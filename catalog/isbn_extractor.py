"""
ISBN harvesting — from filenames, front matter, text and OCR output.

An ISBN is the highest-precision identifier available and it is free: several
filenames in this library carry one outright (`9789004412866_webready….pdf`,
`…-1801817472-9781801817479.epub`). The old strip-list deleted digit runs from
the title instead of using them, and its `\\b\\d{10,13}\\b` pattern did not even
match, because `_` is a word character.

Every ISBN written here is check-digit validated.
"""
import logging
import re
from typing import Iterable, Optional

from .models import BookRecord

logger = logging.getLogger(__name__)

# Digit runs bounded by non-digits (not \b — filenames use "_" separators).
_ISBN13_RAW = re.compile(r"(?<!\d)(97[89][\d\-–\s]{10,17}\d)(?!\d)")
_ISBN10_RAW = re.compile(r"(?<!\d)(\d[\d\-–\s]{8,14}[\dXx])(?![\dXx])")
_ISBN_LABELLED = re.compile(r"ISBN(?:[-\s]?1[03])?\s*[:\-]?\s*([\dXx\-–\s]{10,20})", re.I)

# Stable non-ISBN identifiers worth keeping (Internet Archive, DOI, arXiv).
_IA_ID = re.compile(r"(?<![\w.])(\d{4}\.\d{4,8})(?!\d)")
_IA_GOOG = re.compile(r"\b([a-z0-9]{8,}(?:goog|djvu))\b", re.I)
_DOI = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)\b")
_ARXIV = re.compile(r"\barXiv[:\s]*(\d{4}\.\d{4,5}(?:v\d+)?)\b", re.I)


def validate_isbn13(isbn: str) -> bool:
    if len(isbn) != 13 or not isbn.isdigit() or not isbn.startswith(("978", "979")):
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(isbn))
    return total % 10 == 0


def validate_isbn10(isbn: str) -> bool:
    if len(isbn) != 10:
        return False
    total = 0
    for i, ch in enumerate(isbn):
        if ch in "Xx":
            val = 10
        elif ch.isdigit():
            val = int(ch)
        else:
            return False
        total += val * (10 - i)
    return total % 11 == 0


def normalize_isbn(raw: str) -> str:
    return re.sub(r"[^0-9Xx]", "", raw or "").upper()


def isbn13_to_isbn10(isbn13: str) -> str:
    if not isbn13 or len(isbn13) != 13 or not isbn13.startswith("978"):
        return ""
    body = isbn13[3:12]
    total = sum(int(d) * (10 - i) for i, d in enumerate(body))
    check = (11 - (total % 11)) % 11
    return body + ("X" if check == 10 else str(check))


def isbn10_to_isbn13(isbn10: str) -> str:
    if not isbn10 or len(isbn10) != 10:
        return ""
    body = "978" + isbn10[:9]
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(body))
    return body + str((10 - (total % 10)) % 10)


def find_isbns(text: str) -> tuple[list[str], list[str]]:
    """Return (isbn13s, isbn10s) — validated, in order of appearance."""
    if not text:
        return [], []

    isbn13s: list[str] = []
    isbn10s: list[str] = []

    def _add(candidate: str):
        c = normalize_isbn(candidate)
        if len(c) == 13 and validate_isbn13(c) and c not in isbn13s:
            isbn13s.append(c)
        elif len(c) == 10 and validate_isbn10(c) and c not in isbn10s:
            isbn10s.append(c)

    # Labelled ISBNs first — they are the most trustworthy.
    for m in _ISBN_LABELLED.finditer(text):
        _add(m.group(1))
    for m in _ISBN13_RAW.finditer(text):
        _add(m.group(1))
    for m in _ISBN10_RAW.finditer(text):
        _add(m.group(1))

    return isbn13s, isbn10s


