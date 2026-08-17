"""
PDF metadata and text extraction using pypdf.

Two rules that were missing before:

* `/Producer` and `/Creator` are tool fields. They are read explicitly and are
  only ever considered as an author when they pass `is_person_name`.
* Page texts are kept separate so front matter and content sample can be
  partitioned rather than blended into one excerpt.
"""
import io
import logging
import re
from pathlib import Path

from .config import COVERS_DIR, MAX_PAGES_TO_EXTRACT, MIN_TEXT_CHARS_FOR_HAS_TEXT
from .models import BookRecord
from .names import clean_authors, is_person_name, looks_like_tool
from .text_utils import detect_language, detect_script, partition_pages

logger = logging.getLogger(__name__)

_JUNK_TITLE = re.compile(
    r"^(microsoft\s+word\s*-\s*)|(\.(?:doc|docx|pdf|indd|qxd|tex|rtf)\s*$)|"
    r"^(untitled|unknown|document\d*|print|output|final|draft|scan\d*|book\d*|"
    r"new\s+document|copy\s+of\b)",
    re.IGNORECASE,
)


def clean_meta_title(raw: str) -> str:
    """Return a usable embedded title, or "" when the value is an artefact."""
    if not raw:
        return ""
    title = re.sub(r"\s+", " ", raw).strip()
    was_document_name = bool(re.match(r"^microsoft\s+word\s*-\s*", title, flags=re.I))
    title = re.sub(r"^microsoft\s+word\s*-\s*", "", title, flags=re.I)
    was_document_name = was_document_name or bool(
        re.search(r"\.(?:doc|docx|indd|qxd|tex|rtf)$", title, flags=re.I)
    )
    title = re.sub(r"\.(?:doc|docx|pdf|indd|qxd|tex|rtf)$", "", title, flags=re.I)
    title = title.replace("_", " ").strip()
    # "Microsoft Word - AbuUmar_final.doc" leaves "AbuUmar final", which is a
    # working-file name, not a title. Fall back to the filename instead.
    if was_document_name and re.search(
        r"(?:^|\s)(final|draft|copy|new|edit(?:ed)?|rev\d*|v\d+|test)$", title, flags=re.I
    ):
        return ""
    if len(title) < 3 or _JUNK_TITLE.match(title) or looks_like_tool(title):
        return ""
    if not re.search(r"[^\W\d_]", title, re.UNICODE):
        return ""
    return title


def extract_pdf_metadata(file_path: Path, record: BookRecord) -> BookRecord:
    """Extract metadata and text from a PDF. Mutates and returns the record."""
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.error("pypdf not installed. Run: pip install pypdf")
        record.processing_errors.append("pypdf not installed")
        return record

    try:
        reader = PdfReader(str(file_path))
        record.page_count = len(reader.pages)

        meta = reader.metadata
        if meta:
            _apply_pdf_info(meta, record)

        pages: list[str] = []
        total_chars = 0
        for i, page in enumerate(reader.pages):
            if i >= MAX_PAGES_TO_EXTRACT:
                break
            try:
                page_text = _clean_extracted_text(page.extract_text() or "")
                pages.append(page_text)
                total_chars += len(page_text)
            except Exception as e:
                logger.debug(f"Failed to extract text from page {i} of {file_path}: {e}")

        parts = partition_pages(pages)
        record.text_excerpt = parts["text_excerpt"]
        record.front_matter = parts["front_matter"]
        record.content_sample = parts["content_sample"]

        if total_chars < MIN_TEXT_CHARS_FOR_HAS_TEXT:
            record.has_text = False
            record.ocr_required = True
            logger.info(f"Image-based PDF detected: {file_path.name} ({total_chars} chars)")
        else:
            record.has_text = True
            record.ocr_required = False
            _detect_language(record)

        _extract_pdf_cover(reader, file_path, record)

    except Exception as e:
        logger.error(f"Failed to process PDF {file_path}: {e}")
        record.processing_errors.append(f"PDF extraction failed: {e}")

    return record


def _apply_pdf_info(meta, record: BookRecord):
    """Read the /Info dictionary with tool strings held at arm's length."""
    title = clean_meta_title(getattr(meta, "title", "") or "")
    if title:
        record.original_title_meta = title
        record.set_field("title", title, "file_meta", 0.6)

    author_raw = (getattr(meta, "author", "") or "").strip()
    authors = clean_authors([author_raw]) if author_raw else []

    # /Creator is usually the authoring *application*; accept it only when it
    # unambiguously looks like a person and we have nothing better.
    if not authors:
        creator = (getattr(meta, "creator", "") or "").strip()
        if creator and is_person_name(creator):
            authors = clean_authors([creator])

    # /Producer is always a tool ("Adobe InDesign CS6", "pdftk 2.02") and is
    # deliberately never consulted for authorship.

    if authors:
        record.set_field("authors", authors, "file_meta", 0.6)

    subject = (getattr(meta, "subject", "") or "").strip()
    if subject and len(subject) < 300:
        raw = [k.strip() for k in re.split(r"[;,]", subject) if len(k.strip()) > 2]
        if raw:
            record.subjects_raw = list(dict.fromkeys(record.subjects_raw + raw))[:15]


def _detect_language(record: BookRecord):
    sample = record.content_sample or record.text_excerpt
    script = detect_script(sample)
    if script:
        record.set_field("script", script, "file_meta", 0.7)
    language = detect_language(sample, script)
    if language:
        record.set_field("language", language, "file_meta", 0.6)


def _extract_pdf_cover(reader, file_path: Path, record: BookRecord):
    """Save the largest image on page 1 as the cover."""
    if record.cover_path:
        return
    try:
        from PIL import Image
    except ImportError:
        logger.debug("Pillow not installed, skipping cover extraction")
        return

    try:
        first_page = reader.pages[0]
        images = first_page.images if hasattr(first_page, "images") else []
        largest_img, largest_size = None, 0
        for img in images:
            try:
                data = img.data
                if len(data) > largest_size:
                    largest_size, largest_img = len(data), data
            except Exception:
                continue

        if largest_img and largest_size > 1000:
            cover_path = COVERS_DIR / f"{file_path.stem}_cover.jpg"
            image = Image.open(io.BytesIO(largest_img))
            if image.mode in ("RGBA", "P", "LA"):
                image = image.convert("RGB")
            if image.width > 800 or image.height > 1200:
                image.thumbnail((800, 1200), Image.LANCZOS)
            image.save(str(cover_path), "JPEG", quality=85)
            record.set_field(
                "cover_path", str(cover_path.relative_to(COVERS_DIR.parent.parent)),
                "file_meta", 0.6,
            )
    except Exception as e:
        logger.debug(f"Cover extraction failed for {file_path.name}: {e}")


def _clean_extracted_text(text: str) -> str:
    """Tidy one page of extracted text."""
    if not text:
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and (len(stripped) > 3 or stripped in {".", ",", ":", ";"}):
            lines.append(stripped)
    return "\n".join(lines)
