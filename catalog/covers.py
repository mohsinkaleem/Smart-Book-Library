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

`is_usable_cover` lives here too, next to the thing it guards. It is the
server-side half of `isUnusableCover()` in `frontend/.../BookCover.tsx`,
decided once at extraction time instead of on every render. It is applied by
the *callers* that synthesise an image rather than inside `save_cover`,
because a real jacket is a cover whatever its pixels look like — a flat
OpenLibrary jacket is still the publisher's jacket, while a flat rendered page
1 is a blank sheet of paper.

What it measures is **ink**, not uniformity. The browser's original test —
"more than 90% of a 20x20 downscale is one colour" — is right for a
*downloaded image*, where one flat colour means a corrupt file, and badly
wrong for a *rendered page*, where white paper is the normal state of affairs.
Measured over this catalog it rejected 61 of 92 page-1 renders, among them the
title pages of The Kite Runner, Mein Kampf and The Holy Bible: pages that name
their book in 48pt type and were thrown away for having margins. The ink
fraction separates the two cases by two orders of magnitude — a blank page
with a page number on it scores 0.00001, the sparsest real title page in the
catalog 0.0017 — so the floor sits in open space rather than on a cliff.
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

# The weakest cover there is: page 1 of the PDF, rendered. Used only when the
# embedded images, the providers and the scraper all came up empty. It carries
# its own source label so `field_sources` says plainly that the "cover" is a
# page of the book, and a confidence below every other cover source so it
# never outranks a real jacket.
PDF_PAGE_SOURCE = "pdf_page_1"
PDF_PAGE_CONFIDENCE = 0.1

# ── Usability thresholds (mirrored in BookCover.tsx) ──
# Real covers are roughly 1:1.2 to 1:1.8; anything outside 1:4–4:1 is a spine
# scan or a thin strip.
MIN_COVER_PIXELS = 50
COVER_ASPECT_MIN = 0.25
COVER_ASPECT_MAX = 4.0
# A pixel counts as ink when it is this far in grey level from the image's
# modal (background) tone. Measured at full resolution: downscaling first is
# what loses thin type, which is exactly the type a title page is set in.
INK_GREY_DELTA = 40
# Below this fraction of ink there is nothing on the page to recognise.
MIN_INK_FRACTION = 0.001


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


def is_usable_cover(image) -> str:
    """
    Why `image` is unusable as a cover, or "" when it is fine.

    `image` is raw bytes or an already-open PIL image, as for `save_cover`. A
    reason rather than a bool because the caller logs it: "page 1 is blank" and
    "page 1 is a 39x1200 strip" are different facts about the book.

    An image we cannot even open is reported as usable — `save_cover` is the
    one that has to fail on it, and it already does.
    """
    try:
        from PIL import Image
    except ImportError:
        return ""

    try:
        img = Image.open(io.BytesIO(bytes(image))) if isinstance(
            image, (bytes, bytearray)
        ) else image
        width, height = img.width, img.height
    except Exception:
        return ""

    if width < MIN_COVER_PIXELS or height < MIN_COVER_PIXELS:
        return f"too small ({width}x{height})"

    ratio = width / height if height else 0
    if ratio < COVER_ASPECT_MIN or ratio > COVER_ASPECT_MAX:
        return f"extreme aspect ratio ({width}x{height})"

    try:
        ink = ink_fraction(img)
    except Exception:
        return ""

    if ink < MIN_INK_FRACTION:
        return f"nothing on the page ({ink:.4%} ink)"
    return ""


def ink_fraction(img) -> float:
    """
    How much of `img` is not its own background, as a fraction of its pixels.

    The background is the modal grey level rather than a corner pixel: a page
    scanned at an angle, or a jacket with a border, has a corner that is not
    the page. `histogram()` does the counting in C, so this is one cheap pass
    over the image at full resolution.
    """
    histogram = img.convert("L").histogram()
    background = histogram.index(max(histogram))
    low = max(0, background - INK_GREY_DELTA)
    high = min(255, background + INK_GREY_DELTA)
    total = sum(histogram) or 1
    return 1.0 - sum(histogram[low:high + 1]) / total
