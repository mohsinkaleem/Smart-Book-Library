"""
Catalog store — SQLite is the store of record.

The pipeline reads and writes `data/catalog.db` directly; the web server reads
the same file. There is no JSON round-trip and therefore no "which store is
current?" question. JSON is available as an export via
`CatalogStore.export_json`.

User-owned fields (rating, tags, favourite, reading status, progress, pinned
field corrections) live in `user_data` and are re-applied on every write, so a
pipeline run — or a full rebuild — cannot destroy them.
"""
import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .config import CATALOG_DB_FILE, CATALOG_FILE, PROCESSING_LOG_FILE, SCHEMA_VERSION
from .fts import fts_query as _fts_query
from .models import BookRecord
from .schema import BOOK_COLUMNS, PIPELINE_COLUMNS, USER_COLUMNS, ensure_schema

logger = logging.getLogger(__name__)

_JSON_FIELDS = {
    "authors", "source_ids", "themes", "categories", "subjects_raw", "keywords",
    "review_reasons", "rejected_candidates", "api_sources", "processing_errors",
    "user_tags", "field_sources", "stage_versions",
}
_BOOL_FIELDS = {"has_text", "ocr_required", "favorite", "needs_review"}
_ALL_COLUMNS = [name for name, _ in BOOK_COLUMNS]


def _dump(value) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _load(value, default):
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
    return parsed if isinstance(parsed, type(default)) else default


