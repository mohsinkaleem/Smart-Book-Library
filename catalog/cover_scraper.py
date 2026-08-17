"""
Cover image fallback using Playwright.

When no cover was found via API or embedded images, scrapes cover images
from book websites (Open Library, Google Books, Amazon, Goodreads).

Requirements:
    pip install playwright
    playwright install chromium
"""
import logging
import re
import time
from pathlib import Path
from typing import Optional

from .config import COVERS_DIR, API_REQUEST_TIMEOUT
from .models import BookRecord

logger = logging.getLogger(__name__)

# Search sources in priority order
COVER_SOURCES = [
    "openlibrary",
    "google_books",
    "amazon",
]


def is_available() -> bool:
    """Check if Playwright is installed and has browsers."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        return False


def fetch_cover_playwright(record: BookRecord, headless: bool = True) -> BookRecord:
    """
    Attempt to find and download a cover image using Playwright browser automation.
    Only runs for books that don't already have a cover.
    """
    if record.cover_path:
        return record

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning(
            "Playwright not installed. Install with:\n"
            "  pip install playwright && playwright install chromium"
        )
        return record

    search_query = _build_search_query(record)
    if not search_query:
        return record

    logger.info(f"   🌐 Searching for cover: {record.title[:50]}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page.set_default_timeout(15000)

        cover_url = None

        try:
            # Strategy 1: Open Library direct search
            cover_url = _search_openlibrary_cover(page, search_query)

            # Strategy 2: Google Books search
            if not cover_url:
                cover_url = _search_google_books_cover(page, search_query)

            # Strategy 3: Google Image search (last resort)
            if not cover_url:
                cover_url = _search_google_images_cover(page, search_query)

        except Exception as e:
            logger.debug(f"Playwright cover search failed for {record.file_name}: {e}")
        finally:
            browser.close()

        # Download the cover if we found one
        if cover_url:
            _download_cover_image(record, cover_url)

    return record


def _build_search_query(record: BookRecord) -> str:
    """Build a search query from record metadata."""
    parts = []
    if record.title:
        parts.append(record.title)
    if record.authors:
        parts.append(record.authors[0])
    return " ".join(parts).strip()


def _search_openlibrary_cover(page, query: str) -> Optional[str]:
    """Search Open Library for a cover image."""
    try:
        encoded = query.replace(" ", "+")
        page.goto(
            f"https://openlibrary.org/search?q={encoded}&mode=everything",
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(2000)

        # Look for cover images in search results
        cover_img = page.query_selector("img.bookcover")
        if cover_img:
            src = cover_img.get_attribute("src")
            if src and "covers" in src:
                # Get the large version
                src = re.sub(r"-[SML]\.jpg", "-L.jpg", src)
                if not src.startswith("http"):
                    src = "https:" + src if src.startswith("//") else "https://covers.openlibrary.org" + src
                return src
    except Exception as e:
        logger.debug(f"OpenLibrary cover search error: {e}")
    return None


def _search_google_books_cover(page, query: str) -> Optional[str]:
    """Search Google Books for a cover image."""
    try:
        encoded = query.replace(" ", "+")
        page.goto(
            f"https://www.google.com/search?tbm=bks&q={encoded}",
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(2000)

        # Look for book thumbnail images
        imgs = page.query_selector_all("img")
        for img in imgs:
            src = img.get_attribute("src") or ""
            # Google Books thumbnails contain "books.google" or "encrypted-tbn"
            if ("books.google" in src or "content" in src) and "1x1" not in src:
                width = img.evaluate("el => el.naturalWidth")
                if width and width > 50:
                    # Try to get higher resolution
                    src = re.sub(r"zoom=\d", "zoom=3", src)
                    return src
    except Exception as e:
        logger.debug(f"Google Books cover search error: {e}")
    return None


def _search_google_images_cover(page, query: str) -> Optional[str]:
    """Search Google Images for a book cover (last resort)."""
    try:
        search_term = f"{query} book cover"
        encoded = search_term.replace(" ", "+")
        page.goto(
            f"https://www.google.com/search?tbm=isch&q={encoded}",
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(2000)

        # Get the first reasonable image
        imgs = page.query_selector_all("img[src^='http']")
        for img in imgs[:5]:
            src = img.get_attribute("src") or ""
            if src.startswith("http") and "gstatic" not in src:
                return src
    except Exception as e:
        logger.debug(f"Google Images cover search error: {e}")
    return None


def _download_cover_image(record: BookRecord, url: str):
    """Download a cover image from URL using requests."""
    try:
        import requests
        from PIL import Image
        import io

        resp = requests.get(url, timeout=API_REQUEST_TIMEOUT, stream=True)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type and len(resp.content) < 1000:
            return

        cover_name = f"{record.id or Path(record.file_name).stem}_cover.jpg"
        cover_path = COVERS_DIR / cover_name

        img = Image.open(io.BytesIO(resp.content))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        if img.width > 800 or img.height > 1200:
            img.thumbnail((800, 1200), Image.LANCZOS)
        img.save(str(cover_path), "JPEG", quality=85)

        record.cover_path = str(cover_path.relative_to(COVERS_DIR.parent.parent))
        logger.info(f"   🖼️  Downloaded cover via Playwright for {record.file_name}")

    except Exception as e:
        logger.debug(f"Failed to download Playwright cover from {url}: {e}")
