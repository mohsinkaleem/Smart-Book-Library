"""
PDF metadata and text extraction using pypdf.
Handles text-based and image-based PDFs, extracts covers.
"""
import io
import logging
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


def extract_pdf_metadata(file_path: Path, record: BookRecord) -> BookRecord:
    """
    Extract metadata from a PDF file.
    Updates the BookRecord in-place and returns it.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.error("pypdf not installed. Run: pip install pypdf")
        record.processing_errors.append("pypdf not installed")
        return record

    try:
        reader = PdfReader(str(file_path))

        # Page count
        record.page_count = len(reader.pages)

        # Extract metadata from PDF info dict
        meta = reader.metadata
        if meta:
            if meta.title and meta.title.strip():
                record.original_title_meta = meta.title.strip()

            if meta.author and meta.author.strip():
                author_str = meta.author.strip()
                # Split on common delimiters
                authors = _split_authors(author_str)
                if authors and not record.authors:
                    record.authors = authors

            if meta.creator and meta.creator.strip():
                creator = meta.creator.strip()
                # Sometimes creator has the tool name, sometimes the author
                if creator.lower() not in [
                    "latex", "tex", "calibre", "adobe", "microsoft",
                    "libreoffice", "openoffice", "word", "mozilla",
                ] and not any(
                    tool in creator.lower()
                    for tool in ["acrobat", "distiller", "ghostscript",
                                  "pdflatex", "xelatex", "wkhtmltopdf",
                                  "prince", "itext", "fpdf", "reportlab",
                                  "quartz", "preview", "scanner"]
                ):
                    if not record.authors:
                        record.authors = _split_authors(creator)

            if hasattr(meta, "subject") and meta.subject:
                subject = meta.subject.strip()
                if subject:
                    record.keywords = [
                        k.strip() for k in subject.split(",") if k.strip()
                    ][:10]

        # Extract text from first pages
        text_parts = []
        total_chars = 0
        for i, page in enumerate(reader.pages):
            if i >= MAX_PAGES_TO_EXTRACT:
                break
            try:
                page_text = page.extract_text() or ""
                page_text = _clean_extracted_text(page_text)
                if page_text:
                    text_parts.append(page_text)
                    total_chars += len(page_text)
                    if total_chars >= MAX_TEXT_EXCERPT_CHARS:
                        break
            except Exception as e:
                logger.debug(f"Failed to extract text from page {i} of {file_path}: {e}")

        full_text = "\n\n".join(text_parts)
        record.text_excerpt = full_text[:MAX_TEXT_EXCERPT_CHARS]

        # Determine if this is text-based or image-based
        if total_chars < MIN_TEXT_CHARS_FOR_HAS_TEXT:
            record.has_text = False
            record.ocr_required = True
            logger.info(f"Image-based PDF detected: {file_path.name} ({total_chars} chars)")
        else:
            record.has_text = True
            record.ocr_required = False

        # Try to extract cover image (first page image or embedded image)
        _extract_pdf_cover(reader, file_path, record)

    except Exception as e:
        logger.error(f"Failed to process PDF {file_path}: {e}")
        record.processing_errors.append(f"PDF extraction failed: {e}")

    return record


def _extract_pdf_cover(reader, file_path: Path, record: BookRecord):
    """Try to extract the cover image from a PDF."""
    try:
        from PIL import Image
    except ImportError:
        logger.debug("Pillow not installed, skipping cover extraction")
        return

    try:
        first_page = reader.pages[0]
        images = first_page.images if hasattr(first_page, "images") else []

        if images:
            # Get the largest image from the first page (likely the cover)
            largest_img = None
            largest_size = 0

            for img in images:
                try:
                    img_data = img.data
                    if len(img_data) > largest_size:
                        largest_size = len(img_data)
                        largest_img = img_data
                except Exception:
                    continue

            if largest_img and largest_size > 1000:  # Skip tiny images
                cover_name = f"{file_path.stem}_cover.jpg"
                cover_path = COVERS_DIR / cover_name
                try:
                    image = Image.open(io.BytesIO(largest_img))
                    # Convert to RGB if necessary
                    if image.mode in ("RGBA", "P", "LA"):
                        image = image.convert("RGB")
                    # Resize if too large
                    if image.width > 800 or image.height > 1200:
                        image.thumbnail((800, 1200), Image.LANCZOS)
                    image.save(str(cover_path), "JPEG", quality=85)
                    record.cover_path = str(cover_path.relative_to(COVERS_DIR.parent.parent))
                    logger.debug(f"Extracted cover for {file_path.name}")
                except Exception as e:
                    logger.debug(f"Failed to save cover image for {file_path.name}: {e}")

    except Exception as e:
        logger.debug(f"Cover extraction failed for {file_path.name}: {e}")


def _split_authors(author_str: str) -> list[str]:
    """Split an author string into a list of individual authors."""
    # Common delimiters
    for delim in [";", " and ", " & ", ",", "/"]:
        if delim in author_str:
            authors = [a.strip() for a in author_str.split(delim) if a.strip()]
            # Filter out non-name entries
            return [a for a in authors if len(a) > 2 and not a.isdigit()]

    return [author_str] if author_str and len(author_str) > 2 else []


def _clean_extracted_text(text: str) -> str:
    """Clean up extracted text from PDF pages."""
    import re

    if not text:
        return ""

    # Remove excessive whitespace
    text = re.sub(r"[ \t]+", " ", text)
    # Remove page numbers standing alone
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)
    # Remove header/footer-like lines (very short lines)
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and (len(stripped) > 3 or stripped in [".", ",", ":", ";"]):
            cleaned_lines.append(stripped)

    return "\n".join(cleaned_lines)
