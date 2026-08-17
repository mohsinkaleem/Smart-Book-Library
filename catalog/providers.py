"""
HTTP providers: OpenLibrary and Google Books.

Fixes the reliability half of the review:

* one pooled `requests.Session` with retries, backoff and a descriptive
  User-Agent — OpenLibrary throttles anonymous bulk traffic, and every one of
  the 143 historical OL calls failed without a single visible log line;
* the cache stores `{status, fetched_at, payload}`. `error` is never reused,
  `not_found` expires after a TTL, so a transient reset is no longer a
  permanent "this book does not exist";
* per-host token buckets replace the global `time.sleep(1)`;
* per-source counters (attempted / ok / not_found / error) so a dead provider
  is impossible to miss.

Queries are field-scoped (`intitle:` / `title=`). A flat concatenated string is
what let "aisha adobe indesign cs5.5" return an InDesign manual.
"""
import json
import logging
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from .config import (
    API_COOLDOWN_SECONDS,
    API_ERROR_RATE_ALERT,
    API_MAX_RETRIES,
    API_RATE_LIMIT_BY_HOST,
    API_NEGATIVE_CACHE_TTL_DAYS,
    API_RATE_LIMIT_BURST,
    API_RATE_LIMIT_PER_SECOND,
    API_REQUEST_TIMEOUT,
    API_RETRY_BACKOFF,
    API_USER_AGENT,
    ENRICHMENT_CACHE_FILE,
    GOOGLE_BOOKS_API_KEY,
    GOOGLE_BOOKS_API_URL,
    OPENLIBRARY_BOOKS_URL,
    OPENLIBRARY_COVERS_URL,
    OPENLIBRARY_SEARCH_URL,
    OPENLIBRARY_WORKS_BASE,
)
from .evidence import Candidate
from .isbn_extractor import normalize_isbn, validate_isbn10, validate_isbn13

logger = logging.getLogger(__name__)

OK = "ok"
NOT_FOUND = "not_found"
ERROR = "error"


# ── Rate limiting ───────────────────────────────────────────────────────────────

class TokenBucket:
    """Per-host request budget; hosts are limited independently."""

    def __init__(self, rate: float, burst: int):
        self.rate = max(rate, 0.1)
        self.capacity = max(burst, 1)
        self._tokens = float(self.capacity)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(
                    self.capacity, self._tokens + (now - self._updated) * self.rate
                )
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                sleep_for = (1 - self._tokens) / self.rate
                time.sleep(min(sleep_for, 5.0))


_buckets: dict[str, TokenBucket] = {}
_buckets_lock = threading.Lock()
_cooldowns: dict[str, float] = {}


def _bucket_for(url: str) -> TokenBucket:
    host = urlparse(url).netloc
    with _buckets_lock:
        if host not in _buckets:
            rate, burst = API_RATE_LIMIT_BY_HOST.get(
                host, (API_RATE_LIMIT_PER_SECOND, API_RATE_LIMIT_BURST)
            )
            _buckets[host] = TokenBucket(rate, burst)
        return _buckets[host]


def _cooling_down(url: str) -> bool:
    """True while a host is in post-429 cool-down."""
    host = urlparse(url).netloc
    with _buckets_lock:
        until = _cooldowns.get(host, 0.0)
    return time.monotonic() < until


def _start_cooldown(url: str, seconds: float = API_COOLDOWN_SECONDS):
    host = urlparse(url).netloc
    with _buckets_lock:
        _cooldowns[host] = time.monotonic() + seconds
    logger.warning(f"{host} rate-limited us — pausing requests to it for {seconds:.0f}s")


# ── Cache ───────────────────────────────────────────────────────────────────────

