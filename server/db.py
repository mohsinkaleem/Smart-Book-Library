"""
SQLite database wrapper with FTS5 full-text search.
"""
import json
import sqlite3
import logging
from pathlib import Path
from typing import Any, Optional

from .config import DB_PATH

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS books (
    id                TEXT PRIMARY KEY,
    file_path         TEXT UNIQUE NOT NULL,
    file_name         TEXT NOT NULL,
    file_type         TEXT NOT NULL,
    size              INTEGER DEFAULT 0,
    title             TEXT DEFAULT '',
    original_title_meta TEXT DEFAULT '',
    authors           TEXT DEFAULT '[]',
    publisher         TEXT DEFAULT '',
    publication_year  INTEGER,
    language          TEXT DEFAULT '',
    page_count        INTEGER,
    isbn_10           TEXT DEFAULT '',
    isbn_13           TEXT DEFAULT '',
    description       TEXT DEFAULT '',
    summary           TEXT DEFAULT '',
    themes            TEXT DEFAULT '[]',
    categories        TEXT DEFAULT '[]',
    keywords          TEXT DEFAULT '[]',
    cover_path        TEXT DEFAULT '',
    text_excerpt      TEXT DEFAULT '',
    has_text          INTEGER DEFAULT 1,
    ocr_required      INTEGER DEFAULT 0,
    api_sources       TEXT DEFAULT '[]',
    date_added        TEXT DEFAULT '',
    last_opened       TEXT,
    reading_status    TEXT DEFAULT 'not_started',
    progress_percent  REAL DEFAULT 0,
    user_rating       REAL,
    user_tags         TEXT DEFAULT '[]',
    favorite          INTEGER DEFAULT 0,
    duplicate_of      TEXT,
    processing_errors TEXT DEFAULT '[]',
    last_processed    TEXT DEFAULT '',
    author_primary    TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_books_file_type ON books(file_type);
CREATE INDEX IF NOT EXISTS idx_books_reading_status ON books(reading_status);
CREATE INDEX IF NOT EXISTS idx_books_favorite ON books(favorite);
CREATE INDEX IF NOT EXISTS idx_books_publication_year ON books(publication_year);
CREATE INDEX IF NOT EXISTS idx_books_language ON books(language);
CREATE INDEX IF NOT EXISTS idx_books_user_rating ON books(user_rating);
CREATE INDEX IF NOT EXISTS idx_books_duplicate ON books(duplicate_of);
CREATE INDEX IF NOT EXISTS idx_books_title ON books(title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_books_author_primary ON books(author_primary COLLATE NOCASE);

CREATE VIRTUAL TABLE IF NOT EXISTS books_fts USING fts5(
    title,
    authors,
    description,
    summary,
    themes,
    categories,
    keywords,
    publisher,
    content='books',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS books_ai AFTER INSERT ON books BEGIN
    INSERT INTO books_fts(rowid, title, authors, description, summary, themes, categories, keywords, publisher)
    VALUES (new.rowid, new.title, new.authors, new.description, new.summary, new.themes, new.categories, new.keywords, new.publisher);
END;

CREATE TRIGGER IF NOT EXISTS books_ad AFTER DELETE ON books BEGIN
    INSERT INTO books_fts(books_fts, rowid, title, authors, description, summary, themes, categories, keywords, publisher)
    VALUES ('delete', old.rowid, old.title, old.authors, old.description, old.summary, old.themes, old.categories, old.keywords, old.publisher);
END;

CREATE TRIGGER IF NOT EXISTS books_au AFTER UPDATE ON books BEGIN
    INSERT INTO books_fts(books_fts, rowid, title, authors, description, summary, themes, categories, keywords, publisher)
    VALUES ('delete', old.rowid, old.title, old.authors, old.description, old.summary, old.themes, old.categories, old.keywords, old.publisher);
    INSERT INTO books_fts(rowid, title, authors, description, summary, themes, categories, keywords, publisher)
    VALUES (new.rowid, new.title, new.authors, new.description, new.summary, new.themes, new.categories, new.keywords, new.publisher);
END;

CREATE TABLE IF NOT EXISTS embeddings (
    book_id            TEXT PRIMARY KEY REFERENCES books(id),
    content_embedding  BLOB,
    metadata_embedding BLOB
);
"""


def _json_field(val: Any) -> str:
    """Convert a list/dict to JSON string for storage."""
    if isinstance(val, (list, dict)):
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, str):
        return val
    return json.dumps(val or [], ensure_ascii=False)


def _parse_json_field(val: Optional[str]) -> list:
    """Parse a JSON string field back to a list."""
    if not val:
        return []
    try:
        result = json.loads(val)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


class BookDatabase:
    """SQLite database for the book catalog with FTS5 search."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self):
        """Create tables and indexes."""
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ── Book CRUD ────────────────────────────────────────────────────────

    def upsert_book(self, book: dict):
        """Insert or replace a book record."""
        authors = book.get("authors", [])
        author_primary = authors[0] if isinstance(authors, list) and authors else ""

        self.conn.execute("""
            INSERT OR REPLACE INTO books (
                id, file_path, file_name, file_type, size,
                title, original_title_meta, authors, publisher, publication_year,
                language, page_count, isbn_10, isbn_13,
                description, summary, themes, categories, keywords,
                cover_path, text_excerpt,
                has_text, ocr_required, api_sources,
                date_added, last_opened, reading_status, progress_percent,
                user_rating, user_tags, favorite,
                duplicate_of, processing_errors, last_processed,
                author_primary
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?
            )
        """, (
            book.get("id", ""),
            book.get("file_path", ""),
            book.get("file_name", ""),
            book.get("file_type", ""),
            book.get("size", 0),
            book.get("title", ""),
            book.get("original_title_meta", ""),
            _json_field(book.get("authors", [])),
            book.get("publisher", ""),
            book.get("publication_year"),
            book.get("language", ""),
            book.get("page_count"),
            book.get("isbn_10", ""),
            book.get("isbn_13", ""),
            book.get("description", ""),
            book.get("summary", ""),
            _json_field(book.get("themes", [])),
            _json_field(book.get("categories", [])),
            _json_field(book.get("keywords", [])),
            book.get("cover_path", ""),
            book.get("text_excerpt", ""),
            1 if book.get("has_text", True) else 0,
            1 if book.get("ocr_required", False) else 0,
            _json_field(book.get("api_sources", [])),
            book.get("date_added", ""),
            book.get("last_opened"),
            book.get("reading_status", "not_started"),
            book.get("progress_percent", 0),
            book.get("user_rating"),
            _json_field(book.get("user_tags", [])),
            1 if book.get("favorite", False) else 0,
            book.get("duplicate_of"),
            _json_field(book.get("processing_errors", [])),
            book.get("last_processed", ""),
            author_primary,
        ))
        self.conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a SQLite Row to a book dict with parsed JSON fields."""
        d = dict(row)
        # Parse JSON array fields
        for field in ("authors", "themes", "categories", "keywords",
                      "api_sources", "user_tags", "processing_errors"):
            d[field] = _parse_json_field(d.get(field))
        # Convert int booleans
        d["has_text"] = bool(d.get("has_text", 1))
        d["ocr_required"] = bool(d.get("ocr_required", 0))
        d["favorite"] = bool(d.get("favorite", 0))
        # Add computed fields
        d["has_cover"] = bool(d.get("cover_path"))
        d["has_description"] = bool(d.get("description"))
        # Cover URL
        if d.get("cover_path"):
            cover_name = Path(d["cover_path"]).name
            d["cover_url"] = f"/covers/{cover_name}"
        else:
            d["cover_url"] = None
        return d

    def get_book(self, book_id: str) -> Optional[dict]:
        """Get a single book by ID."""
        row = self.conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def get_books(
        self,
        page: int = 1,
        per_page: int = 48,
        sort: str = "title",
        order: str = "asc",
        file_type: Optional[str] = None,
        category: Optional[str] = None,
        theme: Optional[str] = None,
        language: Optional[str] = None,
        reading_status: Optional[str] = None,
        has_cover: Optional[bool] = None,
        has_description: Optional[bool] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        rating_min: Optional[int] = None,
        favorite: Optional[bool] = None,
        author: Optional[str] = None,
        tag: Optional[str] = None,
        search: Optional[str] = None,
    ) -> dict:
        """Get paginated, sorted, filtered book list."""
        where_clauses = []
        params = []

        if file_type:
            where_clauses.append("file_type = ?")
            params.append(file_type)
        if category:
            where_clauses.append("categories LIKE ?")
            params.append(f'%"{category}"%')
        if theme:
            where_clauses.append("themes LIKE ?")
            params.append(f'%"{theme}"%')
        if language:
            where_clauses.append("language = ?")
            params.append(language)
        if reading_status:
            where_clauses.append("reading_status = ?")
            params.append(reading_status)
        if has_cover is True:
            where_clauses.append("cover_path IS NOT NULL AND cover_path != ''")
        elif has_cover is False:
            where_clauses.append("(cover_path IS NULL OR cover_path = '')")
        if has_description is True:
            where_clauses.append("description IS NOT NULL AND description != ''")
        if year_min is not None:
            where_clauses.append("publication_year >= ?")
            params.append(year_min)
        if year_max is not None:
            where_clauses.append("publication_year <= ?")
            params.append(year_max)
        if rating_min is not None:
            where_clauses.append("user_rating >= ?")
            params.append(rating_min)
        if favorite is True:
            where_clauses.append("favorite = 1")
        if author:
            where_clauses.append("authors LIKE ?")
            params.append(f'%"{author}"%')
        if tag:
            where_clauses.append("user_tags LIKE ?")
            params.append(f'%"{tag}"%')
        if search:
            where_clauses.append("id IN (SELECT books.id FROM books_fts JOIN books ON books.rowid = books_fts.rowid WHERE books_fts MATCH ?)")
            params.append(search)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        # Sort mapping
        sort_columns = {
            "title": "title COLLATE NOCASE",
            "author": "author_primary COLLATE NOCASE",
            "date_added": "date_added",
            "year": "publication_year",
            "size": "size",
            "pages": "page_count",
            "rating": "user_rating",
            "last_opened": "last_opened",
        }
        sort_col = sort_columns.get(sort, "title COLLATE NOCASE")
        sort_dir = "DESC" if order.lower() == "desc" else "ASC"

        # Count total
        count_row = self.conn.execute(
            f"SELECT COUNT(*) as cnt FROM books WHERE {where_sql}", params
        ).fetchone()
        total = count_row["cnt"]

        # Fetch page
        offset = (page - 1) * per_page
        rows = self.conn.execute(
            f"SELECT * FROM books WHERE {where_sql} ORDER BY {sort_col} {sort_dir} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()

        pages = max(1, (total + per_page - 1) // per_page)
        return {
            "items": [self._row_to_dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }

    def update_user_fields(self, book_id: str, fields: dict) -> Optional[dict]:
        """Update user-modifiable fields (rating, tags, favorite, reading_status, progress)."""
        allowed = {"user_rating", "user_tags", "favorite", "reading_status", "progress_percent"}
        updates = {}
        for key, val in fields.items():
            if key in allowed:
                if key == "user_tags":
                    updates[key] = _json_field(val)
                elif key == "favorite":
                    updates[key] = 1 if val else 0
                else:
                    updates[key] = val

        if not updates:
            return None

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        params = list(updates.values()) + [book_id]
        self.conn.execute(f"UPDATE books SET {set_clause} WHERE id = ?", params)
        self.conn.commit()
        return self.get_book(book_id)

    # ── Search ───────────────────────────────────────────────────────────

    def search_fts(self, query: str, page: int = 1, per_page: int = 48, **filters) -> dict:
        """Full-text search using FTS5."""
        # Clean query for FTS5
        clean_q = query.strip()
        if not clean_q:
            return self.get_books(page=page, per_page=per_page, **filters)

        # Build filter WHERE clauses on the books table
        where_clauses = []
        params: list[Any] = []
        self._apply_filters(where_clauses, params, filters)
        filter_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        # FTS5 search
        fts_query = self._build_fts_query(clean_q)

        count_sql = f"""
            SELECT COUNT(*) as cnt FROM books_fts
            JOIN books ON books.rowid = books_fts.rowid
            WHERE books_fts MATCH ? AND {filter_sql}
        """
        count_row = self.conn.execute(count_sql, [fts_query] + params).fetchone()
        total = count_row["cnt"]

        offset = (page - 1) * per_page
        search_sql = f"""
            SELECT books.*, bm25(books_fts) as score
            FROM books_fts
            JOIN books ON books.rowid = books_fts.rowid
            WHERE books_fts MATCH ? AND {filter_sql}
            ORDER BY score
            LIMIT ? OFFSET ?
        """
        rows = self.conn.execute(search_sql, [fts_query] + params + [per_page, offset]).fetchall()

        pages = max(1, (total + per_page - 1) // per_page)
        items = []
        for r in rows:
            d = self._row_to_dict(r)
            d["_score"] = r["score"]
            items.append(d)

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }

    def suggest(self, query: str, limit: int = 8) -> list[dict]:
        """Autocomplete suggestions from title."""
        if not query.strip():
            return []
        fts_q = f'title : {query.strip()}*'
        rows = self.conn.execute("""
            SELECT books.id, books.title, books.author_primary
            FROM books_fts
            JOIN books ON books.rowid = books_fts.rowid
            WHERE books_fts MATCH ?
            LIMIT ?
        """, (fts_q, limit)).fetchall()
        return [{"id": r["id"], "title": r["title"], "author": r["author_primary"]} for r in rows]

    def _build_fts_query(self, query: str) -> str:
        """Build an FTS5 query string from user input."""
        # If it looks like a phrase query, keep as-is
        if '"' in query:
            return query
        # Add prefix matching to each term
        terms = query.split()
        return " ".join(f'"{t}"*' if len(t) > 2 else f'"{t}"' for t in terms)

    def _apply_filters(self, where_clauses: list, params: list, filters: dict):
        """Apply filter clauses from kwargs."""
        if filters.get("file_type"):
            where_clauses.append("books.file_type = ?")
            params.append(filters["file_type"])
        if filters.get("category"):
            where_clauses.append("books.categories LIKE ?")
            params.append(f'%"{filters["category"]}"%')
        if filters.get("theme"):
            where_clauses.append("books.themes LIKE ?")
            params.append(f'%"{filters["theme"]}"%')
        if filters.get("language"):
            where_clauses.append("books.language = ?")
            params.append(filters["language"])
        if filters.get("reading_status"):
            where_clauses.append("books.reading_status = ?")
            params.append(filters["reading_status"])
        if filters.get("favorite"):
            where_clauses.append("books.favorite = 1")

    # ── Filter Facets ────────────────────────────────────────────────────

    def get_filter_facets(self) -> dict:
        """Get all filter facet values with counts."""
        facets = {}

        # Categories
        facets["categories"] = self._count_json_array_field("categories")
        # Themes
        facets["themes"] = self._count_json_array_field("themes")
        # Authors
        facets["authors"] = self._count_json_array_field("authors")
        # Languages
        rows = self.conn.execute(
            "SELECT language, COUNT(*) as cnt FROM books WHERE language != '' GROUP BY language ORDER BY cnt DESC"
        ).fetchall()
        facets["languages"] = [{"name": r["language"], "count": r["cnt"]} for r in rows]
        # File types
        rows = self.conn.execute(
            "SELECT file_type, COUNT(*) as cnt FROM books GROUP BY file_type ORDER BY cnt DESC"
        ).fetchall()
        facets["file_types"] = [{"name": r["file_type"], "count": r["cnt"]} for r in rows]
        # Year range
        row = self.conn.execute(
            "SELECT MIN(publication_year) as min_year, MAX(publication_year) as max_year FROM books WHERE publication_year IS NOT NULL"
        ).fetchone()
        facets["years"] = {"min": row["min_year"], "max": row["max_year"]} if row else {"min": None, "max": None}
        # Reading status
        rows = self.conn.execute(
            "SELECT reading_status, COUNT(*) as cnt FROM books GROUP BY reading_status ORDER BY cnt DESC"
        ).fetchall()
        facets["reading_statuses"] = [{"name": r["reading_status"], "count": r["cnt"]} for r in rows]
        # Tags
        facets["tags"] = self._count_json_array_field("user_tags")

        return facets

    def _count_json_array_field(self, field_name: str) -> list[dict]:
        """Count occurrences in a JSON array field."""
        rows = self.conn.execute(f"SELECT {field_name} FROM books").fetchall()
        from collections import Counter
        counter: Counter = Counter()
        for row in rows:
            items = _parse_json_field(row[field_name])
            counter.update(items)
        return [{"name": name, "count": count} for name, count in counter.most_common(50)]

    # ── Stats ────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get dashboard statistics."""
        total = self.conn.execute("SELECT COUNT(*) as cnt FROM books").fetchone()["cnt"]
        total_size = self.conn.execute("SELECT COALESCE(SUM(size), 0) as s FROM books").fetchone()["s"]

        by_type = self.conn.execute(
            "SELECT file_type, COUNT(*) as cnt FROM books GROUP BY file_type"
        ).fetchall()

        by_status = self.conn.execute(
            "SELECT reading_status, COUNT(*) as cnt FROM books GROUP BY reading_status"
        ).fetchall()

        with_cover = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM books WHERE cover_path IS NOT NULL AND cover_path != ''"
        ).fetchone()["cnt"]

        with_description = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM books WHERE description IS NOT NULL AND description != ''"
        ).fetchone()["cnt"]

        with_embeddings = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM embeddings"
        ).fetchone()["cnt"]

        avg_rating = self.conn.execute(
            "SELECT AVG(user_rating) as avg FROM books WHERE user_rating IS NOT NULL"
        ).fetchone()["avg"]

        categories = self._count_json_array_field("categories")
        themes = self._count_json_array_field("themes")

        # Year histogram
        year_rows = self.conn.execute(
            "SELECT publication_year, COUNT(*) as cnt FROM books WHERE publication_year IS NOT NULL GROUP BY publication_year ORDER BY publication_year"
        ).fetchall()

        # Recently processed
        recent = self.conn.execute(
            "SELECT id, title, author_primary, cover_path, last_processed FROM books ORDER BY last_processed DESC LIMIT 10"
        ).fetchall()

        return {
            "total_books": total,
            "total_size_bytes": total_size,
            "by_type": {r["file_type"]: r["cnt"] for r in by_type},
            "by_status": {r["reading_status"]: r["cnt"] for r in by_status},
            "with_cover": with_cover,
            "with_description": with_description,
            "with_embeddings": with_embeddings,
            "avg_rating": round(avg_rating, 1) if avg_rating else None,
            "categories": categories[:15],
            "themes": themes[:10],
            "year_histogram": [{"year": r["publication_year"], "count": r["cnt"]} for r in year_rows],
            "recently_processed": [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "author": r["author_primary"],
                    "cover_url": f"/covers/{Path(r['cover_path']).name}" if r["cover_path"] else None,
                }
                for r in recent
            ],
        }

    # ── Embedding Storage ────────────────────────────────────────────────

    def store_embedding(self, book_id: str, content_emb: Optional[bytes], metadata_emb: Optional[bytes]):
        """Store embedding blobs."""
        self.conn.execute("""
            INSERT OR REPLACE INTO embeddings (book_id, content_embedding, metadata_embedding)
            VALUES (?, ?, ?)
        """, (book_id, content_emb, metadata_emb))
        self.conn.commit()

    def get_all_embeddings(self) -> list[tuple[str, Optional[bytes], Optional[bytes]]]:
        """Get all embeddings for loading into memory."""
        rows = self.conn.execute("SELECT book_id, content_embedding, metadata_embedding FROM embeddings").fetchall()
        return [(r["book_id"], r["content_embedding"], r["metadata_embedding"]) for r in rows]

    def get_book_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) as cnt FROM books").fetchone()["cnt"]
