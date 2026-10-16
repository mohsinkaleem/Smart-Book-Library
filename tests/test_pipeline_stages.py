"""
Stage lifecycle: resumability, invalidation and the rebuild path.

These cover the failure the review called critical — bumping a stage version
used to wipe every record's categories, themes and LLM summaries — plus the
user-data preservation that `CatalogStore.upsert` promises.
"""
import json
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from catalog import pipeline as pipeline_mod  # noqa: E402
from catalog import schema  # noqa: E402
from catalog.config import STAGE_VERSIONS  # noqa: E402
from catalog.models import BookRecord  # noqa: E402
from catalog.pipeline import Pipeline, PipelineConfig  # noqa: E402
from catalog.store import CatalogStore  # noqa: E402


def enriched_record(**overrides) -> BookRecord:
    """A record as it looks after a complete successful run."""
    record = BookRecord(
        id="sha-1",
        content_sha1="sha-1",
        file_path="pdfs/book.pdf",
        file_name="book.pdf",
        file_type="pdf",
        size=1024,
    )
    record.set_field("title", "Filename Title", "filename", 0.4)
    record.set_field("title", "Verified Title", "api_verified", 0.9)
    record.set_field("authors", ["Jane Doe"], "api_verified", 0.9)
    record.set_field("categories", ["History"], "analyzer", 0.5)
    record.set_field("themes", ["empire"], "analyzer", 0.5)
    record.set_field("summary", "An LLM summary.", "llm", 0.6)
    record.text_excerpt = "body text"
    record.content_sample = "body text"
    record.stage_versions = dict(STAGE_VERSIONS)
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


