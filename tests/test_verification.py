"""
The verification gate.

Five real files were matched to completely unrelated books. Those exact
pairings are asserted to be rejected here, and genuine matches are asserted to
be accepted.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from catalog.evidence import (  # noqa: E402
    ACCEPT,
    PARTIAL,
    REJECT,
    Candidate,
    Evidence,
    TitleClue,
    best_candidate,
    collect_evidence,
    score_candidate,
)
from catalog.models import BookRecord  # noqa: E402


def evidence(title="", source="filename", authors=None, year=None, isbns=None):
    ev = Evidence()
    if title:
        ev.titles.append(TitleClue(text=title, source=source))
    ev.authors = authors or []
    ev.year = year
    ev.isbns = set(isbns or [])
    return ev


class TestKnownMismatches(unittest.TestCase):
    """Each of these was written into the catalog as fact."""

    def test_aisha_is_not_an_indesign_manual(self):
        ev = evidence("Aisha")
        cand = Candidate(
            provider="google_books",
            title="InDesign CS5 for Macintosh and Windows",
            subtitle="Visual QuickStart Guide",
            authors=["Sandee Cohen"],
            isbn_13="9780321717764",
        )
        self.assertEqual(REJECT, score_candidate(cand, ev)["verdict"])

    def test_conflicts_of_fitness_is_not_interactive_indesign(self):
        ev = evidence("CONFLICTS of FITNESS")
        cand = Candidate(provider="google_books", title="Interactive InDesign CC",
                         authors=["Mira Rubin"], isbn_13="9781483437170")
        self.assertEqual(REJECT, score_candidate(cand, ev)["verdict"])

    def test_quran_pdf_is_not_a_deoband_monograph(self):
        ev = evidence("15 Line Standard Quran")
        cand = Candidate(
            provider="google_books",
            title="Diverse Narratives and Shared Beliefs: Deoband Islam",
            isbn_13="9781040393369",
        )
        self.assertEqual(REJECT, score_candidate(cand, ev)["verdict"])

    def test_dawah_booklet_is_not_understanding_salafism(self):
        ev = evidence("80 Ways Make Dawah")
        cand = Candidate(provider="google_books", title="Understanding Salafism",
                         authors=["Yasir Qadhi"], isbn_13="9781786078490")
        self.assertEqual(REJECT, score_candidate(cand, ev)["verdict"])

    def test_hinduism_booklet_is_not_women_in_africa(self):
        ev = evidence("2 Muslim Perspectives on Hinduism")
        cand = Candidate(provider="google_books",
                         title="Perspectives on Power: Women in Africa, Asia and Latin America")
        self.assertEqual(REJECT, score_candidate(cand, ev)["verdict"])


class TestGenuineMatches(unittest.TestCase):
    def test_exact_title_and_author_is_accepted(self):
        ev = evidence("Understanding Salafism", authors=["Yasir Qadhi"], year=2024)
        cand = Candidate(provider="google_books", title="Understanding Salafism",
                         authors=["Yasir Qadhi"], year=2024, isbn_13="9781786078490")
        result = score_candidate(cand, ev)
        self.assertEqual(ACCEPT, result["verdict"])
        self.assertGreaterEqual(result["score"], 0.9)

    def test_subtitle_extension_is_accepted(self):
        ev = evidence("The Road To Mecca", authors=["Muhammad Asad"])
        cand = Candidate(provider="openlibrary", title="The Road to Mecca",
                         authors=["Muhammad Asad"])
        self.assertEqual(ACCEPT, score_candidate(cand, ev)["verdict"])

    def test_isbn_hit_is_identity(self):
        ev = evidence("Webready Content Text", isbns={"9789004412866"})
        cand = Candidate(provider="openlibrary",
                         title="Ibn Taymiyya on Reason and Revelation",
                         isbn_13="9789004412866")
        result = score_candidate(cand, ev)
        self.assertEqual(ACCEPT, result["verdict"])
        self.assertEqual(1.0, result["score"])
        self.assertTrue(result["reason"].startswith("isbn match"))


class TestEvidenceSufficiency(unittest.TestCase):
    def test_one_word_title_is_not_searchable(self):
        self.assertFalse(evidence("Aisha").title_is_searchable())
        self.assertFalse(evidence("757").title_is_searchable())
        self.assertFalse(evidence("").title_is_searchable())

    def test_real_title_is_searchable(self):
        self.assertTrue(evidence("The Road To Mecca").title_is_searchable())

    def test_front_matter_outranks_filename_as_query_source(self):
        ev = Evidence()
        ev.titles = [
            TitleClue(text="Webready Content Text", source="filename"),
            TitleClue(text="Ibn Taymiyya on Reason and Revelation", source="front_matter"),
        ]
        self.assertEqual("Ibn Taymiyya on Reason and Revelation", ev.best_title())


class TestBestCandidateAcrossProviders(unittest.TestCase):
    def test_picks_the_best_scoring_candidate_not_the_first(self):
        ev = evidence("The Structure of Scientific Revolutions", authors=["Thomas S. Kuhn"])
        weak = Candidate(provider="openlibrary", title="Scientific Revolution: A Very Short Introduction")
        strong = Candidate(provider="google_books",
                           title="The Structure of Scientific Revolutions",
                           authors=["Thomas S. Kuhn"])
        best, verdict, _ = best_candidate([weak, strong], ev)
        self.assertIsNotNone(best)
        self.assertEqual("google_books", best.provider)
        self.assertEqual(ACCEPT, verdict["verdict"])

    def test_all_rejected_returns_none_and_logs_rejections(self):
        ev = evidence("CONFLICTS of FITNESS")
        cands = [
            Candidate(provider="google_books", title="Interactive InDesign CC"),
            Candidate(provider="openlibrary", title="Adobe InDesign Classroom in a Book"),
        ]
        best, verdict, rejections = best_candidate(cands, ev)
        self.assertIsNone(best)
        self.assertEqual(REJECT, verdict["verdict"])
        self.assertEqual(2, len(rejections))


class TestProvenanceRules(unittest.TestCase):
    def test_weaker_source_cannot_overwrite_stronger(self):
        record = BookRecord()
        record.set_field("title", "Verified Title", "api_verified", 0.9)
        record.set_field("title", "Filename Title", "filename", 0.4)
        self.assertEqual("Verified Title", record.title)

    def test_user_pins_are_never_overwritten(self):
        record = BookRecord()
        record.set_field("title", "Human Corrected", "user", 1.0)
        record.set_field("title", "API Title", "isbn_match", 1.0)
        self.assertEqual("Human Corrected", record.title)

    def test_stronger_source_wins(self):
        record = BookRecord()
        record.set_field("title", "Filename Title", "filename", 0.4)
        record.set_field("title", "Verified Title", "api_verified", 0.8)
        self.assertEqual("Verified Title", record.title)
        self.assertEqual("api_verified", record.field_source("title"))

    def test_borderline_match_cannot_write_identity_fields(self):
        from catalog.api_enricher import _apply_candidate
        record = BookRecord()
        record.set_field("title", "Local Title", "filename", 0.4)
        cand = Candidate(provider="google_books", title="Some Other Book",
                         authors=["Someone Else"], isbn_13="9780321717764",
                         description="A description.")
        _apply_candidate(record, cand, "api_partial", 0.5, identity=False)
        self.assertEqual("Local Title", record.title)
        self.assertEqual("", record.isbn_13)
        self.assertEqual("A description.", record.description)


class TestEvidenceCollection(unittest.TestCase):
    def test_collects_titles_authors_and_isbns_from_a_record(self):
        record = BookRecord()
        record.file_name = "9789004412866_webready_content_text.pdf"
        record.set_field("title", "Webready Content Text", "filename", 0.4)
        record.original_title_meta = "Ibn Taymiyya on Reason and Revelation"
        record.set_field("isbn_13", "9789004412866", "filename", 0.9)
        ev = collect_evidence(record)
        self.assertIn("9789004412866", ev.isbns)
        self.assertTrue(any("Ibn Taymiyya" in c.text for c in ev.titles))


if __name__ == "__main__":
    unittest.main()
