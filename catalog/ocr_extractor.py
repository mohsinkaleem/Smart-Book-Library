"""
OCR for image-based PDFs using pytesseract + pdf2image.

Configuration comes from `catalog.config` (the module-local `OCR_*` copies that
silently shadowed it are gone — S2). The OCR language is chosen per book from
the detected script, so the Arabic and Urdu material is no longer OCR'd as
English (§M5).

Requirements:
    pip install pytesseract pdf2image
    brew install tesseract poppler          # plus language packs, e.g. tesseract-lang
"""
import logging
import re
from pathlib import Path

from .config import (
    COVERS_DIR,
    MAX_PAGES_TO_EXTRACT,
    MIN_TEXT_CHARS_FOR_HAS_TEXT,
    OCR_DPI,
    OCR_LANGUAGE,
    OCR_LANGUAGE_BY_SCRIPT,
    OCR_MAX_PAGES,
)
from .models import BookRecord
from .text_utils import detect_language, detect_script, partition_pages

logger = logging.getLogger(__name__)


def is_available() -> bool:
    """Check whether tesseract and pdf2image are usable."""
    try:
        import pytesseract
        from pdf2image import convert_from_path  # noqa: F401
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def installed_languages() -> set[str]:
    try:
        import pytesseract
        return set(pytesseract.get_languages(config=""))
    except Exception:
        return set()


def choose_language(record: BookRecord, available: set[str]) -> str:
    """Pick tesseract language packs for this book, falling back to English."""
    langs: list[str] = []
    script = record.script or detect_script(record.text_excerpt or "")
    wanted = OCR_LANGUAGE_BY_SCRIPT.get(script)
    if wanted and (not available or wanted in available):
        langs.append(wanted)
    for lang in OCR_LANGUAGE.split("+"):
        if lang and lang not in langs and (not available or lang in available):
            langs.append(lang)
    return "+".join(langs) or "eng"


def ocr_pdf(file_path: Path, record: BookRecord) -> BookRecord:
    """OCR an image-based PDF and re-partition its text."""
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

    language = choose_language(record, installed_languages())
    logger.info(f"   🔍 Running OCR on {file_path.name} (lang={language})...")

    try:
        pages_to_convert = min(OCR_MAX_PAGES, MAX_PAGES_TO_EXTRACT)
        images = convert_from_path(
            str(file_path), dpi=OCR_DPI, first_page=1, last_page=pages_to_convert, fmt="jpeg"
        )

        pages: list[str] = []
        total_chars = 0
        for i, img in enumerate(images):
            try:
                page_text = _clean_ocr_text(pytesseract.image_to_string(img, lang=language))
                if page_text and len(page_text.strip()) > 10:
                    pages.append(page_text.strip())
                    total_chars += len(page_text)
            except Exception as e:
                logger.debug(f"OCR failed on page {i + 1} of {file_path.name}: {e}")

        if pages:
            parts = partition_pages(pages)
            record.text_excerpt = parts["text_excerpt"]
            record.front_matter = parts["front_matter"]
            record.content_sample = parts["content_sample"]

        if total_chars >= MIN_TEXT_CHARS_FOR_HAS_TEXT:
            record.has_text = True
            record.ocr_required = False
            script = detect_script(record.text_excerpt)
            if script:
                record.set_field("script", script, "file_meta", 0.6)
            lang = detect_language(record.text_excerpt, script)
            if lang:
                record.set_field("language", lang, "file_meta", 0.5)
            logger.info(f"   ✅ OCR extracted {total_chars} chars from {len(images)} pages")
        else:
            logger.warning(f"   ⚠️  OCR produced only {total_chars} chars for {file_path.name}")

        if not record.cover_path and images:
            _save_ocr_cover(images[0], file_path, record)

    except Exception as e:
        logger.error(f"OCR failed for {file_path.name}: {e}")
        record.processing_errors.append(f"OCR failed: {e}")

    return record


def _clean_ocr_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[\x0c\x00-\x08\x0e-\x1f]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if len(stripped) > 2 or stripped == "":
            lines.append(stripped)
    return "\n".join(lines)


def _save_ocr_cover(image, file_path: Path, record: BookRecord):
    try:
        from PIL import Image
        cover_path = COVERS_DIR / f"{record.id or file_path.stem}_cover.jpg"
        img = image.copy()
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        if img.width > 800 or img.height > 1200:
            img.thumbnail((800, 1200), Image.LANCZOS)
        img.save(str(cover_path), "JPEG", quality=85)
        record.set_field(
            "cover_path", str(cover_path.relative_to(COVERS_DIR.parent.parent)),
            "file_meta", 0.5,
        )
    except Exception as e:
        logger.debug(f"Failed to save OCR cover for {file_path.name}: {e}")
