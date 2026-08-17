"""
Stage lifecycle: resumability, invalidation and the rebuild path.

These cover the failure the review called critical — bumping a stage version
used to wipe every record's categories, themes and LLM summaries — plus the
user-data preservation that `CatalogStore.upsert` promises.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from catalog import pipeline as pipeline_mod  # noqa: E402
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

    def test_current_record_runs_nothing(self):
        self.assertEqual(self.outdated(enriched_record()), set())

    def test_stale_enrich_drags_the_whole_metadata_cohort(self):
        record = enriched_record()
        record.stage_versions["enrich"] = STAGE_VERSIONS["enrich"] - 1
        outdated = self.outdated(record)
        for stage in ("parse", "extract", "ocr", "identify", "enrich"):
            self.assertIn(stage, outdated)

    def test_stale_enrich_invalidates_its_consumers(self):
        record = enriched_record()
        record.stage_versions["enrich"] = STAGE_VERSIONS["enrich"] - 1
        outdated = self.outdated(record, llm_enrich=True, embed=True)
        self.assertIn("analyze", outdated)
        self.assertIn("llm", outdated)     # transitive: enrich → analyze → llm
        self.assertIn("embed", outdated)

    def test_disabled_stages_are_never_scheduled(self):
        record = enriched_record()
        record.stage_versions["enrich"] = STAGE_VERSIONS["enrich"] - 1
        outdated = self.outdated(record, enrich_api=False)
        self.assertNotIn("enrich", outdated)
        self.assertNotIn("llm", outdated)

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


if __name__ == "__main__":
    unittest.main()
