"""
The person-name predicate.

Every junk author observed in the catalog audit is a case here — these strings
became authors, were concatenated into API queries, and produced the InDesign
mismatches in §A1.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from catalog.names import clean_authors, is_person_name, normalize_author, split_authors  # noqa: E402

NOT_PEOPLE = [
    "Adobe InDesign CS6 (Macintosh)",
    "Adobe InDesign CS5.5 (7.5)",
    "writer v00.06.02",
    "pdftk 2.02 - www.pdftk.com",
    "LaTeX with hyperref",
    "waseel@hotmail.com",
    "0008471",
    "Kalamullah.Com",
    "www.it-ebooks.info",
    "Microsoft Word",
    "DELL",
    "Acrobat Distiller 9.0.0",
    "GPL Ghostscript 9.05",
    "All",
    "Abu",
    "Al",
    "sani",
    "Islam & Politics",
    "Introduction to Machine Learning",
    "10th Anniversary Edition",
]

PEOPLE = [
    "Rashid Khalidi",
    "Muhammad Asad",
    "Thomas S. Kuhn",
    "Mufti Muhammad Taqi Usmani",
    "Wael B. Hallaq",
    "Joseph Henrich",
    "O'Brien Smith",
    "Al-Ghazali Ahmad",
    "محمد أسد",
]


class TestIsPersonName(unittest.TestCase):
    def test_tools_versions_urls_and_fragments_are_rejected(self):
        wrong = [s for s in NOT_PEOPLE if is_person_name(s)]
        self.assertEqual([], wrong, f"accepted as people: {wrong}")

    def test_real_names_are_accepted(self):
        wrong = [s for s in PEOPLE if not is_person_name(s)]
        self.assertEqual([], wrong, f"rejected real names: {wrong}")


class TestAuthorNormalisation(unittest.TestCase):
    def test_last_first_is_flipped(self):
        self.assertEqual("Muhammad Asad", normalize_author("Asad, Muhammad"))
        self.assertEqual("Rashid Khalidi", normalize_author("Rashid Khalidi"))

    def test_split_on_real_delimiters(self):
        self.assertEqual(
            ["Jane Doe", "John Roe"], split_authors("Jane Doe and John Roe")
        )
        self.assertEqual(["Thomas S. Kuhn"], split_authors("Kuhn, Thomas S."))

    def test_clean_authors_drops_junk_entries(self):
        self.assertEqual(
            ["Chip Huyen"],
            clean_authors(["Chip Huyen", "Adobe InDesign CS6 (Macintosh)", "0008471"]),
        )


if __name__ == "__main__":
    unittest.main()
