"""
API enrichment module - fetches metadata from OpenLibrary and Google Books APIs.

Strategies:
1. Search by ISBN (most accurate)
2. Search by title + author
3. Search by title only (fallback)

Implements caching to avoid redundant API calls.
"""
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import requests

from .config import (
    OPENLIBRARY_SEARCH_URL,
    OPENLIBRARY_WORKS_URL,
    OPENLIBRARY_BOOKS_URL,
    OPENLIBRARY_COVERS_URL,
    GOOGLE_BOOKS_API_URL,
    GOOGLE_BOOKS_API_KEY,
    API_REQUEST_TIMEOUT,
    API_RATE_LIMIT_DELAY,
    ENRICHMENT_CACHE_FILE,
    COVERS_DIR,
)
from .models import BookRecord

logger = logging.getLogger(__name__)


class APICache:
    """Simple file-based cache for API responses."""

    def __init__(self, cache_file: Path = ENRICHMENT_CACHE_FILE):
        self.cache_file = cache_file
        self._cache = {}
        self._load()

    def _load(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception:
                self._cache = {}

    def save(self):
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, indent=2, ensure_ascii=False)

    def get(self, key: str) -> Optional[dict]:
        return self._cache.get(key)

    def set(self, key: str, value: dict):
        self._cache[key] = value

    def has(self, key: str) -> bool:
        return key in self._cache


_cache = APICache()


def enrich_from_apis(record: BookRecord) -> BookRecord:
    """
    Enrich a BookRecord using OpenLibrary and Google Books APIs.
    Tries multiple search strategies in order of reliability.
    """
    enriched = False

    # Strategy 1: Search by ISBN (most reliable)
    if record.isbn_13 or record.isbn_10:
        isbn = record.isbn_13 or record.isbn_10
        enriched = _enrich_openlibrary_isbn(record, isbn)
        if not enriched:
            enriched = _enrich_google_books_isbn(record, isbn)

    # Strategy 2: Search by title + author
    if not enriched and record.title:
        search_query = record.title
        if record.authors:
            search_query += " " + record.authors[0]
        enriched = _enrich_openlibrary_search(record, search_query)
        if not enriched:
            enriched = _enrich_google_books_search(record, search_query)

    # Strategy 3: Title only (broader search)
    if not enriched and record.title:
        enriched = _enrich_google_books_search(record, record.title)

    _cache.save()
    return record


# ─── OpenLibrary ────────────────────────────────────────────────────────────────

