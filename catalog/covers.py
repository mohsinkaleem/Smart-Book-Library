"""
The one place an image becomes this catalog's cover file.

Five call sites used to carry their own copy of "open it, convert to RGB,
thumbnail to 800x1200, save as JPEG at quality 85, write `cover_path`":
`pdf_extractor`, `epub_extractor`, `ocr_extractor`, `api_enricher` and
`cover_scraper`. They had already drifted — `cover_scraper` assigned
`record.cover_path` directly instead of going through `set_field`, so a
scraped jacket could overwrite a cover a human had pinned, and its
content-type guard used `and` where every other copy used `or`, which let a
1 KB HTML error page through as an image.

Every cover is a JPEG named `{record.id}_cover.jpg`. Keying on the record id
rather than the file stem matters: `pdfs/x.pdf` and `epubs/x.epub` share a stem
and used to overwrite each other's cover.
"""
import io
import logging
from pathlib import Path

from .config import COVERS_DIR
from .models import BookRecord

logger = logging.getLogger(__name__)

# Covers are shown in a grid; anything larger is bytes nobody sees.
MAX_COVER_SIZE = (800, 1200)
JPEG_QUALITY = 85
# Below this a "cover" is a tracking pixel, a spacer GIF or an error page.
MIN_COVER_BYTES = 1000


def cover_path_for(record: BookRecord) -> Path:
    """Where this record's cover lives on disk."""
    stem = record.id or Path(record.file_name or "cover").stem
    return COVERS_DIR / f"{stem}_cover.jpg"


def relative_cover_path(path: Path) -> str:
    """The project-relative path stored on the record."""
    return str(path.relative_to(COVERS_DIR.parent.parent))


def save_cover(
    record: BookRecord,
    image,
    source: str,
    confidence: float,
    min_bytes: int = MIN_COVER_BYTES,
) -> bool:
    """
    Save `image` as this record's cover and record where it came from.

    `image` is raw bytes or an already-open PIL image. Returns True when a
    cover was written. A record that already has one is left alone — the first
    cover found wins, and the callers are ordered by how much they are trusted.
    """
    if record.cover_path:
        return False
    if isinstance(image, (bytes, bytearray)) and len(image) < min_bytes:
        return False

    try:
        from PIL import Image
    except ImportError:
        logger.debug("Pillow not installed, skipping cover")
        return False

    try:
        img = Image.open(io.BytesIO(bytes(image))) if isinstance(
            image, (bytes, bytearray)
        ) else image.copy()
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        if img.width > MAX_COVER_SIZE[0] or img.height > MAX_COVER_SIZE[1]:
            img.thumbnail(MAX_COVER_SIZE, Image.LANCZOS)

        path = cover_path_for(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(path), "JPEG", quality=JPEG_QUALITY)
    except Exception as e:
        logger.debug(f"Cover could not be saved for {record.file_name}: {e}")
        return False

    # Through `set_field`, never by assignment: a cover a human pinned outranks
    # anything a scraper finds later.
    return record.set_field("cover_path", relative_cover_path(path), source, confidence)