class StageTestCase(unittest.TestCase):
    """Gives each test a real Pipeline backed by a throwaway database."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.store = CatalogStore(self.dir / "catalog.db")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def pipeline(self, **config_kwargs) -> Pipeline:
        return Pipeline(PipelineConfig(scan=False, **config_kwargs), store=self.store)


class TestOutdatedStages(StageTestCase):
    def outdated(self, record, **config_kwargs):
        return self.pipeline(**config_kwargs)._outdated_stages(record, True)

    @staticmethod
    def stale_metadata(record) -> BookRecord:
        record.stage_versions["metadata"] = STAGE_VERSIONS["metadata"] - 1
        return record

    def test_current_record_runs_nothing(self):
        self.assertEqual(self.outdated(enriched_record()), set())

    def test_a_stale_metadata_unit_schedules_all_five_of_its_stages(self):
        outdated = self.outdated(self.stale_metadata(enriched_record()))
        for stage in ("parse", "extract", "ocr", "identify", "enrich"):
            self.assertIn(stage, outdated)

    def test_stale_metadata_invalidates_its_consumers(self):
        outdated = self.outdated(
            self.stale_metadata(enriched_record()), llm_enrich=True, embed=True
        )
        self.assertIn("analyze", outdated)
        self.assertIn("llm", outdated)     # transitive: metadata → analyze → llm
        self.assertIn("embed", outdated)

    def test_disabled_stages_are_never_scheduled(self):
        outdated = self.outdated(self.stale_metadata(enriched_record()), enrich_api=False)
        self.assertNotIn("enrich", outdated)
        self.assertNotIn("llm", outdated)
        self.assertIn("parse", outdated)   # the rest of the unit still runs

    def test_a_stale_analyze_leaves_the_metadata_alone(self):
        record = enriched_record()
        record.stage_versions["analyze"] = STAGE_VERSIONS["analyze"] - 1
        outdated = self.outdated(record)
        self.assertEqual(outdated, {"analyze"})

    def test_force_runs_every_enabled_stage(self):
        outdated = self.outdated(enriched_record(), force_reprocess=True)
        self.assertEqual(outdated, {"parse", "extract", "ocr", "identify", "enrich", "analyze"})


class TestInvalidation(StageTestCase):
    def invalidate(self, record, outdated):
        self.pipeline()._invalidate(record, outdated)
        return record

    def test_rerunning_enrich_withdraws_only_api_values(self):
        record = self.invalidate(enriched_record(), {"enrich"})
        self.assertEqual(record.title, "")           # was api_verified
        self.assertEqual(record.authors, [])
        self.assertEqual(record.categories, ["History"])   # analyzer keeps its own
        self.assertEqual(record.summary, "An LLM summary.")

    def test_rerunning_analyze_does_not_touch_the_llm_summary(self):
        record = self.invalidate(enriched_record(), {"analyze"})
        self.assertEqual(record.categories, [])
        self.assertEqual(record.themes, [])
        self.assertEqual(record.summary, "An LLM summary.")
        self.assertEqual(record.title, "Verified Title")

    def test_no_api_run_keeps_verified_metadata(self):
        """The bug: a --no-api rebuild used to erase everything the APIs found."""
        record = self.invalidate(enriched_record(), {"parse", "extract", "ocr", "identify"})
        self.assertEqual(record.title, "Verified Title")
        self.assertEqual(record.authors, ["Jane Doe"])

    def test_user_pins_survive_invalidation(self):
        record = enriched_record()
        record.set_field("title", "Human Corrected", "user", 1.0)
        self.invalidate(record, set(pipeline_mod.PER_BOOK_STAGES))
        self.assertEqual(record.title, "Human Corrected")

    def test_review_flags_clear_without_the_api_stage(self):
        record = enriched_record()
        record.flag_review("stale reason")
        self.invalidate(record, {"parse"})
        self.assertFalse(record.needs_review)
        self.assertEqual(record.review_reasons, [])

    def test_review_flags_survive_an_analyze_only_rerun(self):
        record = enriched_record()
        record.flag_review("borderline match")
        self.invalidate(record, {"analyze"})
        self.assertTrue(record.needs_review)

    def test_merged_lists_reset_only_when_enrich_reruns(self):
        record = enriched_record(source_ids=["ia:2015.168284"],
                                 subjects_raw=["From an API"])
        self.invalidate(record, {"parse", "extract", "ocr", "identify"})   # --no-api
        self.assertEqual(record.subjects_raw, ["From an API"])
        self.assertEqual(record.source_ids, ["ia:2015.168284"])

        self.invalidate(record, {"parse", "extract", "ocr", "identify", "enrich"})
        self.assertEqual(record.subjects_raw, [])
        self.assertEqual(record.source_ids, [])


class TestDeferredStages(StageTestCase):
    """A stage that could not do its job must stay stale so the next run retries it."""

    def run_stages(self, pipeline, record, stages):
        pipeline._run_book_stages(record, Path(record.file_path), set(stages))
        return record

    def test_enrich_with_provider_errors_is_retried(self):
        record = enriched_record()
        del record.stage_versions["metadata"]
        pipeline = self.pipeline()
        with unittest.mock.patch.object(
            pipeline_mod, "enrich_from_apis",
            return_value={"verdict": "reject", "incomplete": True, "reason": ""},
        ):
            self.run_stages(pipeline, record, {"enrich"})
        self.assertNotIn("metadata", record.stage_versions)
        self.assertEqual(pipeline.stats["api_deferred"], 1)
        self.assertEqual(pipeline.stats["errors"], 0)

    def test_an_accepted_match_is_final_despite_provider_errors(self):
        record = enriched_record()
        del record.stage_versions["metadata"]
        with unittest.mock.patch.object(
            pipeline_mod, "enrich_from_apis",
            return_value={"verdict": "accept", "incomplete": True, "reason": "isbn match"},
        ):
            self.run_stages(self.pipeline(), record, {"enrich"})
        self.assertEqual(record.stage_versions["metadata"], STAGE_VERSIONS["metadata"])

    def test_llm_stage_waits_for_ollama(self):
        record = enriched_record()
        del record.stage_versions["llm"]
        pipeline = self.pipeline(llm_enrich=True)
        pipeline._llm_ready = False
        self.run_stages(pipeline, record, {"llm"})
        self.assertNotIn("llm", record.stage_versions)

    def test_ocr_stage_waits_for_tesseract(self):
        record = enriched_record(ocr_required=True)
        del record.stage_versions["metadata"]
        with unittest.mock.patch("catalog.ocr_extractor.is_available", return_value=False):
            self.run_stages(self.pipeline(), record, {"ocr"})
        self.assertNotIn("metadata", record.stage_versions)


class TestCoverRenderStage(StageTestCase):
    """
    The cover of last resort, and the two things that make it safe to keep.

    It must never take a slot a real jacket could have, and it must not reopen
    the same blank title page on every run to reach the same conclusion.
    """

    def book(self, **overrides) -> BookRecord:
        record = enriched_record(**overrides)
        record.stage_versions.pop("cover", None)
        self.store.upsert(record)
        return record

    def render(self, pipeline, reason=""):
        """Run the stage with the renderer stubbed; returns what it looked at."""
        seen = []

        def _render(path, record):
            seen.append(record.id)
            if not reason:
                record.set_field("cover_path", "data/covers/x.jpg", "pdf_page_1", 0.1)
            return reason

        with unittest.mock.patch("catalog.pdf_extractor.render_page_1_cover", _render), \
                unittest.mock.patch("catalog.pdf_extractor.can_render_pages", return_value=True), \
                unittest.mock.patch.object(Path, "exists", lambda self: True):
            pipeline._stage_cover_render()
        return seen

    def test_a_book_with_no_cover_gets_its_page_1(self):
        self.book()
        pipeline = self.pipeline()
        self.assertEqual(["sha-1"], self.render(pipeline))
        self.assertEqual(1, pipeline.stats["covers_rendered"])
        self.assertEqual("pdf_page_1", self.store.get_by_path("pdfs/book.pdf").field_source("cover_path"))

    def test_a_book_that_already_has_a_cover_is_never_opened(self):
        """The whole point: a provider's jacket outranks a page of the book."""
        record = enriched_record()
        record.stage_versions.pop("cover", None)
        record.set_field("cover_path", "data/covers/real.jpg", "api_verified", 0.9)
        self.store.upsert(record)
        self.assertEqual([], self.render(self.pipeline()))

    def test_epubs_are_not_candidates(self):
        self.book(id="sha-2", content_sha1="sha-2", file_path="epubs/b.epub", file_type="epub")
        self.assertEqual([], self.render(self.pipeline()))

    def test_a_missing_file_is_not_candidate(self):
        self.book(status="missing")
        self.assertEqual([], self.render(self.pipeline()))

    def test_a_blank_page_1_is_not_retried_on_the_next_run(self):
        self.book()
        first = self.pipeline()
        self.assertEqual(["sha-1"], self.render(first, reason="nothing on the page (0.0000% ink)"))
        self.assertEqual(1, first.stats["covers_unusable"])
        self.assertEqual("", self.store.get_by_path("pdfs/book.pdf").cover_path)

        # Still cover-less, but the attempt is on the record, so a second run
        # does not open the file again.
        self.assertEqual([], self.render(self.pipeline()))

    def test_a_version_bump_asks_again(self):
        self.book()
        self.render(self.pipeline(), reason="nothing on the page (0.0000% ink)")
        with unittest.mock.patch.dict(
            pipeline_mod.STAGE_VERSIONS, {"cover": STAGE_VERSIONS["cover"] + 1}
        ):
            self.assertEqual(["sha-1"], self.render(self.pipeline()))

    def test_the_stage_is_retried_when_pymupdf_is_missing(self):
        """Deferred, not failed: nothing is marked, so the next run tries again."""
        self.book()
        with unittest.mock.patch("catalog.pdf_extractor.can_render_pages", return_value=False):
            self.pipeline()._stage_cover_render()
        self.assertNotIn("cover", self.store.get_by_path("pdfs/book.pdf").stage_versions)

    def test_it_can_be_turned_off(self):
        self.assertFalse(self.pipeline(cover_render=False).config.cover_render)


