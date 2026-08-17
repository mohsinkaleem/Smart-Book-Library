"""
EPUB metadata and text extraction using ebooklib + BeautifulSoup.

EPUBs carry the richest metadata of any format here: `dc:identifier`,
`calibre:isbn`, `dc:source` and `dc:subject` are all worth harvesting
for the verification gate.
"""
import io
import logging
import re
from pathlib import Path
from typing import Optional

from .config import COVERS_DIR
from .isbn_extractor import normalize_isbn, validate_isbn10, validate_isbn13
from .models import BookRecord
from .names import clean_authors
from .text_utils import detect_language, detect_script, partition_pages

logger = logging.getLogger(__name__)


def extract_epub_metadata(file_path: Path, record: BookRecord) -> BookRecord:
    """Extract metadata and text from an EPUB. Mutates and returns the record."""
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError:
        logger.error("ebooklib not installed. Run: pip install ebooklib")
        record.processing_errors.append("ebooklib not installed")
        return record

    try:
        book = epub.read_epub(str(file_path), options={"ignore_ncx": True})

        titles = book.get_metadata("DC", "title")
        if titles and titles[0] and titles[0][0]:
            title = re.sub(r"\s+", " ", titles[0][0]).strip()
            record.original_title_meta = title
            record.set_field("title", title, "file_meta", 0.7)

        creators = book.get_metadata("DC", "creator")
        authors = clean_authors([c[0] for c in creators if c and c[0]]) if creators else []
        if authors:
            record.set_field("authors", authors, "file_meta", 0.7)

        publishers = book.get_metadata("DC", "publisher")
        if publishers and publishers[0] and publishers[0][0]:
            record.set_field("publisher", publishers[0][0].strip(), "file_meta", 0.7)

        languages = book.get_metadata("DC", "language")
        if languages and languages[0] and languages[0][0]:
            record.set_field("language", languages[0][0][:2].lower(), "file_meta", 0.75)

        dates = book.get_metadata("DC", "date")
        if dates and dates[0] and dates[0][0]:
            year = _extract_year(dates[0][0])
            if year:
                record.set_field("publication_year", year, "file_meta", 0.7)

        descriptions = book.get_metadata("DC", "description")
        if descriptions and descriptions[0] and descriptions[0][0]:
            desc = _strip_html(descriptions[0][0])
            if desc:
                record.set_field("description", desc[:2000], "file_meta", 0.7)

        subjects = book.get_metadata("DC", "subject")
        if subjects:
            raw = [s[0].strip() for s in subjects if s and s[0] and len(s[0].strip()) > 2]
            if raw:
                record.subjects_raw = list(dict.fromkeys(record.subjects_raw + raw))[:20]

        _harvest_identifiers(book, record)

        # ── Text ─────────────────────────────────────────────────────────────
        pages: list[str] = []
        total_chars = 0
        items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
        for item in items:
            if total_chars >= 20000:
                break
            try:
                content = item.get_content()
                if not content:
                    continue
                text = _extract_text_from_html(content).strip()
                if len(text) > 20:
                    pages.append(text)
                    total_chars += len(text)
            except Exception as e:
                logger.debug(f"Failed to extract text from EPUB chapter: {e}")

        parts = partition_pages(pages)
        record.text_excerpt = parts["text_excerpt"]
        record.front_matter = parts["front_matter"]
        record.content_sample = parts["content_sample"]

        record.has_text = total_chars >= 100
        record.ocr_required = not record.has_text

        sample = record.content_sample or record.text_excerpt
        script = detect_script(sample)
        if script:
            record.set_field("script", script, "file_meta", 0.7)
        if not record.language:
            language = detect_language(sample, script)
            if language:
                record.set_field("language", language, "file_meta", 0.6)

        _extract_epub_cover(book, file_path, record)

        if not record.page_count and total_chars:
            estimated = total_chars * (len(items) / max(len(pages), 1))
            record.page_count = max(1, int(estimated / 1250))

    except Exception as e:
        logger.error(f"Failed to process EPUB {file_path}: {e}")
        record.processing_errors.append(f"EPUB extraction failed: {e}")

    return record


def _harvest_identifiers(book, record: BookRecord):
    """Pull ISBNs and stable ids out of dc:identifier, calibre:isbn, dc:source."""
    candidates: list[str] = []
    for ident in book.get_metadata("DC", "identifier") or []:
        if ident and ident[0]:
            candidates.append(str(ident[0]))
    for source in book.get_metadata("DC", "source") or []:
        if source and source[0]:
            candidates.append(str(source[0]))
    for meta in book.get_metadata("OPF", "meta") or []:
        attrs = meta[1] if len(meta) > 1 else {}
        name = (attrs.get("name") or "").lower()
        if "isbn" in name or "calibre" in name:
            value = attrs.get("content") or (meta[0] or "")
            if value:
                candidates.append(str(value))

    for raw in candidates:
        clean = normalize_isbn(raw)
        if len(clean) == 13 and validate_isbn13(clean):
            record.set_field("isbn_13", clean, "file_meta", 0.85)
        elif len(clean) == 10 and validate_isbn10(clean):
            record.set_field("isbn_10", clean, "file_meta", 0.85)
        elif raw.lower().startswith(("urn:uuid", "uuid:")):
            continue
        elif ":" in raw and len(raw) < 80:
            tag = raw.strip()
            if tag not in record.source_ids:
                record.source_ids.append(tag)


def _extract_epub_cover(book, file_path: Path, record: BookRecord):
    if record.cover_path:
        return
    try:
        from PIL import Image
        import ebooklib
    except ImportError:
        return

    try:
        cover_items = []
        cover_meta = book.get_metadata("OPF", "cover")
        if cover_meta and cover_meta[0]:
            cover_id = cover_meta[0][1].get("content", "")
            if cover_id:
                for item in book.get_items():
                    if item.get_id() == cover_id:
                        cover_items.append(item)
                        break
        if not cover_items:
            for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
                if "cover" in (item.get_name() or "").lower():
                    cover_items.append(item)
                    break
        if not cover_items:
            images = list(book.get_items_of_type(ebooklib.ITEM_IMAGE))
            if images:
                cover_items.append(images[0])

        if not cover_items:
            return
        data = cover_items[0].get_content()
        if not data or len(data) <= 1000:
            return

        cover_path = COVERS_DIR / f"{file_path.stem}_cover.jpg"
        image = Image.open(io.BytesIO(data))
        if image.mode in ("RGBA", "P", "LA"):
            image = image.convert("RGB")
        if image.width > 800 or image.height > 1200:
            image.thumbnail((800, 1200), Image.LANCZOS)
        image.save(str(cover_path), "JPEG", quality=85)
        record.set_field(
            "cover_path", str(cover_path.relative_to(COVERS_DIR.parent.parent)),
            "file_meta", 0.7,
        )
    except Exception as e:
        logger.debug(f"EPUB cover extraction failed for {file_path.name}: {e}")


def _extract_text_from_html(content: bytes) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "head", "meta", "link"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except Exception:
        text = content.decode("utf-8", errors="ignore")
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()


def _strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", clean).strip()


def _extract_year(date_str: str) -> Optional[int]:
    m = re.search(r"(\d{4})", date_str or "")
    if m:
        year = int(m.group(1))
        if 1800 <= year <= 2030:
            return year
    return None