def _enrich_openlibrary_isbn(record: BookRecord, isbn: str) -> bool:
    """Enrich using OpenLibrary ISBN API."""
    cache_key = f"ol_isbn_{isbn}"
    data = _cache.get(cache_key)

    if data is None:
        try:
            url = f"{OPENLIBRARY_BOOKS_URL}?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
            resp = requests.get(url, timeout=API_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            _cache.set(cache_key, data)
            time.sleep(API_RATE_LIMIT_DELAY)
        except Exception as e:
            logger.debug(f"OpenLibrary ISBN lookup failed for {isbn}: {e}")
            _cache.set(cache_key, {})
            return False

    book_key = f"ISBN:{isbn}"
    if book_key not in data:
        return False

    info = data[book_key]
    _apply_openlibrary_data(record, info)
    if "openlibrary" not in record.api_sources:
        record.api_sources.append("openlibrary")
    return True


def _enrich_openlibrary_search(record: BookRecord, query: str) -> bool:
    """Enrich using OpenLibrary Search API."""
    cache_key = f"ol_search_{_normalize_query(query)}"
    data = _cache.get(cache_key)

    if data is None:
        try:
            params = {"q": query, "limit": 3, "fields": "key,title,author_name,first_publish_year,publisher,isbn,subject,cover_i,number_of_pages_median,language"}
            resp = requests.get(OPENLIBRARY_SEARCH_URL, params=params, timeout=API_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            _cache.set(cache_key, data)
            time.sleep(API_RATE_LIMIT_DELAY)
        except Exception as e:
            logger.debug(f"OpenLibrary search failed for '{query}': {e}")
            _cache.set(cache_key, {"docs": []})
            return False

    docs = data.get("docs", [])
    if not docs:
        return False

    # Take the best match (first result)
    doc = docs[0]
    _apply_openlibrary_search_data(record, doc)

    # Try to get detailed work info for description
    work_key = doc.get("key", "")
    if work_key:
        _fetch_openlibrary_work_details(record, work_key)

    if "openlibrary" not in record.api_sources:
        record.api_sources.append("openlibrary")
    return True


def _fetch_openlibrary_work_details(record: BookRecord, work_key: str):
    """Fetch detailed work info from OpenLibrary for description/subjects."""
    cache_key = f"ol_work_{work_key}"
    data = _cache.get(cache_key)

    if data is None:
        try:
            url = f"https://openlibrary.org{work_key}.json"
            resp = requests.get(url, timeout=API_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            _cache.set(cache_key, data)
            time.sleep(API_RATE_LIMIT_DELAY)
        except Exception as e:
            logger.debug(f"OpenLibrary work details failed for {work_key}: {e}")
            _cache.set(cache_key, {})
            return

    if not data:
        return

    # Description
    desc = data.get("description", "")
    if isinstance(desc, dict):
        desc = desc.get("value", "")
    if desc and not record.description:
        record.description = desc[:2000]

    # Subjects
    subjects = data.get("subjects", [])
    if subjects and not record.categories:
        record.categories = subjects[:10]


def _apply_openlibrary_data(record: BookRecord, info: dict):
    """Apply data from OpenLibrary Books API response."""
    if not record.title or record.title == record.file_name:
        record.title = info.get("title", record.title)

    if not record.original_title_meta:
        record.original_title_meta = info.get("title", "")

    authors = info.get("authors", [])
    if authors and not record.authors:
        record.authors = [a.get("name", "") for a in authors if a.get("name")]

    publishers = info.get("publishers", [])
    if publishers and not record.publisher:
        record.publisher = publishers[0].get("name", "")

    if not record.publication_year:
        publish_date = info.get("publish_date", "")
        year = _extract_year_from_string(publish_date)
        if year:
            record.publication_year = year

    if not record.page_count:
        record.page_count = info.get("number_of_pages")

    subjects = info.get("subjects", [])
    if subjects and not record.categories:
        record.categories = [s.get("name", "") for s in subjects[:10] if s.get("name")]

    # Cover
    cover = info.get("cover", {})
    if cover and not record.cover_path:
        cover_url = cover.get("large") or cover.get("medium") or cover.get("small")
        if cover_url:
            _download_cover(record, cover_url)


def _apply_openlibrary_search_data(record: BookRecord, doc: dict):
    """Apply data from OpenLibrary Search API response."""
    if not record.original_title_meta:
        record.original_title_meta = doc.get("title", "")

    if doc.get("author_name") and not record.authors:
        record.authors = doc["author_name"][:5]

    if doc.get("publisher") and not record.publisher:
        record.publisher = doc["publisher"][0] if doc["publisher"] else ""

    if doc.get("first_publish_year") and not record.publication_year:
        record.publication_year = doc["first_publish_year"]

    if doc.get("number_of_pages_median") and not record.page_count:
        record.page_count = doc["number_of_pages_median"]

    if doc.get("subject") and not record.categories:
        record.categories = doc["subject"][:10]

    if doc.get("language") and not record.language:
        langs = doc["language"]
        record.language = langs[0] if langs else ""

    # ISBN
    if doc.get("isbn"):
        isbns = doc["isbn"]
        for isbn in isbns:
            clean = re.sub(r"[^0-9Xx]", "", isbn)
            if len(clean) == 13 and not record.isbn_13:
                record.isbn_13 = clean
            elif len(clean) == 10 and not record.isbn_10:
                record.isbn_10 = clean

    # Cover from cover_i
    cover_i = doc.get("cover_i")
    if cover_i and not record.cover_path:
        cover_url = f"{OPENLIBRARY_COVERS_URL}/id/{cover_i}-L.jpg"
        _download_cover(record, cover_url)


# ─── Google Books ───────────────────────────────────────────────────────────────

def _enrich_google_books_isbn(record: BookRecord, isbn: str) -> bool:
    """Enrich using Google Books API by ISBN."""
    return _enrich_google_books_search(record, f"isbn:{isbn}")


def _enrich_google_books_search(record: BookRecord, query: str) -> bool:
    """Enrich using Google Books API search."""
    cache_key = f"gb_search_{_normalize_query(query)}"
    data = _cache.get(cache_key)

    if data is None:
        try:
            params = {"q": query, "maxResults": 3}
            if GOOGLE_BOOKS_API_KEY:
                params["key"] = GOOGLE_BOOKS_API_KEY
            resp = requests.get(GOOGLE_BOOKS_API_URL, params=params, timeout=API_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            _cache.set(cache_key, data)
            time.sleep(API_RATE_LIMIT_DELAY)
        except Exception as e:
            logger.debug(f"Google Books search failed for '{query}': {e}")
            _cache.set(cache_key, {"totalItems": 0})
            return False

    items = data.get("items", [])
    if not items:
        return False

    # Best match
    vol = items[0].get("volumeInfo", {})
    _apply_google_books_data(record, vol)

    if "google_books" not in record.api_sources:
        record.api_sources.append("google_books")
    return True


def _apply_google_books_data(record: BookRecord, vol: dict):
    """Apply data from Google Books API response."""
    if not record.original_title_meta:
        title = vol.get("title", "")
        subtitle = vol.get("subtitle", "")
        if subtitle:
            title = f"{title}: {subtitle}"
        record.original_title_meta = title

    if vol.get("authors") and not record.authors:
        record.authors = vol["authors"][:5]

    if vol.get("publisher") and not record.publisher:
        record.publisher = vol["publisher"]

    if vol.get("publishedDate") and not record.publication_year:
        year = _extract_year_from_string(vol["publishedDate"])
        if year:
            record.publication_year = year

    if vol.get("pageCount") and not record.page_count:
        record.page_count = vol["pageCount"]

    if vol.get("description") and not record.description:
        record.description = vol["description"][:2000]

    if vol.get("categories") and not record.categories:
        record.categories = vol["categories"][:10]

    if vol.get("language") and not record.language:
        record.language = vol["language"]

    # ISBNs
    identifiers = vol.get("industryIdentifiers", [])
    for ident in identifiers:
        id_type = ident.get("type", "")
        id_val = ident.get("identifier", "")
        if id_type == "ISBN_13" and not record.isbn_13:
            record.isbn_13 = id_val
        elif id_type == "ISBN_10" and not record.isbn_10:
            record.isbn_10 = id_val

    # Cover
    images = vol.get("imageLinks", {})
    if images and not record.cover_path:
        cover_url = (
                images.get("thumbnail")
                or images.get("smallThumbnail")
                or images.get("small")
                or images.get("medium")
        )
        if cover_url:
            # Google Books uses http, upgrade to https
            cover_url = cover_url.replace("http://", "https://")
            _download_cover(record, cover_url)


# ─── Utilities ──────────────────────────────────────────────────────────────────

def _download_cover(record: BookRecord, url: str):
    """Download a cover image from URL."""
    if record.cover_path:  # Already have a cover
        return

    try:
        resp = requests.get(url, timeout=API_REQUEST_TIMEOUT, stream=True)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type and len(resp.content) < 1000:
            return  # Not a valid image

        # Determine extension
        ext = "jpg"
        if "png" in content_type:
            ext = "png"

        cover_name = f"{Path(record.file_name).stem}_cover.{ext}"
        cover_path = COVERS_DIR / cover_name

        with open(cover_path, "wb") as f:
            f.write(resp.content)

        # Try to optimize with PIL
        try:
            from PIL import Image
            img = Image.open(cover_path)
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            if img.width > 800 or img.height > 1200:
                img.thumbnail((800, 1200), Image.LANCZOS)
            # Save as JPEG
            jpg_path = cover_path.with_suffix(".jpg")
            img.save(str(jpg_path), "JPEG", quality=85)
            if jpg_path != cover_path:
                cover_path.unlink(missing_ok=True)
                cover_path = jpg_path
        except Exception:
            pass

        record.cover_path = str(cover_path.relative_to(COVERS_DIR.parent.parent))
        logger.debug(f"Downloaded cover for {record.file_name}")

    except Exception as e:
        logger.debug(f"Failed to download cover from {url}: {e}")


def _normalize_query(query: str) -> str:
    """Normalize a search query for cache key."""
    return re.sub(r"\s+", "_", query.lower().strip())[:100]


def _extract_year_from_string(s: str) -> Optional[int]:
    """Extract a year from a string."""
    m = re.search(r"(\d{4})", s)
    if m:
        year = int(m.group(1))
        if 1800 <= year <= 2030:
            return year
    return None


def save_cache():
    """Explicitly save the API cache."""
    _cache.save()