class TestRenderedCoverYieldsToARealOne(StageTestCase):
    """
    A rendered page 1 is a placeholder, and `_invalidate` treats it as one.

    Without this the first run to render a page would pin that page as the
    cover forever: `save_cover` refuses a record that already has one, so no
    later jacket — embedded, verified or scraped — could ever replace it.
    """

    def invalidate(self, record, outdated):
        self.pipeline()._invalidate(record, outdated)
        return record

    def rendered(self) -> BookRecord:
        record = enriched_record()
        record.set_field("cover_path", "data/covers/sha-1_cover.jpg", "pdf_page_1", 0.1)
        record.mark_stage("cover", STAGE_VERSIONS["cover"])
        return record

    def test_a_metadata_rerun_gives_the_slot_back(self):
        record = self.invalidate(self.rendered(), {"parse", "extract", "ocr", "identify"})
        self.assertEqual("", record.cover_path)
        self.assertNotIn("cover", record.stage_versions)   # so it renders again if nothing better

    def test_a_verified_jacket_survives_a_no_api_rerun(self):
        """Only the placeholder yields. A --no-api rebuild keeps the real one."""
        record = enriched_record()
        record.set_field("cover_path", "data/covers/real.jpg", "api_verified", 0.9)
        record.mark_stage("cover", STAGE_VERSIONS["cover"])
        self.invalidate(record, {"parse", "extract", "ocr", "identify"})
        self.assertEqual("data/covers/real.jpg", record.cover_path)
        self.assertIn("cover", record.stage_versions)

    def test_an_analyze_only_rerun_keeps_the_rendered_cover(self):
        record = self.invalidate(self.rendered(), {"analyze"})
        self.assertEqual("data/covers/sha-1_cover.jpg", record.cover_path)

    def test_a_cover_the_user_pinned_is_never_withdrawn(self):
        record = self.rendered()
        record.set_field("cover_path", "data/covers/mine.jpg", "user", 1.0)
        self.invalidate(record, set(pipeline_mod.PER_BOOK_STAGES))
        self.assertEqual("data/covers/mine.jpg", record.cover_path)


