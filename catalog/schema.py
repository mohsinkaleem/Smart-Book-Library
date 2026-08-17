"""
Canonical SQLite schema for the catalog.

`data/catalog.db` is the store of record: the pipeline writes it directly and
the web server reads it. `catalog.json` is now
only an export. Both `catalog.store` and `server.db` call `ensure_schema` so
the DDL exists in exactly one place.

Two tables own book data:

* ``books``     — everything the pipeline produces. The pipeline never writes
                  the user-owned columns (R5).
* ``user_data`` — ratings, tags, favourites, reading progress and pinned field
                  corrections. Keyed by book id *and* file path so the data
                  survives a full catalog rebuild.
"""
import sqlite3

# Columns owned by the pipeline; user-owned columns are listed separately so the
# upsert can never clobber them.
BOOK_COLUMNS: list[tuple[str, str]] = [
    ("id", "TEXT PRIMARY KEY"),
    ("content_sha1", "TEXT DEFAULT ''"),
    ("file_path", "TEXT UNIQUE NOT NULL"),
    ("file_name", "TEXT NOT NULL"),
    ("file_type", "TEXT NOT NULL"),
    ("size", "INTEGER DEFAULT 0"),
    ("mtime", "REAL DEFAULT 0"),
    ("status", "TEXT DEFAULT 'active'"),
    ("title", "TEXT DEFAULT ''"),
    ("subtitle", "TEXT DEFAULT ''"),
    ("original_title_meta", "TEXT DEFAULT ''"),
    ("authors", "TEXT DEFAULT '[]'"),
    ("publisher", "TEXT DEFAULT ''"),
    ("publication_year", "INTEGER"),
    ("language", "TEXT DEFAULT ''"),
    ("script", "TEXT DEFAULT ''"),
    ("page_count", "INTEGER"),
    ("isbn_10", "TEXT DEFAULT ''"),
    ("isbn_13", "TEXT DEFAULT ''"),
    ("source_ids", "TEXT DEFAULT '[]'"),
    ("description", "TEXT DEFAULT ''"),
    ("summary", "TEXT DEFAULT ''"),
    ("themes", "TEXT DEFAULT '[]'"),
    ("categories", "TEXT DEFAULT '[]'"),
    ("subjects_raw", "TEXT DEFAULT '[]'"),
    ("keywords", "TEXT DEFAULT '[]'"),
    ("cover_path", "TEXT DEFAULT ''"),
    ("text_excerpt", "TEXT DEFAULT ''"),
    ("front_matter", "TEXT DEFAULT ''"),
    ("content_sample", "TEXT DEFAULT ''"),
    ("field_sources", "TEXT DEFAULT '{}'"),
    ("needs_review", "INTEGER DEFAULT 0"),
    ("review_reasons", "TEXT DEFAULT '[]'"),
    ("match_score", "REAL"),
    ("rejected_candidates", "TEXT DEFAULT '[]'"),
    ("has_text", "INTEGER DEFAULT 1"),
    ("ocr_required", "INTEGER DEFAULT 0"),
    ("api_sources", "TEXT DEFAULT '[]'"),
    ("stage_versions", "TEXT DEFAULT '{}'"),
    ("duplicate_of", "TEXT"),
    ("processing_errors", "TEXT DEFAULT '[]'"),
    ("last_processed", "TEXT DEFAULT ''"),
    ("date_added", "TEXT DEFAULT ''"),
    ("author_primary", "TEXT DEFAULT ''"),
    # ── user-owned; mirrored from user_data, never written by the pipeline ──
    ("last_opened", "TEXT"),
    ("reading_status", "TEXT DEFAULT 'not_started'"),
    ("progress_percent", "REAL DEFAULT 0"),
    ("user_rating", "REAL"),
    ("user_tags", "TEXT DEFAULT '[]'"),
    ("favorite", "INTEGER DEFAULT 0"),
]

USER_COLUMNS = [
    "last_opened",
    "reading_status",
    "progress_percent",
    "user_rating",
    "user_tags",
    "favorite",
]

PIPELINE_COLUMNS = [name for name, _ in BOOK_COLUMNS if name not in USER_COLUMNS]

FTS_COLUMNS = [
    "title",
    "authors",
    "description",
    "summary",
    "themes",
    "categories",
    "keywords",
    "publisher",
    "subjects_raw",
]

