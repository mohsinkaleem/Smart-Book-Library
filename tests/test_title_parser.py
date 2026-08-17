"""
Golden set for filename parsing.

Every case in §A5 is a regression test here. `title_parser` is pure-functional
and pathological-input-driven, which makes it the ideal unit-test target — and
without these there is no way to know whether a regex "fix" helps or hurts.

Run: python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from catalog.title_parser import parse_filename, split_author_title  # noqa: E402

# filename -> expected (title, authors, year, isbn)
GOLDEN: list[tuple[str, dict]] = [
    # ── §A5: the splitter used to shred these ────────────────────────────────
    ("Abu-Dhar-Al-Gifari-Struggle-for-Equality.pdf",
     {"title": "Abu Dhar Al Gifari Struggle for Equality", "authors": []}),
    ("All-The-Arabic-You-Never-Learned-The-First-Time-Around.pdf",
     {"title": "All The Arabic You Never Learned The First Time Around", "authors": []}),
    ("Bryley-Myers-Allen-10th.pdf",
     {"title": "Bryley Myers Allen 10th", "authors": []}),
    ("Islam and Evolution - Al-Ghazali and the Modern Evolutionary Paradigm.pdf",
     {"title": "Islam and Evolution - Al-Ghazali and the Modern Evolutionary Paradigm",
      "authors": []}),

    # ── Both orders of author/title must work ────────────────────────────────
    ("The Hundred Years War on Palestine - Rashid Khalidi.epub",
     {"title": "The Hundred Years War on Palestine", "authors": ["Rashid Khalidi"]}),
    ("Asad, Muhammad - The Road To Mecca (2014, The Book Foundation) - libgen.li.epub",
     {"title": "The Road To Mecca", "authors": ["Muhammad Asad"], "publication_year": 2014}),
    ("Usmani, Mufti Muhammad Taqi - Islam & Politics (2020, Turath Publishing) - libgen.li.epub",
     {"title": "Islam & Politics", "authors": ["Mufti Muhammad Taqi Usmani"],
      "publication_year": 2020}),
    ("[] Marco Peixeiro - Time Series Forecasting in Python (2023, Manning).epub",
     {"title": "Time Series Forecasting in Python", "authors": ["Marco Peixeiro"],
      "publication_year": 2023}),

    # ── Hyphens as word separators ───────────────────────────────────────────
    ("designing-data-intensive-applications.pdf",
     {"title": "Designing Data Intensive Applications"}),
    ("vdoc.pub_blitzed-drugs-in-the-third-reich.epub",
     {"title": "Blitzed Drugs in the Third Reich"}),

    # ── §A4: identifiers are harvested, not deleted ──────────────────────────
    ("9789004412866_webready_content_text.pdf", {"isbn_13": "9789004412866"}),
    ("dokumen.pub_data-analysis-and-machine-learning-with-kaggle-1801817472-9781801817479.epub",
     {"title": "Data Analysis and Machine Learning with Kaggle",
      "isbn_13": "9781801817479", "isbn_10": "1801817472"}),
    ("2015.168284.Man-The-Unknown.pdf",
     {"title": "Man The Unknown", "source_ids": ["ia:2015.168284"]}),

    # ── Numbers that are part of the title must survive ──────────────────────
    ("15-Line-Standard-Quran-PDF.pdf", {"title": "15 Line Standard Quran"}),
    ("80-ways-make-dawah_eng.pdf", {"title": "80 Ways Make Dawah"}),

    # ── Nothing to go on: an empty title is the correct answer ───────────────
    ("1658134075976.pdf", {"title": ""}),
    ("Aisha.pdf", {"title": "Aisha", "authors": []}),

    # ── Publisher/year furniture stripped ────────────────────────────────────
    ("Chip Huyen - Designing Machine Learning Systems-O'Reilly Media, Inc. (2022) (1).epub",
     {"title": "Designing Machine Learning Systems", "authors": ["Chip Huyen"],
      "publication_year": 2022}),
    ("Yasir Qadhi - Understanding Salafism (Oneworld Academic) - libgen.li.epub",
     {"title": "Understanding Salafism", "authors": ["Yasir Qadhi"]}),
]


class TestFilenameGoldenSet(unittest.TestCase):
    def test_golden_set(self):
        failures = []
        for filename, expected in GOLDEN:
            parsed = parse_filename(filename)
            for key, want in expected.items():
                got = parsed[key]
                if got != want:
                    failures.append(f"{filename}\n    {key}: got {got!r}, want {want!r}")
        self.assertEqual([], failures, "\n" + "\n".join(failures))


class TestAuthorTitleSplit(unittest.TestCase):
    def test_requires_real_whitespace_around_dash(self):
        title, authors = split_author_title("Abu-Dhar-Al-Gifari-Struggle")
        self.assertEqual([], authors)
        self.assertEqual("Abu-Dhar-Al-Gifari-Struggle", title)

    def test_author_on_either_side(self):
        self.assertEqual(
            ("The Road To Mecca", ["Muhammad Asad"]),
            split_author_title("Asad, Muhammad - The Road To Mecca"),
        )
        self.assertEqual(
            ("The Hundred Years War on Palestine", ["Rashid Khalidi"]),
            split_author_title("The Hundred Years War on Palestine - Rashid Khalidi"),
        )

    def test_neither_side_a_person_keeps_whole_string(self):
        title, authors = split_author_title(
            "Islam and Evolution - Al-Ghazali and the Modern Evolutionary Paradigm"
        )
        self.assertEqual([], authors)
        self.assertIn("Islam and Evolution", title)


if __name__ == "__main__":
    unittest.main()