class TestStoreUserData(StageTestCase):
    def test_rating_and_tags_survive_a_content_change(self):
        self.store.upsert(enriched_record())
        self.store.update_user_fields(
            "sha-1", {"user_rating": 4.5, "user_tags": ["reread"], "favorite": True},
            "pdfs/book.pdf",
        )

        # Same path, new bytes: the id moves.
        self.store.upsert(enriched_record(id="sha-2", content_sha1="sha-2"))

        reloaded = self.store.get_by_path("pdfs/book.pdf")
        self.assertEqual(reloaded.id, "sha-2")
        self.assertEqual(reloaded.user_rating, 4.5)
        self.assertEqual(reloaded.user_tags, ["reread"])
        self.assertTrue(reloaded.favorite)
        self.assertEqual(self.store.count(), 1)

    def test_pinned_field_outranks_the_pipeline(self):
        self.store.upsert(enriched_record())
        self.store.pin_field("sha-1", "title", "Human Corrected", "pdfs/book.pdf")

        self.store.upsert(enriched_record(id="sha-2", content_sha1="sha-2"))

        reloaded = self.store.get_by_path("pdfs/book.pdf")
        self.assertEqual(reloaded.title, "Human Corrected")
        self.assertEqual(reloaded.field_source("title"), "user")

    def test_embeddings_follow_the_record_id(self):
        self.store.upsert(enriched_record())
        self.store.store_embedding("sha-1", b"\x00" * 16, None)
        self.assertTrue(self.store.has_embedding("sha-1"))

        self.store.upsert(enriched_record(id="sha-2", content_sha1="sha-2"))

        self.assertTrue(self.store.has_embedding("sha-2"))
        self.assertFalse(self.store.has_embedding("sha-1"))

    def test_search_uses_the_fts_index(self):
        self.store.upsert(enriched_record())
        self.assertEqual([r.id for r in self.store.search("Verified")], ["sha-1"])
        self.assertEqual(self.store.search("nothingmatchesthis"), [])

    def test_search_does_not_choke_on_fts_operators(self):
        self.store.upsert(enriched_record())
        for query in ('title:"', "AND", "*", "verified OR"):
            self.store.search(query)   # must not raise