_INDEXES = [
    ("idx_books_file_type", "books(file_type)"),
    ("idx_books_reading_status", "books(reading_status)"),
    ("idx_books_favorite", "books(favorite)"),
    ("idx_books_publication_year", "books(publication_year)"),
    ("idx_books_language", "books(language)"),
    ("idx_books_user_rating", "books(user_rating)"),
    ("idx_books_duplicate", "books(duplicate_of)"),
    ("idx_books_needs_review", "books(needs_review)"),
    ("idx_books_status", "books(status)"),
    ("idx_books_content_sha1", "books(content_sha1)"),
    ("idx_books_title", "books(title COLLATE NOCASE)"),
    ("idx_books_author_primary", "books(author_primary COLLATE NOCASE)"),
]

USER_DATA_SQL = """
CREATE TABLE IF NOT EXISTS user_data (
    book_id          TEXT PRIMARY KEY,
    file_path        TEXT,
    reading_status   TEXT DEFAULT 'not_started',
    progress_percent REAL DEFAULT 0,
    user_rating      REAL,
    user_tags        TEXT DEFAULT '[]',
    favorite         INTEGER DEFAULT 0,
    last_opened      TEXT,
    field_overrides  TEXT DEFAULT '{}',
    updated_at       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_user_data_path ON user_data(file_path);
"""

EMBEDDINGS_SQL = """
CREATE TABLE IF NOT EXISTS embeddings (
    book_id            TEXT PRIMARY KEY,
    content_embedding  BLOB,
    metadata_embedding BLOB
);
"""


def _fts_ddl() -> str:
    cols = ",\n    ".join(FTS_COLUMNS)
    insert_cols = ", ".join(FTS_COLUMNS)
    new_vals = ", ".join(f"new.{c}" for c in FTS_COLUMNS)
    old_vals = ", ".join(f"old.{c}" for c in FTS_COLUMNS)
    return f"""
CREATE VIRTUAL TABLE IF NOT EXISTS books_fts USING fts5(
    {cols},
    content='books',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

DROP TRIGGER IF EXISTS books_ai;
DROP TRIGGER IF EXISTS books_ad;
DROP TRIGGER IF EXISTS books_au;

CREATE TRIGGER books_ai AFTER INSERT ON books BEGIN
    INSERT INTO books_fts(rowid, {insert_cols}) VALUES (new.rowid, {new_vals});
END;

CREATE TRIGGER books_ad AFTER DELETE ON books BEGIN
    INSERT INTO books_fts(books_fts, rowid, {insert_cols})
    VALUES ('delete', old.rowid, {old_vals});
END;

CREATE TRIGGER books_au AFTER UPDATE ON books BEGIN
    INSERT INTO books_fts(books_fts, rowid, {insert_cols})
    VALUES ('delete', old.rowid, {old_vals});
    INSERT INTO books_fts(rowid, {insert_cols}) VALUES (new.rowid, {new_vals});
END;
"""


def _existing_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", (name,)
    ).fetchone()
    return row is not None


def ensure_schema(conn: sqlite3.Connection):
    """Create or migrate the catalog schema in-place. Safe to call repeatedly."""
    conn.execute("PRAGMA journal_mode=WAL")

    if not _table_exists(conn, "books"):
        cols = ",\n    ".join(f"{name} {decl}" for name, decl in BOOK_COLUMNS)
        conn.execute(f"CREATE TABLE books (\n    {cols}\n)")
    else:
        have = set(_existing_columns(conn, "books"))
        for name, decl in BOOK_COLUMNS:
            if name not in have:
                # PRIMARY KEY / UNIQUE / NOT NULL cannot be added by ALTER.
                simple = (
                    decl.replace(" PRIMARY KEY", "")
                    .replace(" UNIQUE", "")
                    .replace(" NOT NULL", "")
                )
                conn.execute(f"ALTER TABLE books ADD COLUMN {name} {simple}")

    for idx_name, target in _INDEXES:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {target}")

    # FTS: recreate when the indexed column set changed (adding a column to an
    # existing fts5 table is not possible).
    rebuild_fts = False
    if _table_exists(conn, "books_fts"):
        if _existing_columns(conn, "books_fts") != FTS_COLUMNS:
            conn.execute("DROP TABLE books_fts")
            rebuild_fts = True
    else:
        rebuild_fts = True

    conn.executescript(_fts_ddl())
    conn.executescript(USER_DATA_SQL)
    conn.executescript(EMBEDDINGS_SQL)

    if rebuild_fts:
        try:
            conn.execute("INSERT INTO books_fts(books_fts) VALUES('rebuild')")
        except sqlite3.OperationalError:
            pass

    conn.commit()
