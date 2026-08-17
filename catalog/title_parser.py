"""
Filename parser — turns a book filename into title / authors / publisher / year
/ identifiers.

The important rules:

* identifiers are *extracted* before the title is cleaned, never deleted;
* an "Author - Title" split requires real whitespace around the dash, so
  `Abu-Dhar-Al-Gifari-Struggle-for-Equality` is no longer read as author "Abu";
* which side is the author is decided by `is_person_name`, not by position, so
  both `Author - Title` and `Title - Author` work;
* a hyphen-joined name with no spaces at all is a spaced title.
"""
import logging
import re

from .isbn_extractor import find_source_ids, isbns_from_filename, normalize_isbn
from .names import is_person_name, normalize_author

logger = logging.getLogger(__name__)

# Source-site and download-artefact markers.
STRIP_PATTERNS = [
    r"^dokumen\.pub_",
    r"^ebin\.pub_",
    r"^vdoc\.pub_",
    r"^kupdf\.net_",
    r"^pdfcoffee\.com_",
    r"^toaz\.info-",
    r"^noor-book\.com\s+",
    r"^annas-archive\S*_",
    r"^\[\s*\]\s*",
    r"\s*[-_]\s*libgen(?:\.li|\.rs|\.is)?\s*$",
    r"\s*\(\s*z-lib\.org\s*\)\s*$",
    r"\s*\(\s*PDFDrive(?:\.com)?\s*\)\s*$",
    r"\s*\(\s*book-drive\.com\s*\)\s*$",
    r"\s*\(\s*www\.[^)]+\)\s*$",
    r"_[a-z0-9]{6,}goog$",             # Internet Archive google-scan suffix
    r"_djvu$",
    r"\s*\(\d+\)\s*$",                 # "(1)" duplicate marker
    r"\s+copy(?:\s+\d+)?$",
    r"^[0-9a-f]{20,}[_-]",             # hash-like prefix
    r"^\d{8,}[_-]",                    # download-site numeric id prefix
    r"^\d{1,3}\.\s+",                  # "10. " list prefix (never a bare "80-")
    r"[-_\s]+(?:pdf|epub|mobi|ebook|e-book|book)$",
    r"^(?:en|ar|ur|fr|de|es)[-_](?=[a-z])",   # locale prefix
    r"[-_](?:en|eng|ar|ara|urd|ur)$",         # locale suffix
    r"[-_\s]+(?:final|draft|v\d+|rev\d*|ocr|scan(?:ned)?|compressed|merged)$",
]

PUBLISHER_PATTERNS = [
    r"[-–]\s*O'Reilly\s+Media(?:,\s*Inc\.?)?\s*(?:\(\d{4}\))?",
    r"[-–]\s*Packt\s+Publishing(?:\s+Ltd)?\s*(?:\(\d{4}\))?",
    r"[-–]\s*Manning(?:\s+Publications?)?\s*(?:\(\d{4}\))?",
    r"[-–]\s*Springer(?:\s+International)?\s*(?:\(\d{4}\))?",
    r"[-–]\s*(?:Prentice\s+Hall|Wiley|McGraw.Hill|Cambridge|Oxford|Harvard)\s*(?:\(\d{4}\))?",
    r"[-–]\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Press|Publishing|Publications|Books)\s*(?:\(\d{4}\))?",
]

PUBLISHER_NAMES = re.compile(
    r"(O'Reilly Media|Packt Publishing|Manning Publications?|Manning|"
    r"Springer|Prentice Hall|Wiley|McGraw.Hill|Cambridge University Press|"
    r"Oxford University Press|Harvard University Press|Grove Press|"
    r"Penguin Books?|Random House|Free Press|Columbia University Press|"
    r"Oneworld (?:Publications?|Academic)|FT Publishing|Independently Published|"
    r"Equilibra Press|The Book Foundation|Bayt Al-Hikma Press|"
    r"Turath Publishing|Rigel Publishing|University of Chicago Press|"
    r"Farrar,?\s*Straus.*?Giroux|Citadel Press|American Trust Publications|"
    r"No Starch Press|Apress|Addison.Wesley|MIT Press|Routledge|"
    r"Hurst|Brill|For Dummies)",
    re.IGNORECASE,
)

YEAR_PATTERN = re.compile(r"\((\d{4})(?:[,_/]\s*[^)]*)?\)")
YEAR_BARE = re.compile(r"(?<!\d)(1[89]\d{2}|20[0-3]\d)(?!\d)")

# A split candidate must have real whitespace around the dash.
_SPACED_DASH = re.compile(r"\s+[-–—]\s+")

_SMALL_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "vs", "vs.", "as", "is", "its",
}


def extract_year_from_filename(filename: str) -> int | None:
    """Extract a publication year, preferring one inside parentheses."""
    for year_str in YEAR_PATTERN.findall(filename):
        year = int(year_str)
        if 1800 <= year <= 2030:
            return year
    for year_str in YEAR_BARE.findall(filename):
        year = int(year_str)
        if 1900 <= year <= 2030:
            return year
    return None


def extract_publisher_from_filename(filename: str) -> str:
    m = PUBLISHER_NAMES.search(filename)
    return m.group(1).strip() if m else ""