class TestReadingProgressIsMonotonic(StageTestCase):
    """
    `last_opened` is user-owned: the reader writes it on every open, while
    Spotlight only knows when the *file* was last opened on disk. The stage
    used to write the filesystem hint unconditionally, walking real reading
    history backwards.
    """

    APP_WROTE = "2026-08-18T13:45:00.000Z"      # what the reader stores
    SPOTLIGHT_OLDER = "2026-08-01T09:00:00+00:00"
    SPOTLIGHT_NEWER = "2026-08-19T09:00:00+00:00"

    def setUp(self):
        super().setUp()
        self.record = enriched_record()
        self.store.upsert(self.record)
        self.book = self.dir / "book.pdf"
        self.book.write_bytes(b"%PDF-1.4\n")

    def run_stage(self, spotlight_says):
        """Run the stage with the filesystem hint stubbed to a known value."""
        import catalog.reading_tracker as tracker

        pipe = self.pipeline(reading_progress=True)
        pipe._touched = [self.record]
        pipe.config.only = ["book.pdf"]          # narrowed, so `_touched` is the scope
        with unittest.mock.patch.object(
            tracker, "_get_last_opened_macos", return_value=spotlight_says
        ), unittest.mock.patch.object(pipeline_mod, "PROJECT_ROOT", self.dir):
            self.record.file_path = self.book.name
            pipe._stage_reading_progress()
        return self.store.user_field(self.record.id, "last_opened", self.record.file_path)

    def test_an_older_filesystem_hint_never_overwrites_the_app(self):
        self.store.update_user_fields(
            self.record.id, {"last_opened": self.APP_WROTE}, self.record.file_path
        )
        self.assertEqual(self.run_stage(self.SPOTLIGHT_OLDER), self.APP_WROTE)

    def test_a_newer_filesystem_hint_advances_it(self):
        self.store.update_user_fields(
            self.record.id, {"last_opened": self.APP_WROTE}, self.record.file_path
        )
        self.assertEqual(self.run_stage(self.SPOTLIGHT_NEWER), self.SPOTLIGHT_NEWER)

    def test_it_fills_in_when_nothing_is_recorded_yet(self):
        self.assertEqual(self.run_stage(self.SPOTLIGHT_OLDER), self.SPOTLIGHT_OLDER)

    def test_a_fresh_in_memory_record_still_compares_against_user_data(self):
        """
        The record's own `last_opened` is empty for a record built this run —
        the comparison has to go to `user_data`, or the guard reads as "nothing
        recorded yet" and writes the older hint anyway.
        """
        self.store.update_user_fields(
            self.record.id, {"last_opened": self.APP_WROTE}, self.record.file_path
        )
        self.record.last_opened = None
        self.assertEqual(self.run_stage(self.SPOTLIGHT_OLDER), self.APP_WROTE)


if __name__ == "__main__":
    unittest.main()


class TestEnrichmentStatusBackfill(unittest.TestCase):
    """
    Records written before `enrichment_status` existed get one derived from
    the reasons already on them, so the review split applies without waiting
    for a full pipeline run.
    """

    def setUp(self):
        import sqlite3

        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE TABLE books (id TEXT PRIMARY KEY, review_reasons TEXT, "
            "api_sources TEXT, match_score REAL, needs_review INTEGER, "
            "enrichment_status TEXT DEFAULT '')"
        )
        self.addCleanup(self.conn.close)

    def add(self, book_id, reasons, needs_review=1, api_sources="[]", match_score=None):
        self.conn.execute(
            "INSERT INTO books VALUES (?,?,?,?,?,'')",
            (book_id, json.dumps(reasons), api_sources, match_score, needs_review),
        )

    def derive(self) -> dict:
        schema._backfill_enrichment_status(self.conn)
        return {
            row[0]: (row[1], row[2])
            for row in self.conn.execute(
                "SELECT id, enrichment_status, needs_review FROM books"
            )
        }

    def test_an_llm_rejection_is_rejected_not_borderline(self):
        """
        The needle "llm rejected the borderline match" *contains* "borderline
        match". Matching the shorter one first filed 54 settled rejections as
        decisions still waiting to be made.
        """
        self.add("a", ["llm rejected the borderline match"])
        self.add("b", ["borderline match (0.52) with 'Something Else'"])
        derived = self.derive()
        self.assertEqual(("rejected", 0), derived["a"])
        self.assertEqual(("borderline", 1), derived["b"])

    def test_provider_silence_stops_asking_for_a_human(self):
        self.add("a", ["no provider returned a match"])
        self.add("b", ["insufficient evidence to identify this file"])
        self.add("c", ["no candidate passed verification (below gate)"])
        self.add("d", ["metadata lookup incomplete (provider errors) — will retry"])
        derived = self.derive()
        self.assertEqual(("unmatched", 0), derived["a"])
        self.assertEqual(("no_evidence", 0), derived["b"])
        self.assertEqual(("rejected", 0), derived["c"])
        self.assertEqual(("deferred", 0), derived["d"])

    def test_a_record_with_no_title_still_needs_a_person(self):
        self.add("a", ["no provider returned a match", "no title could be established"])
        self.assertEqual(("unmatched", 1), self.derive()["a"])

    def test_a_clean_api_match_is_verified(self):
        self.add("a", [], needs_review=0, api_sources='["google_books"]', match_score=0.93)
        self.assertEqual(("verified", 0), self.derive()["a"])
