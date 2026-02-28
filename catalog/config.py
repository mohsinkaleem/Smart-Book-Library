"""
Configuration for the book catalog enrichment pipeline.
"""
from pathlib import Path
import os

# ─── Project Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOOKS_DIRS = [
    PROJECT_ROOT / "epubs",
    PROJECT_ROOT / "pdfs",
]
DATA_DIR = PROJECT_ROOT / "data"
COVERS_DIR = DATA_DIR / "covers"
TEXT_EXCERPTS_DIR = DATA_DIR / "text_excerpts"
CATALOG_FILE = DATA_DIR / "catalog.json"
ENRICHMENT_CACHE_FILE = DATA_DIR / "api_cache.json"
PROCESSING_LOG_FILE = DATA_DIR / "processing_log.json"

# Ensure directories exist
for d in [DATA_DIR, COVERS_DIR, TEXT_EXCERPTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── Supported File Types ───────────────────────────────────────────────────────
SUPPORTED_EXTENSIONS = {".pdf", ".epub", ".mobi"}

# ─── Text Extraction ────────────────────────────────────────────────────────────
MAX_TEXT_EXCERPT_CHARS = 5000       # ~2 pages of text for preview/embedding
MAX_PAGES_TO_EXTRACT = 10          # First N pages to try extracting text from
MIN_TEXT_CHARS_FOR_HAS_TEXT = 100   # Below this = likely image-based/scanned

# ─── API Configuration ──────────────────────────────────────────────────────────
OPENLIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
OPENLIBRARY_WORKS_URL = "https://openlibrary.org/works"
OPENLIBRARY_BOOKS_URL = "https://openlibrary.org/api/books"
OPENLIBRARY_COVERS_URL = "https://covers.openlibrary.org"
GOOGLE_BOOKS_API_URL = "https://www.googleapis.com/books/v1/volumes"
GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY", "")  # Optional

API_REQUEST_TIMEOUT = 15  # seconds
API_RATE_LIMIT_DELAY = 1.0  # seconds between API calls (be nice to servers)

# ─── Embedding Configuration ────────────────────────────────────────────────────
EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # sentence-transformers model
EMBEDDING_DIMENSION = 384               # Dimension for all-MiniLM-L6-v2

# ─── OCR Configuration ──────────────────────────────────────────────────────────
OCR_ENABLED = True                  # Enable OCR for image-based PDFs
OCR_DPI = 300                       # DPI for pdf2image conversion
OCR_LANGUAGE = "eng"                # Tesseract language(s), e.g. "eng+ara"
OCR_MAX_PAGES = 15                  # Max pages to OCR (slow process)

# ─── LLM Configuration (Ollama) ─────────────────────────────────────────────────
LLM_ENABLED = True                  # Enable LLM-powered enrichment
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2"           # Change to your installed model
OLLAMA_TIMEOUT = 120                # Seconds to wait for LLM response
OLLAMA_MAX_INPUT_CHARS = 3000       # Max chars sent to LLM

# ─── Cover Scraping (Playwright) ────────────────────────────────────────────────
COVER_SCRAPER_ENABLED = True        # Enable Playwright cover fallback
COVER_SCRAPER_HEADLESS = True       # Run browser headlessly

# ─── Duplicate Detection ────────────────────────────────────────────────────────
DUPLICATE_TITLE_THRESHOLD = 85   # fuzzy match score (0-100)
DUPLICATE_SHA_CHECK = True       # Also check SHA1 for exact file duplicates

# ─── Processing ─────────────────────────────────────────────────────────────────
BATCH_SIZE = 20                  # Process N books at a time for progress reporting
MAX_WORKERS = 4                  # Parallel workers for file processing
SCHEMA_VERSION = "1.0"

# ─── Logging ────────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