def _strip_identifiers(name: str) -> str:
    """Remove ISBNs and archive identifiers already captured elsewhere."""
    isbn13, isbn10 = isbns_from_filename(name)
    for isbn in (isbn13, isbn10):
        if not isbn:
            continue
        # Remove both the plain and the hyphenated rendering.
        name = re.sub(r"(?<!\d)" + r"[\-–\s]?".join(isbn) + r"(?!\d)", " ", name)
    for sid in find_source_ids(name):
        value = sid.split(":", 1)[1]
        name = name.replace(value, " ")
    return name


def _normalise_separators(name: str) -> str:
    """
    Underscores become spaces (`_ ` is libgen's colon), and hyphens become
    spaces when they are clearly acting as word separators.

    The test is positional, not global: a filename with a spaced dash uses the
    dash as an author/title separator and its remaining hyphens are real
    (`Al-Ghazali`), so those are left alone.
    """
    name = re.sub(r"_\s+", ": ", name)
    name = name.replace("_", " ")
    name = re.sub(r"\s{2,}", " ", name).strip()

    if _SPACED_DASH.search(name):
        return name
    hyphens = name.count("-")
    spaces = name.count(" ")
    if (hyphens >= 2 and hyphens >= spaces) or (hyphens >= 1 and spaces == 0):
        name = name.replace("-", " ")
    return re.sub(r"\s{2,}", " ", name).strip()


def _clean_markers(name: str) -> str:
    previous = None
    while previous != name:
        previous = name
        for pattern in STRIP_PATTERNS:
            name = re.sub(pattern, " ", name, flags=re.IGNORECASE).strip()
    return name


def _remove_metadata_parens(name: str) -> str:
    # Anything parenthesised that opens with a year: "(2019, Equilibra Press)",
    # "(2014_2012, Columbia University Press)", "(2022)".
    name = re.sub(r"\(\s*\d{4}[^)]*\)", " ", name)
    # Trailing publisher parentheticals: "(Oneworld Academic)", "(Manning)".
    name = re.sub(
        r"\([^)]*\b(?:Press|Publishing|Publications?|Publishers?|Books?|Media|"
        r"Academic|University|Ltd|Inc|GmbH)\b[^)]*\)",
        " ", name, flags=re.IGNORECASE,
    )
    name = re.sub(r"\(\s*\)", " ", name)
    for pattern in PUBLISHER_PATTERNS:
        name = re.sub(pattern, " ", name, flags=re.IGNORECASE)
    return name


def split_author_title(name: str) -> tuple[str, list[str]]:
    """
    Split "Author - Title" or "Title - Author" using the person predicate.

    Returns (title, authors). When neither side looks like a person the whole
    string is the title — the old code guessed, and guessed wrong often.
    """
    parts = [p.strip() for p in _SPACED_DASH.split(name) if p.strip()]
    if len(parts) < 2:
        return name.strip(), []

    left, right = parts[0], _SPACED_DASH.split(name, maxsplit=1)[1].strip()
    left_is_person = is_person_name(left)
    right_is_person = is_person_name(right)

    if left_is_person and not right_is_person:
        return right, [normalize_author(left)]
    if right_is_person and not left_is_person:
        return left, [normalize_author(right)]
    if left_is_person and right_is_person:
        # Ambiguous: the shorter side is the author, the longer the title.
        if len(left) <= len(right):
            return right, [normalize_author(left)]
        return left, [normalize_author(right)]
    return name.strip(), []


def tidy_title(name: str) -> str:
    name = re.sub(r"\s*[-–—]\s*[-–—]\s*", " - ", name)
    name = name.strip(" -–—_.,;:")
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"\s+([:,;])", r"\1", name)
    if not name:
        return ""
    if name == name.lower() or name == name.upper():
        words = name.split()
        out = []
        for i, word in enumerate(words):
            if i == 0 or word.lower() not in _SMALL_WORDS:
                out.append(word[:1].upper() + word[1:].lower() if word.isupper() else word.capitalize())
            else:
                out.append(word.lower())
        name = " ".join(out)
    return name.strip()


def clean_title(filename: str) -> str:
    """Clean a book filename into a human-readable title."""
    return parse_filename(filename)["title"]


def parse_filename(filename: str) -> dict:
    """
    Parse a book filename into every piece of metadata it carries.

    Returns: title, authors, publisher, publication_year, isbn_13, isbn_10,
    source_ids.
    """
    stem = re.sub(r"\.\w{2,5}$", "", filename or "")

    isbn13, isbn10 = isbns_from_filename(stem)
    source_ids = find_source_ids(stem)
    year = extract_year_from_filename(stem)
    publisher = extract_publisher_from_filename(stem)

    name = _strip_identifiers(stem)
    name = _clean_markers(name)
    name = _remove_metadata_parens(name)
    name = _normalise_separators(name)
    name = _clean_markers(name)

    title, authors = split_author_title(name)
    title = tidy_title(title)

    # A title with no letters at all (bare digits, punctuation) says nothing.
    if title and not re.search(r"[^\W\d_]", title, re.UNICODE):
        title = ""

    result = {
        "title": title,
        "authors": [a for a in authors if a],
        "publisher": publisher,
        "publication_year": year,
        "isbn_13": normalize_isbn(isbn13) if isbn13 else "",
        "isbn_10": normalize_isbn(isbn10) if isbn10 else "",
        "source_ids": source_ids,
    }
    logger.debug(f"Parsed '{filename}' -> {result}")
    return result


def extract_author_from_filename(filename: str) -> list[str]:
    """Legacy helper retained for callers outside the pipeline."""
    return parse_filename(filename)["authors"]
