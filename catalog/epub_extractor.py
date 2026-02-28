"""
EPUB metadata and text extraction using ebooklib and BeautifulSoup.
"""
import io
import logging
from pathlib import Path
from typing import Optional

from .config import (
    MAX_TEXT_EXCERPT_CHARS,
    MIN_TEXT_CHARS_FOR_HAS_TEXT,
    COVERS_DIR,
)
from .models import BookRecord

logger = logging.getLogger(__name__)


def extract_epub_metadata(file_path: Path, record: BookRecord) -> BookRecord:
    """
    Extract metadata from an EPUB file.
    Updates the BookRecord in-place and returns it.
    """
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError:
        logger.error("ebooklib not installed. Run: pip install ebooklib")
        record.processing_errors.append("ebooklib not installed")
        return record

    try:
        book = epub.read_epub(str(file_path), options={"ignore_ncx": True})

        # ── Title ────────────────────────────────────────────────────────
        title = book.get_metadata("DC", "title")
        if title:
            record.original_title_meta = title[0][0] if title[0] else ""

        # ── Authors ──────────────────────────────────────────────────────
        creators = book.get_metadata("DC", "creator")
        if creators and not record.authors:
            record.authors = [c[0] for c in creators if c[0]]

        # ── Publisher ────────────────────────────────────────────────────
        publishers = book.get_metadata("DC", "publisher")
        if publishers and not record.publisher:
            record.publisher = publishers[0][0] if publishers[0] else ""

        # ── Language ─────────────────────────────────────────────────────
        languages = book.get_metadata("DC", "language")
        if languages and not record.language:
            lang = languages[0][0] if languages[0] else ""
            record.language = lang[:2] if lang else ""  # Normalize to 2-char

        # ── Date ─────────────────────────────────────────────────────────
        dates = book.get_metadata("DC", "date")
        if dates and not record.publication_year:
            date_str = dates[0][0] if dates[0] else ""
            year = _extract_year(date_str)
            if year:
                record.publication_year = year

        # ── Description ──────────────────────────────────────────────────
        descriptions = book.get_metadata("DC", "description")
        if descriptions:
            desc = descriptions[0][0] if descriptions[0] else ""
            if desc:
                # Clean HTML from description
                record.description = _strip_html(desc)

        # ── Subject/Keywords ─────────────────────────────────────────────
        subjects = book.get_metadata("DC", "subject")
        if subjects:
            record.keywords = [s[0] for s in subjects if s[0]][:10]

        # ── ISBN ─────────────────────────────────────────────────────────
        identifiers = book.get_metadata("DC", "identifier")
        for ident in identifiers:
            val = ident[0] if ident else ""
            attrs = ident[1] if len(ident) > 1 else {}
            if val:
                _extract_isbn(val, attrs, record)

        # ── Text Extraction ──────────────────────────────────────────────
        text_parts = []
        total_chars = 0
        items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))

        for item in items:
            if total_chars >= MAX_TEXT_EXCERPT_CHARS:
                break
            try:
                content = item.get_content()
                if content:
                    text = _extract_text_from_html(content)
                    if text and len(text.strip()) > 20:
                        text_parts.append(text.strip())
                        total_chars += len(text)
            except Exception as e:
                logger.debug(f"Failed to extract text from EPUB chapter: {e}")

        full_text = "\n\n".join(text_parts)
        record.text_excerpt = full_text[:MAX_TEXT_EXCERPT_CHARS]

        # Determine text availability
        if total_chars < MIN_TEXT_CHARS_FOR_HAS_TEXT:
            record.has_text = False
            record.ocr_required = True
        else:
            record.has_text = True
            record.ocr_required = False

        # ── Cover Extraction ─────────────────────────────────────────────
        _extract_epub_cover(book, file_path, record)

        # ── Page Count (estimate from chapters) ─────────────────────────
        if not record.page_count:
            # Rough estimate: ~250 words per page, ~5 chars per word
            estimated_total_chars = total_chars * (len(items) / max(len(text_parts), 1))
            record.page_count = max(1, int(estimated_total_chars / 1250))

    except Exception as e:
        logger.error(f"Failed to process EPUB {file_path}: {e}")
        record.processing_errors.append(f"EPUB extraction failed: {e}")

    return record


def _extract_epub_cover(book, file_path: Path, record: BookRecord):
    """Extract cover image from EPUB."""
    try:
        from PIL import Image
        import ebooklib
    except ImportError:
        return

    try:
        # Method 1: Look for cover in metadata
        cover_items = []

        # Check meta cover tag
        cover_meta = book.get_metadata("OPF", "cover")
        if cover_meta:
            cover_id = cover_meta[0][1].get("content", "") if cover_meta[0] else ""
            if cover_id:
                for item in book.get_items():
                    if item.get_id() == cover_id:
                        cover_items.append(item)
                        break

        # Method 2: Look for items with 'cover' in name
        if not cover_items:
            for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
                name = (item.get_name() or "").lower()
                if "cover" in name:
                    cover_items.append(item)
                    break

        # Method 3: First image
        if not cover_items:
            images = list(book.get_items_of_type(ebooklib.ITEM_IMAGE))
            if images:
                cover_items.append(images[0])

        if cover_items:
            cover_data = cover_items[0].get_content()
            if cover_data and len(cover_data) > 1000:
                cover_name = f"{file_path.stem}_cover.jpg"
                cover_path = COVERS_DIR / cover_name
                try:
                    image = Image.open(io.BytesIO(cover_data))
                    if image.mode in ("RGBA", "P", "LA"):
                        image = image.convert("RGB")
                    if image.width > 800 or image.height > 1200:
                        image.thumbnail((800, 1200), Image.LANCZOS)
                    image.save(str(cover_path), "JPEG", quality=85)
                    record.cover_path = str(cover_path.relative_to(COVERS_DIR.parent.parent))
                except Exception as e:
                    logger.debug(f"Failed to save EPUB cover for {file_path.name}: {e}")

    except Exception as e:
        logger.debug(f"EPUB cover extraction failed for {file_path.name}: {e}")


def _extract_text_from_html(content: bytes) -> str:
    """Extract plain text from HTML content."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, "html.parser")
        # Remove script and style elements
        for tag in soup(["script", "style", "head", "meta", "link"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text
    except Exception:
        # Fallback: crude tag stripping
        import re
        text = content.decode("utf-8", errors="ignore")
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    import re
    clean = re.sub(r"<[^>]+>", "", text)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def _extract_year(date_str: str) -> Optional[int]:
    """Extract a year from a date string."""
    import re
    m = re.search(r"(\d{4})", date_str)
    if m:
        year = int(m.group(1))
        if 1800 <= year <= 2030:
            return year
    return None


def _extract_isbn(value: str, attrs: dict, record: BookRecord):
    """Extract ISBN from identifier value and attributes."""
    import re

    # Check attributes for scheme
    scheme = ""
    for key, val in attrs.items():
        if "scheme" in key.lower() or "type" in key.lower():
            scheme = val.lower()
            break

    # Clean the value
    clean_val = re.sub(r"[^0-9Xx]", "", value)

    if "isbn" in scheme or "isbn" in value.lower():
        if len(clean_val) == 13:
            record.isbn_13 = clean_val
        elif len(clean_val) == 10:
            record.isbn_10 = clean_val
    elif len(clean_val) == 13 and clean_val.startswith("978"):
        record.isbn_13 = clean_val
    elif len(clean_val) == 10:
        record.isbn_10 = clean_val
