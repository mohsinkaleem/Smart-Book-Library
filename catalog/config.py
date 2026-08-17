"""
Configuration for the book catalog enrichment pipeline.

This is the ONLY place pipeline settings are defined. Modules must import from
here rather than declaring their own module-local copies (which used to shadow
these values silently).

Every setting can be overridden with an environment variable of the same name,
e.g. ``OCR_LANGUAGE=eng+ara python build_catalog.py``.
"""
from pathlib import Path
import os


def _load_dotenv():
    """
    Load `.env` from the project root into the environment (without overriding
    variables already set in the shell). Keeps secrets such as
    GOOGLE_BOOKS_API_KEY out of the source tree — `.env` is gitignored.
    """
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# ─── Project Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOOKS_DIRS = [
    PROJECT_ROOT / "epubs",
    PROJECT_ROOT / "pdfs",
]
DATA_DIR = PROJECT_ROOT / "data"
COVERS_DIR = DATA_DIR / "covers"
CATALOG_DB_FILE = DATA_DIR / "catalog.db"      # store of record (SQLite)
CATALOG_FILE = DATA_DIR / "catalog.json"       # export only, never read back
ENRICHMENT_CACHE_FILE = DATA_DIR / "api_cache.json"
PROCESSING_LOG_FILE = DATA_DIR / "processing_log.json"
REPORT_FILE = DATA_DIR / "enrichment_report.json"

