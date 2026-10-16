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

# ── Passage index (Part 1) ──
# Full extracted text lives on disk, not in a `books` column: 340 MB of prose
# in a row that every list query reads would make the catalog unusable.
TEXT_DIR = DATA_DIR / "text"
# One vector per chunk, float16 on disk (half the file), upcast to float32
# once at load. Never matmul in float16 — NumPy has no float16 BLAS path and
# upcasts elementwise on every query, which measures 32x *slower*.
CHUNK_VECTORS_FILE = DATA_DIR / "chunk_vectors.npy"

# Ensure directories exist
for _d in [DATA_DIR, COVERS_DIR, TEXT_DIR]:
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
# `bge-small-en-v1.5` over `all-MiniLM-L6-v2`: same 384 dimensions, so every
# stored blob and every matmul is unchanged in shape, but a 512-token sequence
# limit instead of 256 — MiniLM truncated a 4 000-character content sample at
# roughly its halfway mark and embedded only the first half.
#
# English-only is deliberate. 575 of 618 books are English and 4 are Arabic; a
# multilingual model would cost quality on 93% of the library to serve 0.6%.
EMBEDDING_MODEL = _env_str("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

# bge is an *asymmetric* retrieval model: it wants this instruction on short
# search queries and on nothing else. Passage-to-passage similarity — "find
# books whose prose resembles this paragraph" — is symmetric and must be
# encoded without it. Applying it in both directions quietly degrades results
# rather than failing, which is why the two paths are separate functions in
# `catalog.embeddings` instead of a boolean argument.
EMBEDDING_QUERY_PREFIX = _env_str(
    "EMBEDDING_QUERY_PREFIX",
    "Represent this sentence for searching relevant passages: ",
)
EMBEDDING_MAX_INPUT_CHARS = _env_int("EMBEDDING_MAX_INPUT_CHARS", 4000)
EMBEDDING_BATCH_SIZE = _env_int("EMBEDDING_BATCH_SIZE", 32)

# ─── Passage Index / Chunking ───────────────────────────────────────────────────
# Sized to sit under bge's 512-token limit (~375 tokens at 4 chars/token) while
# still holding a complete argument. The overlap keeps a thought that straddles
# a chunk boundary retrievable from both sides; the stride is the difference.
CHUNK_TARGET_CHARS = _env_int("CHUNK_TARGET_CHARS", 1500)
CHUNK_OVERLAP_CHARS = _env_int("CHUNK_OVERLAP_CHARS", 250)
# Below this a chunk is a stray heading or a page number, not a passage.
CHUNK_MIN_CHARS = _env_int("CHUNK_MIN_CHARS", 200)
# The needle stored with an EPUB chunk so the reader can locate it in a
# re-rendered document. Same role as `annotations.anchor_text`.
CHUNK_ANCHOR_CHARS = _env_int("CHUNK_ANCHOR_CHARS", 60)

# Full-text extraction for the passage index lifts `MAX_PAGES_TO_EXTRACT` — that
# cap exists for the *metadata* pipeline, which only ever wanted the front of
# the book. 0 means no cap.
FULL_TEXT_MAX_PAGES = _env_int("FULL_TEXT_MAX_PAGES", 0)

# Reciprocal Rank Fusion constant. RRF needs no score normalisation between the
# dense and BM25 rankings, which is the usual source of hybrid-search bugs.
RRF_K = _env_int("RRF_K", 60)

# Cross-encoder reranking of the fused top-N (§1.11 phase 2). Off by default:
# it is a large precision gain for ~50 ms, but the model is an ~80 MB download
# on first use, so opting in is the user's call rather than a surprise at the
# first query. When the model will not load, search falls back to the fused
# ranking rather than failing.
PASSAGE_RERANK = _env_bool("PASSAGE_RERANK", False)
PASSAGE_RERANK_MODEL = _env_str("PASSAGE_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
PASSAGE_RERANK_CANDIDATES = _env_int("PASSAGE_RERANK_CANDIDATES", 50)

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

# ─── Covers ─────────────────────────────────────────────────────────────────────
COVER_SCRAPER_HEADLESS = _env_bool("COVER_SCRAPER_HEADLESS", True)
# Rasterising page 1 as a last-resort cover. 150 DPI puts a US Letter page at
# roughly 1275x1650, which `covers.save_cover` thumbnails to 800x1200 — so the
# title stays legible in the grid without decoding an OCR-sized bitmap.
COVER_RENDER_DPI = _env_int("COVER_RENDER_DPI", 150)

# ─── Duplicate Detection ────────────────────────────────────────────────────────
DUPLICATE_TITLE_THRESHOLD = _env_int("DUPLICATE_TITLE_THRESHOLD", 90)
# ISBNs below this confidence are not trusted to establish identity.
DUPLICATE_MIN_ISBN_CONFIDENCE = _env_float("DUPLICATE_MIN_ISBN_CONFIDENCE", 0.75)

# ─── Processing ─────────────────────────────────────────────────────────────────
BATCH_SIZE = _env_int("BATCH_SIZE", 20)          # progress reporting granularity
MAX_WORKERS = _env_int("MAX_WORKERS", 4)         # parallel per-book workers
SCHEMA_VERSION = "2.0"

# ─── Stage Versions ─────────────────────────────────────────────────────────────
# Work re-runs for a record when the version here is newer than the version
# recorded on that record, or when the file's content hash changed. Bump a
# version after changing that code to re-run it on the next pass.
#
# These are *units of staleness*, not stages. `parse`, `extract`, `ocr`,
# `identify` and `enrich` used to carry five independent version numbers, but
# the pipeline dragged all five along whenever any one of them was stale —
# they write the same bibliographic fields and settle conflicts by
# SOURCE_RANK, so re-running one without the others drops values nothing
# restores. Five numbers that always moved together are one number; collapsing
# them also removes the cohort rule that existed only to re-couple them.
#
# The numbering restarts here: every record in an existing catalog predates
# the `metadata` key and is stale on the next run either way.
# `cover` is the one unit that is not a per-book stage: covers are filled by a
# closing stage, because a rendered page 1 may only be tried once the embedded
# images, the providers and the scraper have all failed to produce a jacket.
# What it records is that the attempt was *made* — so a book whose page 1 is a
# blank title page is not re-rendered on every run.
STAGE_VERSIONS = {
    "metadata": 1,     # parse + extract + ocr + identify + enrich
    "analyze": 2,      # controlled vocabulary + normalised scoring
    "llm": 2,
    "embed": 3,        # bge-small-en-v1.5; vectors from other models are not comparable
    "chunk": 1,        # full-text extraction + passage chunking (Part 1)
    "cover": 2,        # last-resort cover rendered from page 1 of a PDF
}

# ─── Logging ────────────────────────────────────────────────────────────────────
LOG_LEVEL = _env_str("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