class ResponseCache:
    """
    File-backed cache of provider answers with an explicit status.

    Legacy entries (bare payloads with no status) are dropped on load: they are
    exactly the poisoned negatives that kept OpenLibrary dead.
    """

    def __init__(self, cache_file: Path = ENRICHMENT_CACHE_FILE):
        self.cache_file = cache_file
        self._cache: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._dirty = 0
        self.purged_legacy = 0
        self._load()

    def _load(self):
        if not self.cache_file.exists():
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return
        for key, value in raw.items():
            if isinstance(value, dict) and "status" in value and "payload" in value:
                self._cache[key] = value
            else:
                self.purged_legacy += 1
        if self.purged_legacy:
            logger.info(
                f"Dropped {self.purged_legacy} legacy cache entries "
                "(statusless payloads, including the poisoned OpenLibrary negatives)"
            )

    def get(self, key: str) -> Optional[dict]:
        with self._lock:
            entry = self._cache.get(key)
        if not entry:
            return None
        status = entry.get("status")
        if status == ERROR:
            return None                       # never reuse a failure
        if status == NOT_FOUND:
            try:
                fetched = datetime.fromisoformat(entry.get("fetched_at", ""))
            except ValueError:
                return None
            if datetime.now() - fetched > timedelta(days=API_NEGATIVE_CACHE_TTL_DAYS):
                return None                   # negative results expire
        return entry

    def set(self, key: str, status: str, payload):
        with self._lock:
            self._cache[key] = {
                "status": status,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
                "payload": payload,
            }
            self._dirty += 1
            should_save = self._dirty >= 50
        if should_save:
            self.save()

    def save(self):
        with self._lock:
            snapshot = dict(self._cache)
            self._dirty = 0
        tmp = self.cache_file.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False)
        tmp.rename(self.cache_file)


_cache = ResponseCache()


def save_cache():
    _cache.save()


# ── HTTP ────────────────────────────────────────────────────────────────────────

_session: Optional[requests.Session] = None
_session_lock = threading.Lock()

_metrics: dict[str, dict[str, int]] = defaultdict(
    lambda: {"attempted": 0, "ok": 0, "not_found": 0, "error": 0, "cached": 0, "cooldown": 0}
)
_metrics_lock = threading.Lock()


def _get_session() -> requests.Session:
    global _session
    with _session_lock:
        if _session is None:
            from requests.adapters import HTTPAdapter
            try:
                from urllib3.util.retry import Retry
                retry = Retry(
                    total=API_MAX_RETRIES,
                    backoff_factor=API_RETRY_BACKOFF,
                    status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["GET"],
                    respect_retry_after_header=True,
                    raise_on_status=False,
                )
                adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
            except Exception:  # pragma: no cover - urllib3 always present with requests
                adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8)
            session = requests.Session()
            session.headers.update({"User-Agent": API_USER_AGENT, "Accept": "application/json"})
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            _session = session
    return _session


def _record_metric(source: str, outcome: str):
    with _metrics_lock:
        _metrics[source][outcome] += 1


def get_metrics() -> dict:
    with _metrics_lock:
        return {source: dict(counts) for source, counts in _metrics.items()}


def reset_metrics():
    with _metrics_lock:
        _metrics.clear()


def unhealthy_sources() -> list[str]:
    """Sources whose error rate exceeds the alert threshold, or that are throttling us."""
    out = []
    for source, counts in get_metrics().items():
        attempted = counts["attempted"]
        if attempted >= 5 and counts["error"] / attempted > API_ERROR_RATE_ALERT:
            out.append(source)
        elif counts.get("cooldown", 0) >= 5 and counts["ok"] == 0:
            out.append(source)
    return out


def _fetch_json(source: str, cache_key: str, url: str, params: dict = None) -> tuple[str, dict]:
    """GET JSON with caching, rate limiting and explicit status."""
    cached = _cache.get(cache_key)
    if cached is not None:
        _record_metric(source, "cached")
        return cached["status"], cached.get("payload") or {}

    if _cooling_down(url):
        # Our own throttle, not the provider's answer: counted separately so it
        # does not distort the error rate, and never cached.
        _record_metric(source, "cooldown")
        return ERROR, {}

    _record_metric(source, "attempted")
    _bucket_for(url).acquire()
    try:
        resp = _get_session().get(url, params=params, timeout=API_REQUEST_TIMEOUT)
        if resp.status_code == 404:
            _cache.set(cache_key, NOT_FOUND, {})
            _record_metric(source, "not_found")
            return NOT_FOUND, {}
        if resp.status_code == 429:
            _start_cooldown(url)
            _record_metric(source, "error")
            return ERROR, {}
        resp.raise_for_status()
        payload = resp.json()
        _cache.set(cache_key, OK, payload)
        _record_metric(source, "ok")
        return OK, payload
    except Exception as e:
        # An error is cached as an error, and errors are never reused.
        _cache.set(cache_key, ERROR, {"error": str(e)[:300]})
        _record_metric(source, "error")
        logger.warning(f"{source} request failed ({url}): {e}")
        return ERROR, {}


