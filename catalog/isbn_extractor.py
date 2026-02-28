"""
ISBN extraction from book text content.

Scans text excerpts (copyright pages, front matter) for ISBN patterns.
Works on both regular text-extracted and OCR'd content.
Also extracts ISBNs from EPUB metadata identifiers that may have been missed.
"""
import logging
import re
from typing import Optional

from .models import BookRecord

logger = logging.getLogger(__name__)


def extract_isbn_from_content(record: BookRecord) -> BookRecord:
    """
    Attempt to extract ISBN from a book's text excerpt.
    Prioritises the first ~3000 chars (copyright page is usually early).
    Updates record.isbn_13 and record.isbn_10 in-place.
    """
    if record.isbn_13 and record.isbn_10:
        return record  # Already have both

    text = record.text_excerpt or ""
    if not text:
        return record

    # Focus on the first portion — copyright page is typically in first few pages
    search_text = text[:5000]

    # Also try the title/description metadata which sometimes embed ISBNs
    meta_text = " ".join([
        record.original_title_meta or "",
        record.description or "",
        record.file_name or "",
    ])
    search_text = search_text + "\n" + meta_text

    # ── ISBN-13 ──────────────────────────────────────────────────────────
    if not record.isbn_13:
        isbn13 = _find_isbn13(search_text)
        if isbn13:
            record.isbn_13 = isbn13
            logger.info(f"   📖 Extracted ISBN-13 from text: {isbn13} ({record.file_name})")

    # ── ISBN-10 ──────────────────────────────────────────────────────────
    if not record.isbn_10:
        isbn10 = _find_isbn10(search_text)
        if isbn10:
            record.isbn_10 = isbn10
            logger.info(f"   📖 Extracted ISBN-10 from text: {isbn10} ({record.file_name})")

    # ── Convert between formats if we only have one ─────────────────────
    if record.isbn_13 and not record.isbn_10:
        record.isbn_10 = isbn13_to_isbn10(record.isbn_13)
    elif record.isbn_10 and not record.isbn_13:
        record.isbn_13 = isbn10_to_isbn13(record.isbn_10)

    return record


def _find_isbn13(text: str) -> Optional[str]:
    """Find a valid ISBN-13 in text."""
    patterns = [
        # Explicit ISBN label
        r"ISBN[-\s]*(?:13)?[-:\s]*(97[89][-–\s]?\d[-–\s]?\d{2,5}[-–\s]?\d{2,6}[-–\s]?\d)",
        # Bare 13-digit starting with 978/979
        r"\b(97[89]\d{10})\b",
        # Hyphenated 13-digit
        r"\b(97[89][-–]\d[-–]\d{2,5}[-–]\d{2,6}[-–]\d)\b",
        # Spaced
        r"\b(97[89]\s\d\s\d{2,5}\s\d{2,6}\s\d)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            candidate = re.sub(r"[-–\s]", "", match.group(1))
            if len(candidate) == 13 and _validate_isbn13(candidate):
                return candidate
    return None


def _find_isbn10(text: str) -> Optional[str]:
    """Find a valid ISBN-10 in text."""
    patterns = [
        r"ISBN[-\s]*(?:10)?[-:\s]*(\d[-–\s]?\d{2,5}[-–\s]?\d{2,6}[-–\s]?[\dXx])",
        r"\b(\d{9}[\dXx])\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            candidate = re.sub(r"[-–\s]", "", match.group(1)).upper()
            if len(candidate) == 10 and _validate_isbn10(candidate):
                return candidate
    return None


def _validate_isbn13(isbn: str) -> bool:
    """Validate ISBN-13 check digit."""
    if len(isbn) != 13 or not isbn.isdigit():
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(isbn))
    return total % 10 == 0


def _validate_isbn10(isbn: str) -> bool:
    """Validate ISBN-10 check digit."""
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


def isbn13_to_isbn10(isbn13: str) -> str:
    """Convert ISBN-13 to ISBN-10 (only works for 978-prefix)."""
    if not isbn13 or len(isbn13) != 13 or not isbn13.startswith("978"):
        return ""
    body = isbn13[3:12]  # 9 digits after 978, before check digit
    total = sum(int(d) * (10 - i) for i, d in enumerate(body))
    check = (11 - (total % 11)) % 11
    check_char = "X" if check == 10 else str(check)
    return body + check_char


def isbn10_to_isbn13(isbn10: str) -> str:
    """Convert ISBN-10 to ISBN-13."""
    if not isbn10 or len(isbn10) != 10:
        return ""
    body = "978" + isbn10[:9]
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(body))
    check = (10 - (total % 10)) % 10
    return body + str(check)