def find_source_ids(text: str) -> list[str]:
    """Stable non-ISBN identifiers found in a filename or front matter."""
    ids: list[str] = []
    for m in _IA_ID.finditer(text or ""):
        ids.append(f"ia:{m.group(1)}")
    for m in _IA_GOOG.finditer(text or ""):
        ids.append(f"ia:{m.group(1)}")
    for m in _DOI.finditer(text or ""):
        ids.append(f"doi:{m.group(1)}")
    for m in _ARXIV.finditer(text or ""):
        ids.append(f"arxiv:{m.group(1)}")
    seen: set[str] = set()
    return [i for i in ids if not (i in seen or seen.add(i))]


def isbns_from_filename(filename: str) -> tuple[Optional[str], Optional[str]]:
    """Extract a validated ISBN pair from a filename, if present."""
    stem = re.sub(r"\.\w{2,5}$", "", filename or "")
    isbn13s, isbn10s = find_isbns(stem)
    return (isbn13s[0] if isbn13s else None, isbn10s[0] if isbn10s else None)


def _fill_pair(record: BookRecord, isbn13: Optional[str], isbn10: Optional[str],
               source: str, confidence: float) -> bool:
    """Write an ISBN pair with provenance, deriving the missing half."""
    wrote = False
    if isbn13 and validate_isbn13(isbn13):
        wrote |= record.set_field("isbn_13", isbn13, source, confidence)
        derived = isbn13_to_isbn10(isbn13)
        if derived and not record.isbn_10:
            record.set_field("isbn_10", derived, "derived", confidence * 0.9)
    if isbn10 and validate_isbn10(isbn10):
        wrote |= record.set_field("isbn_10", isbn10, source, confidence)
        derived = isbn10_to_isbn13(isbn10)
        if derived and not record.isbn_13:
            record.set_field("isbn_13", derived, "derived", confidence * 0.9)
    return wrote


def harvest_identifiers(record: BookRecord) -> BookRecord:
    """
    Collect identifiers from every local source, strongest first:
    filename → front matter → full text excerpt.
    """
    # 1. Filename — an explicit ISBN in the name is deliberate and reliable.
    f13, f10 = isbns_from_filename(record.file_name)
    if f13 or f10:
        if _fill_pair(record, f13, f10, "filename", 0.9):
            logger.debug(f"ISBN from filename for {record.file_name}: {f13 or f10}")

    for sid in find_source_ids(re.sub(r"\.\w{2,5}$", "", record.file_name or "")):
        if sid not in record.source_ids:
            record.source_ids.append(sid)

    # 2. Front matter (title/copyright pages) — where publishers print the ISBN.
    if record.front_matter:
        c13, c10 = find_isbns(record.front_matter)
        if c13 or c10:
            _fill_pair(record, c13[0] if c13 else None, c10[0] if c10 else None,
                       "front_matter", 0.85)
        for sid in find_source_ids(record.front_matter):
            if sid not in record.source_ids:
                record.source_ids.append(sid)

    # 3. Anywhere in the extracted text.
    if not (record.isbn_13 and record.isbn_10) and record.text_excerpt:
        t13, t10 = find_isbns(record.text_excerpt[:8000])
        if t13 or t10:
            _fill_pair(record, t13[0] if t13 else None, t10[0] if t10 else None,
                       "front_matter", 0.7)

    return record


def all_local_isbns(record: BookRecord) -> set[str]:
    """Every validated ISBN visible locally — used as identity evidence."""
    found: set[str] = set()
    for text in (record.file_name, record.front_matter, record.text_excerpt or ""):
        i13, i10 = find_isbns(text[:8000] if text else "")
        found.update(i13)
        found.update(i10)
    for value in (record.isbn_13, record.isbn_10):
        if value:
            found.add(value)
    # Normalise: keep both representations so either matches a candidate.
    expanded = set(found)
    for isbn in found:
        if len(isbn) == 13:
            alt = isbn13_to_isbn10(isbn)
        else:
            alt = isbn10_to_isbn13(isbn)
        if alt:
            expanded.add(alt)
    return expanded


# ── Backwards-compatible entry point ────────────────────────────────────────────

def extract_isbn_from_content(record: BookRecord) -> BookRecord:
    """Legacy name for `harvest_identifiers`."""
    return harvest_identifiers(record)
