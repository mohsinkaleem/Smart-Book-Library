"""
PDF metadata and text extraction using pypdf.

Two rules that were missing before:

* `/Producer` and `/Creator` are tool fields. They are read explicitly and are
  only ever considered as an author when they pass `is_person_name`.
* Page texts are kept separate so front matter and content sample can be
  partitioned rather than blended into one excerpt.

`render_page_1_cover` is the odd one out: it reads nothing, it writes a cover,
and it goes through PyMuPDF rather than pypdf because pypdf cannot rasterise a
page. It lives here anyway — rendering a PDF page is this module's business,
and the pipeline calls it as a closing stage rather than from
`extract_pdf_metadata`, so that a real jacket always gets first refusal.
"""
import logging
import re
from pathlib import Path

from .config import COVER_RENDER_DPI, MAX_PAGES_TO_EXTRACT, MIN_TEXT_CHARS_FOR_HAS_TEXT
from .covers import (
    PDF_PAGE_CONFIDENCE,
    PDF_PAGE_SOURCE,
    is_usable_cover,
    save_cover,
)
from .models import BookRecord
from .names import clean_authors, is_person_name, is_tool_title
from .text_utils import clean_page, detect_language, detect_script, partition_pages

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
    if len(title) < 3 or _JUNK_TITLE.match(title) or is_tool_title(title):
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
                page_text = clean_page(page.extract_text() or "")
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
        first_page = reader.pages[0]
        images = first_page.images if hasattr(first_page, "images") else []
        largest, largest_size = None, 0
        for img in images:
            try:
                data = img.data
                if len(data) > largest_size:
                    largest_size, largest = len(data), data
            except Exception:
                continue
        if largest:
            save_cover(record, largest, "file_meta", 0.6)
    except Exception as e:
        logger.debug(f"Cover extraction failed for {file_path.name}: {e}")


def can_render_pages() -> bool:
    """Whether page rasterisation is available (PyMuPDF is an optional extra)."""
    try:
        import pymupdf  # noqa: F401
        return True
    except ImportError:
        return False


def render_page_1_cover(file_path: Path, record: BookRecord) -> str:
    """
    Use page 1 of a PDF as its cover. Returns "" on success, else the reason.

    The last resort in the cover chain, and deliberately the weakest link in
    it: 92 of the 93 cover-less books in this catalog are PDFs whose page 1
    renders perfectly well, and a title page beats the gradient placeholder for
    recognising a book in a grid. A *blank* title page does not, which is why
    the render is put through `is_usable_cover` before it is saved.
    """
    if record.cover_path:
        return "already has a cover"

    try:
        import pymupdf
    except ImportError:   # pragma: no cover - supplied by the `passages` extra
        return "pymupdf not installed"

    try:
        with pymupdf.open(str(file_path)) as doc:
            if doc.page_count < 1:
                return "no pages"
            # `alpha=False` keeps the bitmap at three channels: a rendered page
            # has nothing to be transparent against.
            pixmap = doc[0].get_pixmap(dpi=COVER_RENDER_DPI, alpha=False)
            data = pixmap.tobytes("png")
    except Exception as e:
        return f"page 1 could not be rendered: {e}"

    reason = is_usable_cover(data)
    if reason:
        return reason
    if not save_cover(record, data, PDF_PAGE_SOURCE, PDF_PAGE_CONFIDENCE):
        return "cover could not be saved"
    return ""