class CatalogStore:
    """SQLite-backed catalog. Thread-safe for the pipeline's worker pool."""

    def __init__(self, db_file: Path = CATALOG_DB_FILE):
        self.db_file = db_file
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_file), check_same_thread=False, timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        ensure_schema(self.conn)

    def close(self):
        with self._lock:
            self.conn.close()

    # ── row ↔ record ─────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> BookRecord:
        data = dict(row)
        for key in _JSON_FIELDS:
            if key in data:
                default = {} if key in ("field_sources", "stage_versions") else []
                data[key] = _load(data[key], default)
        for key in _BOOL_FIELDS:
            if key in data:
                data[key] = bool(data[key])
        data.pop("author_primary", None)
        return BookRecord.from_dict(data)

    @staticmethod
    def _record_values(record: BookRecord) -> dict:
        d = record.to_dict()
        values = {}
        for col in _ALL_COLUMNS:
            if col == "author_primary":
                authors = record.authors or []
                values[col] = authors[0] if authors else ""
                continue
            val = d.get(col)
            if col in _JSON_FIELDS:
                values[col] = _dump(val if val is not None else ([] if col not in ("field_sources", "stage_versions") else {}))
            elif col in _BOOL_FIELDS:
                values[col] = 1 if val else 0
            else:
                values[col] = val
        return values

    # ── user data ────────────────────────────────────────────────────────────

    def _user_row(self, book_id: str, file_path: str) -> Optional[sqlite3.Row]:
        row = self.conn.execute(
            "SELECT * FROM user_data WHERE book_id = ?", (book_id,)
        ).fetchone()
        if row is None and file_path:
            row = self.conn.execute(
                "SELECT * FROM user_data WHERE file_path = ?", (file_path,)
            ).fetchone()
        return row

    def _apply_user_data(self, record: BookRecord) -> dict:
        """Re-apply user-owned values and pinned corrections onto a record."""
        row = self._user_row(record.id, record.file_path)
        if row is None:
            return {col: getattr(record, col, None) for col in USER_COLUMNS}

        overrides = _load(row["field_overrides"], {})
        for name, entry in (overrides or {}).items():
            if not hasattr(record, name):
                continue
            value = entry.get("value") if isinstance(entry, dict) else entry
            if value in (None, "", [], {}):
                continue
            setattr(record, name, value)
            record.field_sources[name] = {
                "source": "user",
                "confidence": 1.0,
                "at": (entry.get("at") if isinstance(entry, dict) else None) or datetime.now().isoformat(timespec="seconds"),
            }

        return {
            "reading_status": row["reading_status"] or "not_started",
            "progress_percent": row["progress_percent"] or 0.0,
            "reader_position": row["reader_position"] or "",
            "user_rating": row["user_rating"],
            "user_tags": row["user_tags"] or "[]",
            "favorite": 1 if row["favorite"] else 0,
            "last_opened": row["last_opened"],
        }

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def upsert(self, record: BookRecord):
        """
        Insert or update a record.

        Only pipeline-owned columns are updated. User-owned columns are seeded
        from `user_data` on insert and left untouched on update.
        """
        with self._lock:
            record.last_processed = datetime.now().isoformat()
            record.set_defaults()

            existing = self.conn.execute(
                "SELECT id FROM books WHERE file_path = ?", (record.file_path,)
            ).fetchone()
            if existing and existing["id"] != record.id:
                # File content changed: the id moved. Carry user data across and
                # take the embeddings with it, or they orphan forever.
                self.conn.execute("DELETE FROM books WHERE file_path = ?", (record.file_path,))
                self.conn.execute(
                    "UPDATE OR IGNORE user_data SET book_id = ? WHERE book_id = ?",
                    (record.id, existing["id"]),
                )
                self.conn.execute(
                    "UPDATE OR REPLACE embeddings SET book_id = ? WHERE book_id = ?",
                    (record.id, existing["id"]),
                )

            user_values = self._apply_user_data(record)
            values = self._record_values(record)
            for col in USER_COLUMNS:
                if col == "user_tags":
                    raw = user_values.get(col)
                    values[col] = raw if isinstance(raw, str) else _dump(raw or [])
                else:
                    values[col] = user_values.get(col)

            placeholders = ", ".join("?" for _ in _ALL_COLUMNS)
            update_clause = ", ".join(
                f"{c} = excluded.{c}" for c in PIPELINE_COLUMNS if c != "id"
            )
            self.conn.execute(
                f"""INSERT INTO books ({", ".join(_ALL_COLUMNS)})
                    VALUES ({placeholders})
                    ON CONFLICT(id) DO UPDATE SET {update_clause}""",
                [values[c] for c in _ALL_COLUMNS],
            )
            self.conn.commit()

    def get(self, record_id: str) -> Optional[BookRecord]:
        row = self.conn.execute("SELECT * FROM books WHERE id = ?", (record_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def get_by_path(self, file_path: str) -> Optional[BookRecord]:
        row = self.conn.execute(
            "SELECT * FROM books WHERE file_path = ?", (str(file_path),)
        ).fetchone()
        return self._row_to_record(row) if row else None

    def all_records(self, include_missing: bool = False) -> list[BookRecord]:
        sql = "SELECT * FROM books"
        if not include_missing:
            sql += " WHERE status != 'missing'"
        return [self._row_to_record(r) for r in self.conn.execute(sql).fetchall()]

    def all_paths(self) -> set[str]:
        return {r["file_path"] for r in self.conn.execute("SELECT file_path FROM books")}

    def remove(self, record_id: str):
        with self._lock:
            self.conn.execute("DELETE FROM books WHERE id = ?", (record_id,))
            self.conn.commit()

    def mark_missing(self, file_paths: Iterable[str]) -> int:
        """Flag records whose files are gone rather than leaving phantoms."""
        paths = list(file_paths)
        if not paths:
            return 0
        with self._lock:
            self.conn.executemany(
                "UPDATE books SET status = 'missing' WHERE file_path = ?",
                [(p,) for p in paths],
            )
            self.conn.commit()
        return len(paths)

    def count(self, include_missing: bool = False) -> int:
        sql = "SELECT COUNT(*) AS c FROM books"
        if not include_missing:
            sql += " WHERE status != 'missing'"
        return self.conn.execute(sql).fetchone()["c"]

    def update_user_fields(self, book_id: str, fields: dict, file_path: str = None) -> dict:
        """Write user-owned fields (rating, progress, …) to `user_data`."""
        from .user_data import write_user_fields
        with self._lock:
            return write_user_fields(self.conn, book_id, fields, file_path)

    def user_field(self, book_id: str, name: str, file_path: str = None):
        """
        Read one user-owned value straight from `user_data`.

        The mirrored copy on `books` can be stale for a record built fresh this
        run, and `user_data` is the side that survives a full rebuild.
        """
        if name not in USER_COLUMNS:
            raise KeyError(f"'{name}' is not a user-owned field")
        with self._lock:
            row = self._user_row(book_id, file_path)
        return None if row is None else row[name]

    def pin_field(self, book_id: str, name: str, value, file_path: str = None) -> bool:
        """Pin a human correction so no future run can overwrite it."""
        from .user_data import pin_field
        with self._lock:
            return pin_field(self.conn, book_id, name, value, file_path)

    # ── embeddings ───────────────────────────────────────────────────────────

    def store_embedding(self, book_id: str, content: Optional[bytes], metadata: Optional[bytes]):
        with self._lock:
            self.conn.execute(
                """INSERT INTO embeddings (book_id, content_embedding, metadata_embedding)
                   VALUES (?, ?, ?)
                   ON CONFLICT(book_id) DO UPDATE SET
                       content_embedding = COALESCE(excluded.content_embedding, embeddings.content_embedding),
                       metadata_embedding = COALESCE(excluded.metadata_embedding, embeddings.metadata_embedding)""",
                (book_id, content, metadata),
            )
            self.conn.commit()

    def has_embedding(self, book_id: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM embeddings WHERE book_id = ? AND content_embedding IS NOT NULL",
            (book_id,),
        ).fetchone() is not None

    # ── search / stats / export ──────────────────────────────────────────────

    def search(self, query: str, limit: int = 200) -> list[BookRecord]:
        """Full-text search over the `books_fts` index, best match first."""
        term = _fts_query(query)
        if not term:
            return []
        try:
            rows = self.conn.execute(
                """SELECT b.* FROM books_fts f
                   JOIN books b ON b.rowid = f.rowid
                   WHERE books_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (term, limit),
            ).fetchall()
        except sqlite3.OperationalError as e:
            logger.debug(f"FTS query failed for {query!r}: {e}")
            return []
        return [self._row_to_record(r) for r in rows]

    def needs_review(self) -> list[BookRecord]:
        rows = self.conn.execute(
            "SELECT * FROM books WHERE needs_review = 1 ORDER BY match_score IS NULL DESC, match_score ASC"
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def compute_stats(self) -> dict:
        records = self.all_records()
        if not records:
            return {}
        from collections import Counter

        cats: Counter = Counter()
        for r in records:
            cats.update(r.categories)
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
            "with_embeddings": self.conn.execute(
                "SELECT COUNT(*) AS c FROM embeddings"
            ).fetchone()["c"],
            "duplicates": sum(1 for r in records if r.duplicate_of),
            "api_enriched": sum(1 for r in records if r.api_sources),
            "needs_review": sum(1 for r in records if r.needs_review),
            "verified_titles": sum(
                1 for r in records if r.field_source("title") in ("api_verified", "isbn_match", "user")
            ),
            "categories": dict(cats.most_common(20)),
            "total_size_mb": round(sum(r.size for r in records) / (1024 * 1024), 1),
        }

    def export_json(self, path: Path = CATALOG_FILE, include_text: bool = True) -> Path:
        """Export the catalog to JSON. This is an export, never a source."""
        records = self.all_records(include_missing=True)
        books = []
        for r in records:
            d = r.to_dict()
            # Vectors live in the `embeddings` table, not on the record.
            d.pop("embedding", None)
            d.pop("metadata_embedding", None)
            if not include_text:
                for key in ("text_excerpt", "front_matter", "content_sample"):
                    d[key] = ""
            books.append(d)
        payload = {
            "_schema_version": SCHEMA_VERSION,
            "_generated": datetime.now().isoformat(),
            "_total_books": len(books),
            "_stats": self.compute_stats(),
            "books": books,
        }
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        tmp.rename(path)
        logger.info(f"Exported {len(books)} records to {path}")
        return path

    def import_json(self, path: Path = CATALOG_FILE) -> int:
        """One-time import of a legacy catalog.json."""
        if not path.exists():
            return 0
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("books", []) if isinstance(data, dict) else data
        count = 0
        for item in items:
            try:
                record = BookRecord.from_dict(item)
                if not record.content_sha1:
                    record.content_sha1 = record.id
                self.upsert(record)
                count += 1
            except Exception as e:  # pragma: no cover - defensive
                logger.warning(f"Failed to import record: {e}")
        return count


class ProcessingLog:
    """Tracks processing history and errors (small JSON file)."""

    def __init__(self, log_file: Path = PROCESSING_LOG_FILE):
        self.log_file = log_file
        self._entries: list[dict] = []
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
            json.dump(self._entries[-200:], f, indent=2, ensure_ascii=False)

    def log(self, event: str, details: dict = None):
        self._entries.append({
            "timestamp": datetime.now().isoformat(),
            "event": event,
            "details": details or {},
        })
