"""
Migration script: JSON catalog → SQLite database.

Usage: python -m server.migrate
"""
import logging
import sys
import numpy as np
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from catalog.database import CatalogDatabase
from server.db import BookDatabase
from server.config import DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def migrate():
    """Migrate catalog.json to SQLite."""
    logger.info("Loading catalog from JSON...")
    catalog = CatalogDatabase()
    records = catalog.all_records()
    logger.info(f"Found {len(records)} records in catalog.json")

    if not records:
        logger.warning("No records found. Nothing to migrate.")
        return

    # Remove existing DB for clean migration
    if DB_PATH.exists():
        DB_PATH.unlink()
        logger.info(f"Removed existing {DB_PATH}")

    db = BookDatabase(DB_PATH)
    logger.info("Created SQLite database with schema")

    migrated = 0
    embedding_count = 0
    for record in records:
        try:
            book_dict = record.to_dict()
            db.upsert_book(book_dict)

            # Store embeddings as blobs
            content_emb = None
            metadata_emb = None
            if record.embedding:
                content_emb = np.array(record.embedding, dtype=np.float32).tobytes()
            if record.metadata_embedding:
                metadata_emb = np.array(record.metadata_embedding, dtype=np.float32).tobytes()
            if content_emb or metadata_emb:
                db.store_embedding(record.id, content_emb, metadata_emb)
                embedding_count += 1

            migrated += 1
        except Exception as e:
            logger.error(f"Failed to migrate {record.file_name}: {e}")

    # Verify
    count = db.get_book_count()
    logger.info(f"Migration complete: {migrated}/{len(records)} books migrated to SQLite")
    logger.info(f"Embeddings stored: {embedding_count}")
    logger.info(f"Verification: {count} books in SQLite")
    db.close()


if __name__ == "__main__":
    migrate()