def probe_sources() -> dict:
    """Probe each provider once — used by `--verify-sources`."""
    results = {}
    probes = [
        ("openlibrary", OPENLIBRARY_SEARCH_URL, {"title": "the road to mecca", "limit": 1, "fields": "key,title"}),
        ("google_books", GOOGLE_BOOKS_API_URL, {"q": 'intitle:"the road to mecca"', "maxResults": 1}),
    ]
    for name, url, params in probes:
        _bucket_for(url).acquire()
        started = time.time()
        try:
            resp = _get_session().get(url, params=params, timeout=API_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            count = len(data.get("docs", data.get("items", [])) or [])
            results[name] = {
                "ok": True,
                "status_code": resp.status_code,
                "results": count,
                "elapsed_ms": int((time.time() - started) * 1000),
            }
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)[:200]}
    return results


# ── Normalisation helpers ───────────────────────────────────────────────────────

def _year(value) -> Optional[int]:
    m = re.search(r"(\d{4})", str(value or ""))
    if m:
        year = int(m.group(1))
        if 1800 <= year <= 2035:
            return year
    return None


def _pick_isbns(values) -> tuple[str, str]:
    isbn13, isbn10 = "", ""
    for value in values or []:
        clean = normalize_isbn(str(value))
        if not isbn13 and len(clean) == 13 and validate_isbn13(clean):
            isbn13 = clean
        elif not isbn10 and len(clean) == 10 and validate_isbn10(clean):
            isbn10 = clean
    return isbn13, isbn10


def _query_key(*parts: str) -> str:
    joined = "_".join(p for p in parts if p)
    return re.sub(r"[^a-z0-9]+", "_", joined.lower()).strip("_")[:120]


# ── OpenLibrary ─────────────────────────────────────────────────────────────────

def openlibrary_by_isbn(isbn: str) -> list[Candidate]:
    status, data = _fetch_json(
        "openlibrary",
        f"ol_isbn_{isbn}",
        OPENLIBRARY_BOOKS_URL,
        {"bibkeys": f"ISBN:{isbn}", "format": "json", "jscmd": "data"},
    )
    if status != OK:
        return []
    info = (data or {}).get(f"ISBN:{isbn}")
    if not info:
        _cache.set(f"ol_isbn_{isbn}", NOT_FOUND, {})
        return []

    identifiers = info.get("identifiers", {}) or {}
    isbn13, isbn10 = _pick_isbns(
        (identifiers.get("isbn_13") or []) + (identifiers.get("isbn_10") or []) + [isbn]
    )
    cover = info.get("cover", {}) or {}
    return [Candidate(
        provider="openlibrary",
        strategy="isbn",
        title=info.get("title", ""),
        subtitle=info.get("subtitle", ""),
        authors=[a.get("name", "") for a in info.get("authors", []) if a.get("name")],
        publisher=(info.get("publishers") or [{}])[0].get("name", ""),
        year=_year(info.get("publish_date", "")),
        isbn_13=isbn13 or (isbn if len(isbn) == 13 else ""),
        isbn_10=isbn10 or (isbn if len(isbn) == 10 else ""),
        page_count=info.get("number_of_pages"),
        subjects=[s.get("name", "") for s in (info.get("subjects") or []) if s.get("name")][:15],
        cover_url=cover.get("large") or cover.get("medium") or cover.get("small") or "",
        work_key=((info.get("works") or [{}])[0].get("key", "")),
        raw={},
    )]