# Ensure directories exist
for _d in [DATA_DIR, COVERS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ─── Supported File Types ───────────────────────────────────────────────────────
# Only formats with a real extractor. `.mobi` used to be listed here and was
# scanned into near-empty records nothing could enrich.
SUPPORTED_EXTENSIONS = {".pdf", ".epub"}

# ─── Text Extraction ────────────────────────────────────────────────────────────
MAX_TEXT_EXCERPT_CHARS = _env_int("MAX_TEXT_EXCERPT_CHARS", 5000)   # reader preview
MAX_PAGES_TO_EXTRACT = _env_int("MAX_PAGES_TO_EXTRACT", 14)
MIN_TEXT_CHARS_FOR_HAS_TEXT = _env_int("MIN_TEXT_CHARS_FOR_HAS_TEXT", 100)

FRONT_MATTER_PAGES = _env_int("FRONT_MATTER_PAGES", 5)      # title/copyright pages
FRONT_MATTER_MAX_CHARS = _env_int("FRONT_MATTER_MAX_CHARS", 3000)
CONTENT_SAMPLE_MAX_CHARS = _env_int("CONTENT_SAMPLE_MAX_CHARS", 4000)
CONTENT_SAMPLE_MIN_PROSE_CHARS = _env_int("CONTENT_SAMPLE_MIN_PROSE_CHARS", 400)

# ─── API Configuration ──────────────────────────────────────────────────────────
OPENLIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
OPENLIBRARY_WORKS_BASE = "https://openlibrary.org"
OPENLIBRARY_BOOKS_URL = "https://openlibrary.org/api/books"
OPENLIBRARY_COVERS_URL = "https://covers.openlibrary.org"
GOOGLE_BOOKS_API_URL = "https://www.googleapis.com/books/v1/volumes"
GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY", "")  # Optional

API_REQUEST_TIMEOUT = _env_int("API_REQUEST_TIMEOUT", 15)          # seconds
API_USER_AGENT = _env_str(
    "API_USER_AGENT",
    "SmartBookLibrary/2.0 (personal catalog; +https://github.com/local/smart-book-library)",
)
API_MAX_RETRIES = _env_int("API_MAX_RETRIES", 3)
API_RETRY_BACKOFF = _env_float("API_RETRY_BACKOFF", 1.5)
# Per-host request budget (token bucket). Hosts are limited independently.
API_RATE_LIMIT_PER_SECOND = _env_float("API_RATE_LIMIT_PER_SECOND", 2.0)
API_RATE_LIMIT_BURST = _env_int("API_RATE_LIMIT_BURST", 3)
# Google Books' anonymous quota is small and per-IP: four workers hitting it in
# parallel earns a 429 on every call. Set GOOGLE_BOOKS_API_KEY to lift this.
API_RATE_LIMIT_BY_HOST = {
    "www.googleapis.com": (
        _env_float("GOOGLE_BOOKS_RATE", 1.0 if GOOGLE_BOOKS_API_KEY else 0.4),
        _env_int("GOOGLE_BOOKS_BURST", 2 if GOOGLE_BOOKS_API_KEY else 1),
    ),
}
# After a 429, stop sending to that host for this long instead of burning the
# remaining requests on guaranteed failures.
API_COOLDOWN_SECONDS = _env_float("API_COOLDOWN_SECONDS", 45.0)
# Cached "not found" answers expire; cached errors are never reused.
API_NEGATIVE_CACHE_TTL_DAYS = _env_int("API_NEGATIVE_CACHE_TTL_DAYS", 30)
# A source whose error rate exceeds this is reported as unhealthy.
API_ERROR_RATE_ALERT = _env_float("API_ERROR_RATE_ALERT", 0.20)

# ─── Verification Gate ──────────────────────────────────────────────────────────
MATCH_ACCEPT_THRESHOLD = _env_float("MATCH_ACCEPT_THRESHOLD", 0.75)
MATCH_PARTIAL_THRESHOLD = _env_float("MATCH_PARTIAL_THRESHOLD", 0.45)
# When a title is the ONLY evidence, both bars rise: measured over the known
# mismatches (0.17–0.53) versus genuine matches (0.85–1.00).
MATCH_TITLE_ONLY_ACCEPT = _env_float("MATCH_TITLE_ONLY_ACCEPT", 0.85)
MATCH_TITLE_ONLY_PARTIAL = _env_float("MATCH_TITLE_ONLY_PARTIAL", 0.60)
# Below this much evidence we do not title-search at all.
MIN_TITLE_EVIDENCE_TOKENS = _env_int("MIN_TITLE_EVIDENCE_TOKENS", 2)
MIN_TITLE_EVIDENCE_CHARS = _env_int("MIN_TITLE_EVIDENCE_CHARS", 8)

# ─── Embedding Configuration ────────────────────────────────────────────────────
EMBEDDING_MODEL = _env_str("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_MAX_INPUT_CHARS = _env_int("EMBEDDING_MAX_INPUT_CHARS", 4000)
EMBEDDING_BATCH_SIZE = _env_int("EMBEDDING_BATCH_SIZE", 32)

# ─── OCR Configuration ──────────────────────────────────────────────────────────
OCR_DPI = _env_int("OCR_DPI", 300)
OCR_LANGUAGE = _env_str("OCR_LANGUAGE", "eng")   # default; overridden per book
OCR_MAX_PAGES = _env_int("OCR_MAX_PAGES", 15)
# Script → tesseract language pack. Used only when the pack is installed.
OCR_LANGUAGE_BY_SCRIPT = {
    "arabic": "ara",
    "devanagari": "hin",
    "cyrillic": "rus",
    "latin": "eng",
}

# ─── LLM Configuration (Ollama) ─────────────────────────────────────────────────
OLLAMA_BASE_URL = _env_str("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = _env_str("OLLAMA_MODEL", "qwen3.5:4b")
OLLAMA_TIMEOUT = _env_int("OLLAMA_TIMEOUT", 180)
OLLAMA_MAX_INPUT_CHARS = _env_int("OLLAMA_MAX_INPUT_CHARS", 3000)
# Ollama serves one request at a time well; keep concurrency low.
LLM_MAX_CONCURRENCY = _env_int("LLM_MAX_CONCURRENCY", 1)

# ─── Cover Scraping (Playwright) ────────────────────────────────────────────────
COVER_SCRAPER_HEADLESS = _env_bool("COVER_SCRAPER_HEADLESS", True)

# ─── Duplicate Detection ────────────────────────────────────────────────────────
DUPLICATE_TITLE_THRESHOLD = _env_int("DUPLICATE_TITLE_THRESHOLD", 90)
# ISBNs below this confidence are not trusted to establish identity.
DUPLICATE_MIN_ISBN_CONFIDENCE = _env_float("DUPLICATE_MIN_ISBN_CONFIDENCE", 0.75)

# ─── Processing ─────────────────────────────────────────────────────────────────
BATCH_SIZE = _env_int("BATCH_SIZE", 20)          # progress reporting granularity
MAX_WORKERS = _env_int("MAX_WORKERS", 4)         # parallel per-book workers
SCHEMA_VERSION = "2.0"

# ─── Stage Versions ─────────────────────────────────────────────────────────────
# A stage re-runs for a record when its version here is newer than the version
# recorded on that record, or when the file's content hash changed. Bump a
# version after changing that stage's logic to re-run it on the next pass.
STAGE_VERSIONS = {
    "parse": 2,
    "extract": 2,
    "ocr": 1,
    "identify": 2,     # ISBN harvesting from filename / front matter / text
    "enrich": 3,       # evidence → candidates → verify → merge
    "analyze": 2,      # controlled vocabulary + normalised scoring
    "llm": 2,
    "embed": 2,        # embeds content_sample rather than front matter
}

# ─── Logging ────────────────────────────────────────────────────────────────────
LOG_LEVEL = _env_str("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
