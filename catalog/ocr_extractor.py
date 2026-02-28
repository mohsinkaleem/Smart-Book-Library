"""
OCR extraction for image-based PDFs using pytesseract + pdf2image.

Converts PDF pages to images and runs Tesseract OCR to extract text.
Also attempts to extract ISBNs from the OCR'd text.

Requirements:
    pip install pytesseract pdf2image Pillow
    brew install tesseract poppler  (macOS)
"""
import logging
import re
from pathlib import Path
from typing import Optional

from .config import (
    MAX_PAGES_TO_EXTRACT,
    MAX_TEXT_EXCERPT_CHARS,
    MIN_TEXT_CHARS_FOR_HAS_TEXT,
    COVERS_DIR,
)
from .models import BookRecord

logger = logging.getLogger(__name__)

# OCR configuration defaults
OCR_DPI = 300
OCR_LANGUAGE = "eng"  # Tesseract language pack(s), e.g. "eng+ara"
OCR_MAX_PAGES = 15    # OCR is slow — cap pages processed


def is_available() -> bool:
    """Check whether tesseract and pdf2image are installed."""
    try:
        import pytesseract
        from pdf2image import convert_from_path  # noqa: F401
        # Quick check that tesseract binary is reachable
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_pdf(file_path: Path, record: BookRecord) -> BookRecord:
    """
    Run OCR on an image-based PDF.

    Updates record.text_excerpt, record.has_text, record.ocr_required,
    and attempts ISBN extraction from the OCR'd text.
    """
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError:
        logger.warning(
            "OCR dependencies missing. Install with:\n"
            "  pip install pytesseract pdf2image\n"
            "  brew install tesseract poppler"
        )
        record.processing_errors.append("OCR dependencies not installed")
        return record

    logger.info(f"   🔍 Running OCR on {file_path.name}...")

    try:
        # Convert PDF pages to images
        pages_to_convert = min(OCR_MAX_PAGES, MAX_PAGES_TO_EXTRACT)
        images = convert_from_path(
            str(file_path),
            dpi=OCR_DPI,
            first_page=1,
            last_page=pages_to_convert,
            fmt="jpeg",
        )

        text_parts = []
        total_chars = 0

        for i, img in enumerate(images):
            if total_chars >= MAX_TEXT_EXCERPT_CHARS:
                break
            try:
                page_text = pytesseract.image_to_string(img, lang=OCR_LANGUAGE)
                page_text = _clean_ocr_text(page_text)
                if page_text and len(page_text.strip()) > 10:
                    text_parts.append(page_text.strip())
                    total_chars += len(page_text)
            except Exception as e:
                logger.debug(f"OCR failed on page {i + 1} of {file_path.name}: {e}")

        full_text = "\n\n".join(text_parts)

        if total_chars >= MIN_TEXT_CHARS_FOR_HAS_TEXT:
            record.text_excerpt = full_text[:MAX_TEXT_EXCERPT_CHARS]
            record.has_text = True
            record.ocr_required = False  # No longer required — done
            logger.info(
                f"   ✅ OCR extracted {total_chars} chars from {len(images)} pages"
            )
        else:
            # Still couldn't extract enough text
            record.text_excerpt = full_text[:MAX_TEXT_EXCERPT_CHARS] if full_text else ""
            logger.warning(
                f"   ⚠️  OCR produced only {total_chars} chars for {file_path.name}"
            )

        # Try to extract ISBN from OCR text (copyright pages)
        _extract_isbn_from_text(full_text, record)

        # Save the first page image as cover if we don't have one
        if not record.cover_path and images:
            _save_ocr_cover(images[0], file_path, record)

    except Exception as e:
        logger.error(f"OCR failed for {file_path.name}: {e}")
        record.processing_errors.append(f"OCR failed: {e}")

    return record


def _extract_isbn_from_text(text: str, record: BookRecord):
    """
    Regex-extract ISBNs from OCR'd or regular text.
    Typically found on copyright pages (first few pages).
    """
    if not text:
        return

    # ISBN-13 pattern: 978 or 979 followed by groups of digits/hyphens
    isbn13_patterns = [
        r"ISBN[-\s]*(?:13)?[-:\s]*(97[89][-\s]?\d[-\s]?\d{2,5}[-\s]?\d{2,6}[-\s]?\d)",
        r"\b(97[89]\d{10})\b",
        r"\b(97[89][-\s]\d[-\s]\d{2,5}[-\s]\d{2,6}[-\s]\d)\b",
    ]
    # ISBN-10 pattern
    isbn10_patterns = [
        r"ISBN[-\s]*(?:10)?[-:\s]*(\d[-\s]?\d{2,5}[-\s]?\d{2,6}[-\s]?[\dXx])",
        r"\b(\d{9}[\dXx])\b",
    ]

    # Search for ISBN-13 first (preferred)
    if not record.isbn_13:
        for pattern in isbn13_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                clean = re.sub(r"[-\s]", "", match)
                if len(clean) == 13 and clean.startswith(("978", "979")):
                    if _validate_isbn13(clean):
                        record.isbn_13 = clean
                        logger.debug(f"Found ISBN-13 in text: {clean}")
                        break
            if record.isbn_13:
                break

    # Search for ISBN-10
    if not record.isbn_10:
        for pattern in isbn10_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                clean = re.sub(r"[-\s]", "", match).upper()
                if len(clean) == 10:
                    if _validate_isbn10(clean):
                        record.isbn_10 = clean
                        logger.debug(f"Found ISBN-10 in text: {clean}")
                        break
            if record.isbn_10:
                break


def _validate_isbn13(isbn: str) -> bool:
    """Validate an ISBN-13 check digit."""
    if len(isbn) != 13 or not isbn.isdigit():
        return False
    total = sum(
        int(d) * (1 if i % 2 == 0 else 3)
        for i, d in enumerate(isbn)
    )
    return total % 10 == 0


def _validate_isbn10(isbn: str) -> bool:
    """Validate an ISBN-10 check digit."""
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


def _clean_ocr_text(text: str) -> str:
    """Clean up OCR output — fix common artefacts."""
    if not text:
        return ""
    # Remove form-feed and other control chars
    text = re.sub(r"[\x0c\x00-\x08\x0e-\x1f]", "", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove very short "noise" lines (single chars, stray punctuation)
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) > 2 or stripped == "":
            cleaned.append(stripped)
    return "\n".join(cleaned)


def _save_ocr_cover(image, file_path: Path, record: BookRecord):
    """Save the first page of an image-based PDF as a cover."""
    try:
        from PIL import Image
        cover_name = f"{file_path.stem}_cover.jpg"
        cover_path = COVERS_DIR / cover_name
        img = image.copy()
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        if img.width > 800 or img.height > 1200:
            img.thumbnail((800, 1200), Image.LANCZOS)
        img.save(str(cover_path), "JPEG", quality=85)
        record.cover_path = str(cover_path.relative_to(COVERS_DIR.parent.parent))
        logger.debug(f"Saved OCR cover for {file_path.name}")
    except Exception as e:
        logger.debug(f"Failed to save OCR cover for {file_path.name}: {e}")