def openlibrary_search(title: str, author: str = "", limit: int = 3) -> list[Candidate]:
    """Field-scoped search — `title=` and `author=`, never one flat string."""
    if not title:
        return []
    params = {
        "title": title,
        "limit": limit,
        "fields": "key,title,subtitle,author_name,first_publish_year,publisher,"
                  "isbn,subject,cover_i,number_of_pages_median,language",
    }
    if author:
        params["author"] = author

    status, data = _fetch_json(
        "openlibrary",
        f"ol_search_{_query_key(title, author)}",
        OPENLIBRARY_SEARCH_URL,
        params,
    )
    if status != OK:
        return []

    docs = (data or {}).get("docs", []) or []
    candidates = []
    for doc in docs[:limit]:
        isbn13, isbn10 = _pick_isbns(doc.get("isbn") or [])
        candidates.append(Candidate(
            provider="openlibrary",
            strategy="title_author" if author else "title",
            title=doc.get("title", ""),
            subtitle=doc.get("subtitle", ""),
            authors=(doc.get("author_name") or [])[:5],
            publisher=(doc.get("publisher") or [""])[0],
            year=doc.get("first_publish_year"),
            isbn_13=isbn13,
            isbn_10=isbn10,
            page_count=doc.get("number_of_pages_median"),
            language=(doc.get("language") or [""])[0][:3],
            subjects=(doc.get("subject") or [])[:15],
            cover_url=(f"{OPENLIBRARY_COVERS_URL}/id/{doc['cover_i']}-L.jpg"
                       if doc.get("cover_i") else ""),
            work_key=doc.get("key", ""),
        ))
    return candidates


def openlibrary_work_details(work_key: str) -> dict:
    """Description and subjects for an accepted OpenLibrary work."""
    if not work_key:
        return {}
    status, data = _fetch_json(
        "openlibrary",
        f"ol_work_{_query_key(work_key)}",
        f"{OPENLIBRARY_WORKS_BASE}{work_key}.json",
    )
    if status != OK or not data:
        return {}
    desc = data.get("description", "")
    if isinstance(desc, dict):
        desc = desc.get("value", "")
    return {"description": desc or "", "subjects": (data.get("subjects") or [])[:15]}


# ── Google Books ────────────────────────────────────────────────────────────────

def _google_books(query: str, cache_key: str, strategy: str, limit: int = 3) -> list[Candidate]:
    params = {"q": query, "maxResults": limit}
    if GOOGLE_BOOKS_API_KEY:
        params["key"] = GOOGLE_BOOKS_API_KEY

    status, data = _fetch_json("google_books", cache_key, GOOGLE_BOOKS_API_URL, params)
    if status != OK:
        return []

    items = (data or {}).get("items", []) or []
    candidates = []
    for item in items[:limit]:
        vol = item.get("volumeInfo", {}) or {}
        isbn13, isbn10 = _pick_isbns(
            [i.get("identifier") for i in vol.get("industryIdentifiers", []) or []]
        )
        images = vol.get("imageLinks", {}) or {}
        cover = (images.get("thumbnail") or images.get("small")
                 or images.get("smallThumbnail") or "")
        candidates.append(Candidate(
            provider="google_books",
            strategy=strategy,
            title=vol.get("title", ""),
            subtitle=vol.get("subtitle", ""),
            authors=(vol.get("authors") or [])[:5],
            publisher=vol.get("publisher", ""),
            year=_year(vol.get("publishedDate", "")),
            isbn_13=isbn13,
            isbn_10=isbn10,
            page_count=vol.get("pageCount"),
            language=vol.get("language", ""),
            description=vol.get("description", ""),
            subjects=(vol.get("categories") or [])[:10],
            cover_url=cover.replace("http://", "https://") if cover else "",
        ))
    return candidates


def google_books_by_isbn(isbn: str) -> list[Candidate]:
    return _google_books(f"isbn:{isbn}", f"gb_isbn_{isbn}", "isbn", limit=2)


def google_books_search(title: str, author: str = "", limit: int = 3) -> list[Candidate]:
    if not title:
        return []
    query = f'intitle:"{title}"'
    if author:
        query += f' inauthor:"{author}"'
    return _google_books(query, f"gb_search_{_query_key(title, author)}",
                         "title_author" if author else "title", limit)
