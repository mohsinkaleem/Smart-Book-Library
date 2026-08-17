"""Server configuration."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "catalog.db"
COVERS_DIR = DATA_DIR / "covers"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

# Pagination
DEFAULT_PAGE_SIZE = 48
MAX_PAGE_SIZE = 200
