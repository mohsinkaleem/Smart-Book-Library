"""
EPUB metadata and text extraction using ebooklib + BeautifulSoup.

EPUBs carry the richest metadata of any format here: `dc:identifier`,
`calibre:isbn`, `dc:source` and `dc:subject` are all worth harvesting
for the verification gate.
"""
import logging
import re
from pathlib import Path
from typing import Optional

from .covers import save_cover
from .isbn_extractor import normalize_isbn, validate_isbn10, validate_isbn13
from .languages import UNKNOWN, normalise_language
from .models import BookRecord
from .names import clean_authors
from .text_utils import detect_language, detect_script, partition_pages

logger = logging.getLogger(__name__)

# `scheme:value` identifiers worth keeping (google:…, amazon:…, doi:…).
_SOURCE_ID = re.compile(r"^[a-z][\w.+-]*:\S+$", re.IGNORECASE)
_UUID = re.compile(r"(?:urn:)?(?:uuid:)?[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$", re.IGNORECASE)


def spine_documents(book) -> list:
    """Document items in reading (spine) order; manifest order only when the spine is empty."""
    import ebooklib
    items = []
    for entry in book.spine or []:
        item_id = entry[0] if isinstance(entry, (tuple, list)) else entry
        item = book.get_item_with_id(item_id)
        if item is not None and item.get_type() == ebooklib.ITEM_DOCUMENT:
            items.append(item)
    return items or list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))


def extract_epub_metadata(file_path: Path, record: BookRecord) -> BookRecord:
    """Extract metadata and text from an EPUB. Mutates and returns the record."""
    try:
        from ebooklib import epub
    except ImportError:
        logger.error("ebooklib not installed. Run: pip install ebooklib")
        record.processing_errors.append("ebooklib not installed")
        return record

    try:
        book = epub.read_epub(str(file_path), options={"ignore_ncx": True})

        titles = book.get_metadata("DC", "title")
        if titles and titles[0] and titles[0][0]:
            # Same artefacts as PDF /Title: "Microsoft Word - Catcher on Rye.docx".
            from .pdf_extractor import clean_meta_title
            title = clean_meta_title(titles[0][0])
            if title:
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
            language = normalise_language(languages[0][0])
            if language != UNKNOWN:
                record.set_field("language", language, "file_meta", 0.75)

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
        # Spine order: the front matter must be the front of the book, and the
        # manifest lists items in whatever order the authoring tool chose.
        pages: list[str] = []
        total_chars = 0
        items = spine_documents(book)
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
    """Pull ISBNs and stable ids out of dc:identifier, dc:source and ISBN-named OPF meta."""
    def _set_isbn(raw: str) -> bool:
        clean = normalize_isbn(raw)
        if len(clean) == 13 and validate_isbn13(clean):
            record.set_field("isbn_13", clean, "file_meta", 0.85)
            return True
        if len(clean) == 10 and validate_isbn10(clean):
            record.set_field("isbn_10", clean, "file_meta", 0.85)
            return True
        return False

    candidates: list[str] = []
    for ident in book.get_metadata("DC", "identifier") or []:
        if ident and ident[0]:
            candidates.append(str(ident[0]).strip())
    for source in book.get_metadata("DC", "source") or []:
        if source and source[0]:
            candidates.append(str(source[0]).strip())

    for raw in candidates:
        if _UUID.match(raw) or _set_isbn(raw):
            continue
        if len(raw) < 80 and _SOURCE_ID.match(raw) and raw not in record.source_ids:
            record.source_ids.append(raw)

    # OPF <meta> is only mined for ISBNs: calibre's timestamps, series and
    # title_sort entries used to land in `source_ids`.
    for meta in book.get_metadata("OPF", "meta") or []:
        attrs = meta[1] if len(meta) > 1 else {}
        if "isbn" in (attrs.get("name") or "").lower():
            value = attrs.get("content") or (meta[0] or "")
            if value:
                _set_isbn(str(value))


def _extract_epub_cover(book, file_path: Path, record: BookRecord):
    """
    Save the EPUB's cover image, trying the four places publishers put it.

    EPUB3 `ITEM_COVER` first, then the EPUB2 `<meta name="cover">` pointer,
    then an image whose name says "cover", and only then the first image in
    the book.
    """
    if record.cover_path:
        return
    try:
        import ebooklib
    except ImportError:
        return

    try:
        items = list(book.get_items_of_type(ebooklib.ITEM_COVER))[:1]

        if not items:
            meta = book.get_metadata("OPF", "cover")
            cover_id = meta[0][1].get("content", "") if meta and meta[0] else ""
            if cover_id:
                items = [i for i in book.get_items() if i.get_id() == cover_id][:1]

        if not items:
            items = [
                i for i in book.get_items_of_type(ebooklib.ITEM_IMAGE)
                if "cover" in (i.get_name() or "").lower()
            ][:1]

        if not items:
            items = list(book.get_items_of_type(ebooklib.ITEM_IMAGE))[:1]

        if items:
            save_cover(record, items[0].get_content() or b"", "file_meta", 0.7)
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
