"""
JSON database management for the book catalog.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import CATALOG_FILE, PROCESSING_LOG_FILE, SCHEMA_VERSION
from .models import BookRecord

logger = logging.getLogger(__name__)


class CatalogDatabase:
    """Manages the book catalog JSON database."""

    def __init__(self, catalog_file: Path = CATALOG_FILE):
        self.catalog_file = catalog_file
        self._records: dict[str, BookRecord] = {}  # id -> BookRecord
        self._load()

    def _load(self):
        """Load catalog from JSON file."""
        if self.catalog_file.exists():
            try:
                with open(self.catalog_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                catalog_data = data.get("books", []) if isinstance(data, dict) else data
                for item in catalog_data:
                    try:
                        record = BookRecord.from_dict(item)
                        if record.id:
                            self._records[record.id] = record
                        elif record.file_path:
                            self._records[record.file_path] = record
                    except Exception as e:
                        logger.warning(f"Failed to load record: {e}")

                logger.info(f"Loaded {len(self._records)} records from catalog")
            except Exception as e:
                logger.error(f"Failed to load catalog: {e}")
                self._records = {}
        else:
            logger.info("No existing catalog found, starting fresh")

    def save(self):
        """Save catalog to JSON file."""
        catalog = {
            "_schema_version": SCHEMA_VERSION,
            "_generated": datetime.now().isoformat(),
            "_total_books": len(self._records),
            "_stats": self._compute_stats(),
            "books": [r.to_dict() for r in self._records.values()],
        }

        # Write atomically (write to temp, then rename)
        tmp_file = self.catalog_file.with_suffix(".json.tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(catalog, f, indent=2, ensure_ascii=False)
        tmp_file.rename(self.catalog_file)

        logger.info(f"Saved {len(self._records)} records to {self.catalog_file}")

    def get(self, record_id: str) -> Optional[BookRecord]:
        """Get a record by ID."""
        return self._records.get(record_id)

    def get_by_path(self, file_path: str) -> Optional[BookRecord]:
        """Get a record by file path."""
        for record in self._records.values():
            if record.file_path == file_path:
                return record
        return None

    def upsert(self, record: BookRecord):
        """Insert or update a record."""
        key = record.id or record.file_path
        if key:
            record.last_processed = datetime.now().isoformat()
            self._records[key] = record

    def remove(self, record_id: str):
        """Remove a record by ID."""
        self._records.pop(record_id, None)

    def all_records(self) -> list[BookRecord]:
        """Get all records."""
        return list(self._records.values())

    def count(self) -> int:
        """Get total record count."""
        return len(self._records)

    def has_record(self, record_id: str) -> bool:
        """Check if a record exists."""
        return record_id in self._records

    def search(self, query: str) -> list[BookRecord]:
        """Simple text search across title, authors, description."""
        query_lower = query.lower()
        results = []
        for record in self._records.values():
            searchable = " ".join([
                record.title,
                " ".join(record.authors),
                record.description,
                " ".join(record.categories),
                " ".join(record.themes),
                " ".join(record.keywords),
            ]).lower()
            if query_lower in searchable:
                results.append(record)
        return results

    def get_by_category(self, category: str) -> list[BookRecord]:
        """Get all books in a category."""
        cat_lower = category.lower()
        return [
            r for r in self._records.values()
            if any(cat_lower in c.lower() for c in r.categories)
        ]

    def get_duplicates(self) -> list[BookRecord]:
        """Get all records marked as duplicates."""
        return [r for r in self._records.values() if r.duplicate_of]

    def _compute_stats(self) -> dict:
        """Compute catalog statistics."""
        records = list(self._records.values())
        if not records:
            return {}

        return {
            "total_books": len(records),
            "by_type": {
                "pdf": sum(1 for r in records if r.file_type == "pdf"),
                "epub": sum(1 for r in records if r.file_type == "epub"),
                "other": sum(1 for r in records if r.file_type not in ("pdf", "epub")),
            },
            "with_text": sum(1 for r in records if r.has_text),
            "ocr_required": sum(1 for r in records if r.ocr_required),
            "with_cover": sum(1 for r in records if r.cover_path),
            "with_description": sum(1 for r in records if r.description),
            "with_isbn": sum(1 for r in records if r.isbn_13 or r.isbn_10),
            "with_embeddings": sum(1 for r in records if r.embedding),
            "duplicates": sum(1 for r in records if r.duplicate_of),
            "api_enriched": sum(1 for r in records if r.api_sources),
            "categories": _count_unique(r.categories for r in records),
            "total_size_mb": round(sum(r.size for r in records) / (1024 * 1024), 1),
        }


def _count_unique(lists_of_items) -> dict:
    """Count unique items across lists."""
    from collections import Counter
    counter = Counter()
    for items in lists_of_items:
        counter.update(items)
    return dict(counter.most_common(20))


class ProcessingLog:
    """Tracks processing history and errors."""

    def __init__(self, log_file: Path = PROCESSING_LOG_FILE):
        self.log_file = log_file
        self._entries = []
        self._load()

    def _load(self):
        if self.log_file.exists():
            try:
                with open(self.log_file, "r", encoding="utf-8") as f:
                    self._entries = json.load(f)
            except Exception:
                self._entries = []

    def save(self):
        with open(self.log_file, "w", encoding="utf-8") as f:
            json.dump(self._entries, f, indent=2, ensure_ascii=False)

    def log(self, event: str, details: dict = None):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event,
            "details": details or {},
        }
        self._entries.append(entry)

    def get_last_run(self) -> Optional[dict]:
        if self._entries:
            return self._entries[-1]
        return None
