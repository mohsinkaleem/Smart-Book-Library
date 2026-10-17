"""
Merge rules, provider normalisation and extractor hygiene.

Each case below was found in the live catalog: English books tagged `po`/`sp`,
PDF page counts replaced by a print edition's, calibre timestamps stored as
identifiers, every Arabic title sharing one cache entry.
"""
import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from catalog import api_enricher, providers  # noqa: E402
from catalog import enrichment_status as status  # noqa: E402
from catalog.api_enricher import _apply_candidate, enrich_from_apis  # noqa: E402
from catalog.epub_extractor import _harvest_identifiers  # noqa: E402
from catalog.evidence import (  # noqa: E402
    Candidate,
    Evidence,
    TitleClue,
    best_candidate,
    collect_evidence,
)
from catalog.models import BookRecord  # noqa: E402


class TempCacheCase(unittest.TestCase):
    """Keeps provider tests away from `data/api_cache.json`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cache = providers.ResponseCache(Path(self.tmp.name) / "cache.json")
        patcher = unittest.mock.patch.object(providers, "_cache", cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)


class TestMergeRules(unittest.TestCase):
    def test_title_match_fills_but_never_replaces_a_local_isbn(self):
        record = BookRecord(file_type="epub")
        record.set_field("isbn_13", "9789004412866", "front_matter", 0.85)
        cand = Candidate(provider="google_books", title="Some Title", isbn_13="9780321717764")
        _apply_candidate(record, cand, "api_verified", 0.9, identity=True)
        self.assertEqual("9789004412866", record.isbn_13)

        empty = BookRecord(file_type="epub")
        _apply_candidate(empty, cand, "api_verified", 0.9, identity=True)
        self.assertEqual("9780321717764", empty.isbn_13)

    def test_a_pdfs_own_page_count_survives_a_match(self):
        record = BookRecord(file_type="pdf", page_count=412)
        _apply_candidate(record, Candidate(provider="google_books", title="T", page_count=288),
                         "isbn_match", 1.0, identity=True)
        self.assertEqual(412, record.page_count)

    def test_provider_language_is_normalised_and_only_fills_a_gap(self):
        record = BookRecord()
        record.set_field("language", "en", "file_meta", 0.6)
        _apply_candidate(record, Candidate(provider="google_books", title="T", language="por"),
                         "api_verified", 0.9, identity=True)
        self.assertEqual("en", record.language)

        blank = BookRecord()
        _apply_candidate(blank, Candidate(provider="google_books", title="T", language="ger"),
                         "api_verified", 0.9, identity=True)
        self.assertEqual("de", blank.language)

    def test_a_subtitle_borne_match_keeps_the_title(self):
        record = BookRecord()
        record.set_field("title", "Misquoting Muhammad", "file_meta", 0.6)
        cand = Candidate(
            provider="google_books", title="OneWorld",
            subtitle="Misquoting Muhammad: The Challenge and Choices of Interpreting the Prophet's Legacy",
        )
        _apply_candidate(record, cand, "api_verified", 0.9, identity=True)
        self.assertEqual("Misquoting Muhammad", record.title)
        self.assertEqual("", record.subtitle)

    def test_a_subtitle_already_in_the_title_is_not_repeated(self):
        record = BookRecord()
        record.set_field("title", "Sapiens: A Brief History of Humankind", "file_meta", 0.6)
        cand = Candidate(provider="google_books", title="Sapiens",
                         subtitle="A Brief History of Humankind")
        _apply_candidate(record, cand, "api_verified", 0.9, identity=True)
        self.assertEqual("Sapiens: A Brief History of Humankind", record.title)
        self.assertEqual("", record.subtitle)


class TestEvidenceQueries(unittest.TestCase):
    def test_isbn_order_is_deterministic_and_the_records_own_comes_first(self):
        ev = Evidence(isbns={"9780321717764", "9789004412866", "9004412867"},
                      primary_isbns=["9789004412866"])
        ordered = ev.ordered_isbns()
        self.assertEqual("9789004412866", ordered[0])
        # The ISBN-10 is the same book as the first ISBN-13 and is not re-queried.
        self.assertEqual(["9789004412866", "9780321717764"], ordered)

    def test_equal_isbn_scores_break_on_title(self):
        ev = Evidence(isbns={"9780321717764", "9789004412866"})
        ev.titles = [TitleClue("Introduction to Linear Algebra", "filename")]
        advertised = Candidate(provider="openlibrary", title="Computational Science and Engineering",
                               isbn_13="9780321717764")
        actual = Candidate(provider="openlibrary", title="Introduction to Linear Algebra",
                           isbn_13="9789004412866")
        best, verdict, _ = best_candidate([advertised, actual], ev)
        self.assertIs(actual, best)
        self.assertEqual(1.0, verdict["score"])

    def test_main_title_is_searched_when_an_author_narrows_it(self):
        title = "Causal Inference in Python: Applying Causal Inference in the Tech Industry (Fourth Early Release)"
        with_author = Evidence(titles=[TitleClue(title, "filename")], authors=["Matheus Facure"])
        self.assertEqual(["Causal Inference in Python"], with_author.query_titles())
        alone = Evidence(titles=[TitleClue(title, "filename")])
        self.assertEqual([title], alone.query_titles())

    def test_the_records_authors_lead_the_title_page_guess(self):
        record = BookRecord(file_name="x.pdf")
        record.set_field("authors", ["Muhammad Asad"], "file_meta", 0.6)
        record.front_matter = "THE ROAD TO MECCA\nby Any Means"
        self.assertEqual("Muhammad Asad", collect_evidence(record).authors[0])


class TestProviders(TempCacheCase):
    def test_cache_keys_do_not_collide(self):
        self.assertNotEqual(providers._query_key("كتاب التوحيد"), providers._query_key("صحيح البخاري"))
        long_title = "Hands On Recommendation Systems with Python " * 3
        self.assertNotEqual(providers._query_key(long_title, "Rounak Banik"),
                            providers._query_key(long_title))
        # Short ASCII keys keep their old shape, so the existing cache stays valid.
        self.assertEqual("the_road_to_mecca_muhammad_asad",
                         providers._query_key("The Road to Mecca", "Muhammad Asad"))

    def test_an_empty_search_is_cached_as_an_expiring_not_found(self):
        with unittest.mock.patch.object(providers, "_fetch_json", return_value=(providers.OK, {"docs": []})):
            self.assertEqual([], providers.openlibrary_search("Nothing Here"))
        key = f"ol_search_{providers._query_key('Nothing Here')}"
        self.assertEqual(providers.NOT_FOUND, providers._cache.get(key)["status"])

    def test_a_work_level_search_doc_carries_no_edition_fields(self):
        doc = {"title": "Brave New World", "author_name": ["Aldous Huxley"],
               "isbn": ["9780060850524", "9788535914849"], "publisher": ["Globo"],
               "language": ["eng", "por"]}
        with unittest.mock.patch.object(providers, "_fetch_json", return_value=(providers.OK, {"docs": [doc]})):
            cand = providers.openlibrary_search("Brave New World")[0]
        self.assertEqual(("", "", "", ""), (cand.isbn_13, cand.isbn_10, cand.publisher, cand.language))
        self.assertIn("9780060850524", cand.isbns())

    def test_a_throttled_lookup_is_reported_incomplete(self):
        record = BookRecord(file_name="The Road to Mecca.epub")
        record.set_field("title", "The Road to Mecca", "filename", 0.4)
        with unittest.mock.patch.object(providers, "_cooling_down", return_value=True):
            result = enrich_from_apis(record)
        self.assertTrue(result["incomplete"])
        self.assertTrue(any("incomplete" in r for r in record.review_reasons))
        self.assertEqual(status.DEFERRED, record.enrichment_status)
        self.assertFalse(record.needs_review)


class TestEnrichmentStatus(TempCacheCase):
    """
    The split the review queue turns on: "no provider had this book" is a fact
    about OpenLibrary and Google Books, not a record a human can confirm. It
    used to set `needs_review`, which put 153 unactionable rows in front of
    the few that needed a decision.
    """

    @staticmethod
    def searchable() -> BookRecord:
        record = BookRecord(file_name="Some Findable Title.epub")
        record.set_field("title", "Some Findable Title", "filename", 0.4)
        return record

    def test_no_provider_match_is_unmatched_not_review(self):
        with unittest.mock.patch.object(providers, "_fetch_json",
                                        return_value=(providers.OK, {})):
            enrich_from_apis(record := self.searchable())
        self.assertEqual(status.UNMATCHED, record.enrichment_status)
        self.assertFalse(record.needs_review)
        self.assertIn("no provider returned a match", record.review_reasons)

    def test_a_file_with_nothing_to_search_on_is_no_evidence(self):
        record = BookRecord(file_name="757.pdf")
        record.set_field("title", "757", "filename", 0.4)
        enrich_from_apis(record)
        self.assertEqual(status.NO_EVIDENCE, record.enrichment_status)
        self.assertFalse(record.needs_review)

    def test_a_borderline_match_is_the_one_that_asks_for_a_person(self):
        record = self.searchable()
        borderline = {
            "score": 0.5, "verdict": "partial", "reason": "borderline: title=0.50",
        }
        candidate = Candidate(provider="google_books", title="Some Findable Titles",
                              description="A description.")
        with unittest.mock.patch.object(
            api_enricher, "gather_candidates", return_value=[candidate]
        ), unittest.mock.patch.object(
            api_enricher, "best_candidate", return_value=(candidate, borderline, [])
        ):
            enrich_from_apis(record)
        self.assertEqual(status.BORDERLINE, record.enrichment_status)
        self.assertTrue(record.needs_review)

    def test_an_accepted_match_is_verified(self):
        record = self.searchable()
        verdict = {"score": 0.95, "verdict": "accept", "reason": "title=0.95"}
        candidate = Candidate(provider="google_books", title="Some Findable Title",
                              authors=["Jane Doe"])
        with unittest.mock.patch.object(
            api_enricher, "gather_candidates", return_value=[candidate]
        ), unittest.mock.patch.object(
            api_enricher, "best_candidate", return_value=(candidate, verdict, [])
        ):
            enrich_from_apis(record)
        self.assertEqual(status.VERIFIED, record.enrichment_status)
        self.assertFalse(record.needs_review)

    def test_unidentified_covers_every_we_do_not_know_outcome(self):
        self.assertEqual(
            {status.REJECTED, status.UNMATCHED, status.NO_EVIDENCE},
            set(status.UNIDENTIFIED),
        )


class FakeEpub:
    def __init__(self, meta):
        self.meta = meta

    def get_metadata(self, namespace, name):
        return self.meta.get((namespace, name), [])


class TestEpubIdentifiers(unittest.TestCase):
    def test_only_real_identifiers_become_source_ids(self):
        book = FakeEpub({
            ("DC", "identifier"): [("urn:isbn:9789004412866", {}),
                                   ("urn:uuid:0c4b1c5e-8d2c-4a0e-9d8b-5f4a2b1c3d4e", {}),
                                   ("google:AbCdEf123", {})],
            ("DC", "source"): [("Aurangzeb: The Man and the Myth", {})],
            ("OPF", "meta"): [(None, {"name": "calibre:timestamp",
                                      "content": "2015-12-24T14:22:40.524000+00:00"}),
                              (None, {"name": "calibre:title_sort", "content": "Road to Mecca, The"})],
        })
        record = BookRecord()
        _harvest_identifiers(book, record)
        self.assertEqual("9789004412866", record.isbn_13)
        self.assertEqual(["google:AbCdEf123"], record.source_ids)


class TestEmbeddedTitles(unittest.TestCase):
    def test_document_names_are_cleaned_and_real_titles_survive(self):
        from catalog.pdf_extractor import clean_meta_title
        self.assertEqual("Catcher on Rye", clean_meta_title("Microsoft Word - Catcher on Rye.docx"))
        self.assertEqual("Man, the Unknown", clean_meta_title("Man, the Unknown"))
        self.assertEqual("The Little Prince", clean_meta_title("The Little Prince"))
        self.assertEqual("", clean_meta_title("Microsoft Word"))
        self.assertEqual("", clean_meta_title("Adobe InDesign CS5.5 (7.5)"))
        self.assertEqual("", clean_meta_title("Untitled"))


class TestLlmOutputShapes(unittest.TestCase):
    def record(self):
        record = BookRecord(file_name="x.epub")
        record.set_field("title", "The Road to Mecca", "filename", 0.4)
        record.content_sample = "A long passage of prose about a journey across Arabia. " * 5
        return record

    def test_list_shaped_fields_do_not_crash(self):
        from catalog import llm_enricher
        raw = json.dumps({"summary": ["A memoir of a journey to Islam.", "It spans decades of travel."],
                          "themes": "travel", "categories": [["nested"], "Religion"]})
        record = self.record()
        with unittest.mock.patch.object(llm_enricher, "_generate", return_value=raw):
            llm_enricher.generate_llm_summary(record)
        self.assertIn("journey to Islam", record.summary)
        self.assertEqual(["travel"], record.themes)

    def test_no_response_is_raised_for_a_retry(self):
        from catalog import llm_enricher
        with unittest.mock.patch.object(llm_enricher, "_generate", return_value=None):
            with self.assertRaises(llm_enricher.LLMNoResponse):
                llm_enricher.generate_llm_summary(self.record())


if __name__ == "__main__":
    unittest.main()
