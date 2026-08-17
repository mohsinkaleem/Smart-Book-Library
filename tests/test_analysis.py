"""
Taxonomy, category scoring, keyword determinism, ISBN harvesting and text
partitioning.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from catalog.isbn_extractor import (  # noqa: E402
    find_isbns,
    find_source_ids,
    harvest_identifiers,
    isbns_from_filename,
    validate_isbn13,
)
from catalog.models import BookRecord  # noqa: E402
from catalog.taxonomy import (  # noqa: E402
    CANONICAL_CATEGORIES,
    clean_subjects,
    constrain_categories,
    is_junk_subject,
    map_to_canonical,
)
from catalog.text_utils import parse_front_matter, partition_pages  # noqa: E402
from catalog.theme_analyzer import detect_categories, extract_keywords  # noqa: E402


class TestIsbnHarvesting(unittest.TestCase):
    def test_isbn_in_filename_with_underscore_boundary(self):
        # The old pattern `\b\d{10,13}\b` could not match here at all.
        isbn13, _ = isbns_from_filename("9789004412866_webready_content_text.pdf")
        self.assertEqual("9789004412866", isbn13)

    def test_both_isbns_in_a_dokumen_pub_name(self):
        isbn13, isbn10 = isbns_from_filename(
            "dokumen.pub_data-analysis-1801817472-9781801817479.epub"
        )
        self.assertEqual("9781801817479", isbn13)
        self.assertEqual("1801817472", isbn10)

    def test_check_digits_are_validated(self):
        self.assertTrue(validate_isbn13("9789004412866"))
        self.assertFalse(validate_isbn13("9789004412867"))

    def test_labelled_isbn_in_front_matter(self):
        i13, _ = find_isbns("First published 2019\nISBN 978-1-78607-849-0\nAll rights reserved")
        self.assertEqual(["9781786078490"], i13)

    def test_internet_archive_identifier_kept_as_source_id(self):
        self.assertEqual(["ia:2015.168284"], find_source_ids("2015.168284.Man-The-Unknown"))

    def test_harvest_writes_provenance(self):
        record = BookRecord(file_name="9789004412866_webready_content_text.pdf")
        harvest_identifiers(record)
        self.assertEqual("9789004412866", record.isbn_13)
        self.assertEqual("filename", record.field_source("isbn_13"))


class TestTaxonomy(unittest.TestCase):
    def test_aliases_collapse_the_split_facets(self):
        self.assertEqual("Computer Science", map_to_canonical("Computers"))
        self.assertEqual("Economics & Finance", map_to_canonical("Business & Economics"))
        self.assertEqual("Religion & Philosophy", map_to_canonical("Religion"))
        self.assertEqual("Islam & Islamic Studies", map_to_canonical("Islam"))

    def test_unknown_labels_do_not_enter_the_vocabulary(self):
        self.assertEqual("", map_to_canonical("Faith and reason"))
        self.assertEqual([], constrain_categories(["Faith and reason", "Power (Social sciences)."]))

    def test_constrained_categories_are_always_canonical(self):
        result = constrain_categories(["Computers", "Religion", "Nonsense Label"])
        self.assertTrue(all(c in CANONICAL_CATEGORIES for c in result))

    def test_person_names_and_bare_nouns_are_not_subjects(self):
        self.assertTrue(is_junk_subject("Asad, Muhammad"))
        self.assertTrue(is_junk_subject("Human beings"))
        self.assertTrue(is_junk_subject("Accessible book"))
        self.assertFalse(is_junk_subject("Islamic philosophy"))

    def test_clean_subjects_deduplicates_and_filters(self):
        self.assertEqual(
            ["Islamic philosophy", "Sufism"],
            clean_subjects(["Islamic philosophy", "islamic philosophy", "Asad, Muhammad", "Sufism"]),
        )


class TestCategoryScoring(unittest.TestCase):
    def test_no_metadata_means_no_categories(self):
        """`1658134075976.pdf` had an empty title and was still given two."""
        record = BookRecord(file_name="1658134075976.pdf", title="")
        record.content_sample = (
            "This page mentions a computer once and prayer once. " * 3
        )
        self.assertEqual([], detect_categories(record))

    def test_title_evidence_outweighs_passing_body_mentions(self):
        record = BookRecord(title="Designing Machine Learning Systems")
        record.content_sample = "A book about history and empire. " * 40
        categories = detect_categories(record)
        self.assertIn("Data Science & ML", categories)

    def test_mapped_external_subject_counts(self):
        record = BookRecord(title="Some Book")
        record.subjects_raw = ["Computers"]
        self.assertIn("Computer Science", detect_categories(record))


class TestKeywordDeterminism(unittest.TestCase):
    def test_same_input_gives_the_same_keywords(self):
        record = BookRecord(title="Machine Learning with Python")
        record.content_sample = (
            "machine learning python programming statistics deep learning neural network "
            "data science algorithm docker cloud api regression clustering pandas numpy "
        ) * 3
        runs = [extract_keywords(record) for _ in range(5)]
        self.assertEqual(1, len({tuple(r) for r in runs}), f"non-deterministic: {runs}")
        self.assertLessEqual(len(runs[0]), 15)

    def test_non_latin_text_gets_no_english_keywords(self):
        record = BookRecord(title="كتاب", script="arabic")
        record.content_sample = "هذا كتاب عن العلم والفلسفة" * 10
        self.assertEqual([], extract_keywords(record))


class TestTextPartitioning(unittest.TestCase):
    def test_content_sample_skips_front_matter_and_toc(self):
        pages = [
            "RETHINKING\nISLAM & THE WEST\nAhmed Paul Keeler\nEQUILIBRA",
            "© 2019 Ahmed Paul Keeler\nAll rights reserved.\nISBN 978-1-5272-4364-9",
            "Contents\nChapter One ......... 1\nChapter Two ......... 24",
            "The crisis of our age is not primarily economic. " * 20,
        ]
        parts = partition_pages(pages)
        self.assertIn("All rights reserved", parts["front_matter"])
        self.assertIn("crisis of our age", parts["content_sample"])
        self.assertNotIn("All rights reserved", parts["content_sample"])
        self.assertNotIn("Chapter One", parts["content_sample"])

    def test_front_matter_yields_title_and_author(self):
        front = parse_front_matter(
            "RETHINKING ISLAM & THE WEST\nA New Narrative for the Age of Crises\n"
            "Ahmed Paul Keeler\nEquilibra Press\n© 2019"
        )
        self.assertEqual("RETHINKING ISLAM & THE WEST", front["title"])
        self.assertIn("Ahmed Paul Keeler", front["authors"])

    def test_archive_notice_is_not_a_subtitle(self):
        # This notice reached OpenLibrary as part of the query title, because
        # `evidence` joins title and subtitle: the search became "Thomas S. Kuhn
        # The Structure Of Scientific Revolutions This book was produced in EPUB
        # format by the Internet Archive." — 5x slower and a worse match.
        front = parse_front_matter(
            "Thomas S. Kuhn The Structure Of Scientific Revolutions\n"
            "This book was produced in EPUB format by the Internet Archive."
        )
        self.assertEqual("", front["subtitle"])

    def test_real_subtitle_still_survives(self):
        front = parse_front_matter(
            "RETHINKING ISLAM & THE WEST\nA New Narrative for the Age of Crises\n"
            "Ahmed Paul Keeler"
        )
        self.assertEqual("A New Narrative for the Age of Crises", front["subtitle"])

    def test_dedication_line_is_not_an_author(self):
        # "My dear Hodgson" was harvested off the dedication page and sent as
        # `author=` for The Indian Musalmans.
        front = parse_front_matter(
            "THE INDIAN MUSALMANS\nMy dear Hodgson\nTrubner and Company"
        )
        self.assertNotIn("My Dear Hodgson", front["authors"])
        self.assertEqual([], front["authors"])


if __name__ == "__main__":
    unittest.main()
