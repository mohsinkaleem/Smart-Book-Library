"""
Canonical SQLite schema for the catalog.

`data/catalog.db` is the store of record: the pipeline writes it directly and
the web server reads it. `catalog.json` is now
only an export. Both `catalog.store` and `server.db` call `ensure_schema` so
the DDL exists in exactly one place.

Two tables own book data:

* ``books``     — everything the pipeline produces. The pipeline does not write
                  the user-owned columns (R5); the one exception is the opt-in
                  reading-progress stage, which may only advance `last_opened`.
* ``user_data`` — ratings, tags, favourites, reading progress and pinned field
                  corrections. Keyed by book id *and* file path so the data
                  survives a full catalog rebuild.
"""
import logging
import random
import sqlite3

from .config import TEXT_DIR
from .enrichment_status import (
    BORDERLINE,
    DEFERRED,
    NO_EVIDENCE,
    REJECTED,
    UNMATCHED,
    VERIFIED,
)

logger = logging.getLogger(__name__)

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
    # Why the enrichment stage ended where it did: verified | borderline |
    # rejected | unmatched | no_evidence | deferred, or '' when it never ran.
    # Separate from `needs_review`, which means "a human's judgement would
    # change something". Conflating them put 153 books that simply are not in
    # OpenLibrary or Google Books into a queue a human cannot action, and
    # buried the handful that genuinely need a decision.
    ("enrichment_status", "TEXT DEFAULT ''"),
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
    # ── user-owned; mirrored from user_data. The pipeline does not write
    #    these, with one declared exception: the opt-in reading-progress stage
    #    may advance `last_opened` when the filesystem reports an open *newer*
    #    than the one on record. It may never move it backwards.
    ("last_opened", "TEXT"),
    ("reading_status", "TEXT DEFAULT 'not_started'"),
    ("progress_percent", "REAL DEFAULT 0"),
    # Where the reader was left: an EPUB CFI, or a PDF page number as a string.
    # Opaque to the server — only the reader that wrote it interprets it.
    ("reader_position", "TEXT DEFAULT ''"),
    ("user_rating", "REAL"),
    ("user_tags", "TEXT DEFAULT '[]'"),
    ("favorite", "INTEGER DEFAULT 0"),
]

USER_COLUMNS = [
    "last_opened",
    "reading_status",
    "progress_percent",
    "reader_position",
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

# The book's own prose, indexed separately from its metadata.
#
# "Full-Text Search" used to mean full-text over *metadata* — the extracted
# text was stored and never indexed. It lives in its own fts5 table rather
# than being appended to `books_fts` because a 5 000-character excerpt next to
# a 40-character title wrecks bm25: every long document would outrank an exact
# title match on term frequency alone. Two tables, two rankings, blended by
# the caller with the metadata side weighted higher.
TEXT_FTS_COLUMNS = [
    "text_excerpt",
    "front_matter",
    "content_sample",
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
    ("idx_books_enrichment_status", "books(enrichment_status)"),
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
    reader_position  TEXT DEFAULT '',
    user_rating      REAL,
    user_tags        TEXT DEFAULT '[]',
    favorite         INTEGER DEFAULT 0,
    last_opened      TEXT,
    field_overrides  TEXT DEFAULT '{}',
    updated_at       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_user_data_path ON user_data(file_path);
"""

# Columns added to `user_data` after it first shipped. `CREATE TABLE IF NOT
# EXISTS` is a no-op on an existing table, so a new column in the DDL above
# reaches an existing database only through this list.
USER_DATA_ADDED_COLUMNS = [
    ("reader_position", "TEXT DEFAULT ''"),
]

# Highlights, bookmarks and margin notes.
#
# Keyed by book id *and* file path for the same reason `user_data` is: a full
# catalog rebuild reassigns nothing a user typed. The id is a content hash, so
# it survives a move but not a re-encode; the path survives a re-encode but not
# a move. Keeping both means a rebuild can relocate an orphaned annotation
# either way.
#
# Anchoring differs by format and neither is exact:
#   * PDF  — `page` plus `anchor_text`. The page is durable; the text locates
#            the highlight within it.
#   * EPUB — `cfi`, with `anchor_text` as the fallback when a re-rendered
#            document shifts the CFI out from under it.
# `anchor_text` is therefore not redundant with `text`: it is the shorter,
# stable needle used to re-find a highlight, and it is what §1.5 of the
# features doc wants chunk anchoring to share.
ANNOTATIONS_SQL = """
CREATE TABLE IF NOT EXISTS annotations (
    id          TEXT PRIMARY KEY,
    book_id     TEXT NOT NULL,
    file_path   TEXT,
    kind        TEXT NOT NULL DEFAULT 'highlight',
    text        TEXT DEFAULT '',
    note        TEXT DEFAULT '',
    color       TEXT DEFAULT 'yellow',
    page        INTEGER,
    cfi         TEXT DEFAULT '',
    anchor_text TEXT DEFAULT '',
    created_at  TEXT DEFAULT '',
    updated_at  TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_annotations_book ON annotations(book_id);
CREATE INDEX IF NOT EXISTS idx_annotations_path ON annotations(file_path);
CREATE INDEX IF NOT EXISTS idx_annotations_kind ON annotations(book_id, kind);
"""

ANNOTATION_KINDS = ("highlight", "bookmark", "note")

# ── The passage index (Part 1) ───────────────────────────────────────────────
#
# `chunks.id` is the row index into `data/chunk_vectors.npy`, so a top-k result
# maps back to its text with a single `WHERE id IN (...)`. That coupling is the
# reason ids are assigned by the builder rather than by AUTOINCREMENT, and the
# reason the vector file is rewritten whole: trying to keep row indices stable
# across deletes buys nothing and gets the mapping wrong exactly once, silently.
#
# Anchoring is per format and, as Part 3 learned the hard way, *positional*:
# a chunk is located by character offsets into the book's extracted text and
# those offsets are mapped to a page, never by searching for the chunk's text
# and taking the first hit. A word occurring twice on a page is the common
# case, and containment picks the wrong one without any visible symptom.
CHUNKS_SQL = """
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY,   -- row index into the vector file
    book_id     TEXT NOT NULL,
    chunk_idx   INTEGER NOT NULL,      -- ordinal within the book
    char_start  INTEGER,               -- offset into data/text/{book_id}.txt
    char_end    INTEGER,
    page_start  INTEGER,               -- PDF
    page_end    INTEGER,               -- PDF
    spine_index INTEGER,               -- EPUB
    section     TEXT DEFAULT '',       -- chapter/heading if detectable
    UNIQUE(book_id, chunk_idx)
);
CREATE INDEX IF NOT EXISTS idx_chunks_book ON chunks(book_id);
"""

#: The columns a chunk row carries, in order. Named once so the builder, the
#: reader and the migration cannot disagree about it.
CHUNK_COLUMNS = [
    "id", "book_id", "chunk_idx", "char_start", "char_end",
    "page_start", "page_end", "spine_index", "section",
]

# One row. Stamped at build time so a model or chunking change is a detectable
# re-index rather than a silent corruption — the same lesson as
# `embeddings.model_id`, applied before it could be learned twice.
CHUNK_INDEX_META_SQL = """
CREATE TABLE IF NOT EXISTS chunk_index_meta (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    model_id      TEXT DEFAULT '',
    dim           INTEGER DEFAULT 0,
    count         INTEGER DEFAULT 0,
    book_count    INTEGER DEFAULT 0,
    dtype         TEXT DEFAULT 'float16',
    built_at      TEXT DEFAULT '',
    chunk_chars   INTEGER DEFAULT 0,
    chunk_overlap INTEGER DEFAULT 0
);
"""

# Contentless, and populated by the builder rather than by triggers.
#
# It used to be an external-content index over `chunks.text`, which meant the
# database held every passage twice: once as a row and once as 317 MB of the
# same prose already sitting in `data/text`. The chunk overlap made it worse
# than a straight copy. Now a chunk row carries only its character span and
# `full_text.read_span` reads the words back, so `chunks.text` does not exist
# for an external-content index to point at.
#
# What this costs: `snippet()` over `chunks_fts` returns empty strings. Only
# `books_fts` and `book_text_fts` use `snippet()`, and both keep their
# external content, so nothing in the application notices.
CHUNKS_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    content='',
    tokenize='porter unicode61'
);

DROP TRIGGER IF EXISTS chunks_ai;
DROP TRIGGER IF EXISTS chunks_ad;
DROP TRIGGER IF EXISTS chunks_au;
"""

# ── LLM threads (§4.2) ───────────────────────────────────────────────────────
#
# A thread is scoped to a passage: the selection and the retrieved context are
# pinned to the thread once and replayed into every turn, so a follow-up
# question does not have to restate what "it" refers to. Messages are a
# separate table rather than a JSON column because the streaming route appends
# one at a time and rewriting a growing blob per token is how that goes wrong.
#
# Keyed by `file_path` alongside `book_id` for the same reason `user_data` and
# `annotations` are: a rebuild reassigns book ids and must not orphan anything
# a human typed.
LLM_THREADS_SQL = """
CREATE TABLE IF NOT EXISTS llm_threads (
    id          TEXT PRIMARY KEY,
    book_id     TEXT NOT NULL,
    file_path   TEXT,
    title       TEXT DEFAULT '',
    passage     TEXT DEFAULT '',     -- the pinned selection
    surrounding TEXT DEFAULT '',     -- prose around it, as sent by the reader
    context     TEXT DEFAULT '',     -- the retrieved, citable block
    page        INTEGER,
    cfi         TEXT DEFAULT '',
    created_at  TEXT DEFAULT '',
    updated_at  TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_llm_threads_book ON llm_threads(book_id);
CREATE INDEX IF NOT EXISTS idx_llm_threads_path ON llm_threads(file_path);

CREATE TABLE IF NOT EXISTS llm_messages (
    id         TEXT PRIMARY KEY,
    thread_id  TEXT NOT NULL REFERENCES llm_threads(id) ON DELETE CASCADE,
    role       TEXT NOT NULL DEFAULT 'user',   -- user | assistant
    content    TEXT DEFAULT '',
    action     TEXT DEFAULT '',                -- explain | compare | ... | ask
    created_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_llm_messages_thread ON llm_messages(thread_id, created_at);
"""

# ── Reading sessions (Part 5) ────────────────────────────────────────────────
#
# `progress_percent` records *where* the reader is; nothing recorded *when* or
# for how long, so pages/week, streaks and time-to-finish were all unanswerable.
# A session is opened when the reader mounts and closed by heartbeat, so a
# closed browser tab leaves a session with the last heartbeat as its end rather
# than an open row that grows forever.
READING_SESSIONS_SQL = """
CREATE TABLE IF NOT EXISTS reading_sessions (
    id           TEXT PRIMARY KEY,
    book_id      TEXT NOT NULL,
    file_path    TEXT,
    started_at   TEXT DEFAULT '',
    ended_at     TEXT DEFAULT '',
    seconds      INTEGER DEFAULT 0,
    start_page   INTEGER,
    end_page     INTEGER,
    pages        INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_reading_sessions_book ON reading_sessions(book_id);
CREATE INDEX IF NOT EXISTS idx_reading_sessions_started ON reading_sessions(started_at);
"""

# ── EPUB locations (§2.1) ────────────────────────────────────────────────────
#
# `book.locations.generate()` walks the whole book and costs seconds on a large
# EPUB — far too slow to run on every open, which is why progress was an
# approximate spine ratio. Generated once and cached here, it becomes an exact
# "page X of Y".
EPUB_LOCATIONS_SQL = """
CREATE TABLE IF NOT EXISTS epub_locations (
    book_id    TEXT PRIMARY KEY,
    locations  TEXT DEFAULT '',   -- book.locations.save(), an opaque JSON string
    total      INTEGER DEFAULT 0,
    chars      INTEGER DEFAULT 0, -- the break interval it was generated at
    created_at TEXT DEFAULT ''
);
"""

EMBEDDINGS_SQL = """
CREATE TABLE IF NOT EXISTS embeddings (
    book_id            TEXT PRIMARY KEY,
    content_embedding  BLOB,
    metadata_embedding BLOB,
    model_id           TEXT DEFAULT ''
);
"""

# `model_id` records which model produced the blob. Vectors from two models
# share a dtype and a dimension and mean nothing together — their cosine is
# noise, and the failure is silent: search keeps returning results, they are
# just wrong. Stamping the model makes a swap a detectable re-index, and
# `SimilarityEngine` drops rows that do not match the configured model rather
# than mixing two vector spaces in one matrix.
EMBEDDINGS_ADDED_COLUMNS = [
    ("model_id", "TEXT DEFAULT ''"),
]


def _fts_ddl(table: str, columns: list[str], trigger_prefix: str) -> str:
    """
    DDL for one external-content fts5 index over `books`, plus its triggers.

    Both indexes share `content='books'`, so neither stores a second copy of
    the text — `book_text_fts` would otherwise duplicate ~6 MB of extracted
    prose that already sits in the `books` row.
    """
    cols = ",\n    ".join(columns)
    insert_cols = ", ".join(columns)
    new_vals = ", ".join(f"new.{c}" for c in columns)
    old_vals = ", ".join(f"old.{c}" for c in columns)
    return f"""
CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING fts5(
    {cols},
    content='books',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

DROP TRIGGER IF EXISTS {trigger_prefix}_ai;
DROP TRIGGER IF EXISTS {trigger_prefix}_ad;
DROP TRIGGER IF EXISTS {trigger_prefix}_au;

CREATE TRIGGER {trigger_prefix}_ai AFTER INSERT ON books BEGIN
    INSERT INTO {table}(rowid, {insert_cols}) VALUES (new.rowid, {new_vals});
END;

CREATE TRIGGER {trigger_prefix}_ad AFTER DELETE ON books BEGIN
    INSERT INTO {table}({table}, rowid, {insert_cols})
    VALUES ('delete', old.rowid, {old_vals});
END;

CREATE TRIGGER {trigger_prefix}_au AFTER UPDATE ON books BEGIN
    INSERT INTO {table}({table}, rowid, {insert_cols})
    VALUES ('delete', old.rowid, {old_vals});
    INSERT INTO {table}(rowid, {insert_cols}) VALUES (new.rowid, {new_vals});
END;
"""


# ── One-time migration: review reasons become an enrichment status ─────────

# The reason strings the pipeline wrote before `enrichment_status` existed,
# mapped to the status it would write now. The first match wins, so the more
# specific needle has to come first: "llm rejected the borderline match"
# *contains* "borderline match", and reading it as one would file 54
# rejections as records waiting on a decision they have already had.
_REASON_STATUS = [
    ("llm rejected the borderline match", REJECTED),
    ("no candidate passed verification", REJECTED),
    ("metadata lookup incomplete", DEFERRED),
    ("borderline match", BORDERLINE),
    ("insufficient evidence", NO_EVIDENCE),
    ("no ISBN and no usable title", NO_EVIDENCE),
    ("no provider returned a match", UNMATCHED),
]

#: The only pre-existing reason that still asks for a person.
_STILL_NEEDS_REVIEW = "no title could be established"


def _backfill_enrichment_status(conn: sqlite3.Connection) -> None:
    """
    Derive `enrichment_status` for records written before the column existed.

    Without this the split only takes effect after a full pipeline run, and
    until then every one of those records stays in a review queue it does not
    belong in. The reason strings are the pipeline's own output, so the
    mapping is a rename, not a guess.
    """
    rows = conn.execute(
        "SELECT id, review_reasons, api_sources, match_score, needs_review FROM books"
    ).fetchall()
    updates = []
    for book_id, raw_reasons, raw_sources, match_score, needs_review in rows:
        reasons = raw_reasons or ""
        status = ""
        for needle, value in _REASON_STATUS:
            if needle in reasons:
                status = value
                break
        if not status and match_score is not None and (raw_sources or "") not in ("", "[]"):
            status = VERIFIED

        keep_review = status == BORDERLINE or _STILL_NEEDS_REVIEW in reasons
        flag = 1 if keep_review else 0
        if status or flag != needs_review:
            updates.append((status, flag, book_id))

    if not updates:
        return
    conn.executemany(
        "UPDATE books SET enrichment_status = ?, needs_review = ? WHERE id = ?", updates
    )
    logger.info(
        f"Derived an enrichment status for {len(updates)} records from their "
        "recorded reasons; the review queue now holds only what a person can settle."
    )


# ── One-time migration: chunk text moves out of the database ────────────────

def _chunk_text_is_recoverable(conn: sqlite3.Connection, sample: int = 25) -> bool:
    """
    Whether every stored chunk can be read back from `data/text` by offset.

    Checked before the text column is dropped, because the offsets are only
    an index into a file that has to still be there. Every indexed book must
    have its text file, and a sampled chunk from each of `sample` books must
    slice back to exactly what the row holds.
    """
    book_ids = [r[0] for r in conn.execute("SELECT DISTINCT book_id FROM chunks")]
    missing = [b for b in book_ids if not (TEXT_DIR / f"{b}.txt").exists()]
    if missing:
        logger.error(
            f"{len(missing)} indexed book(s) have no file in {TEXT_DIR}; leaving "
            "`chunks.text` in place. Rebuild the passage index with "
            "`python scripts/build_passage_index.py --force --force-text` to fix it."
        )
        return False

    for book_id in random.Random(0).sample(book_ids, min(sample, len(book_ids))):
        row = conn.execute(
            "SELECT text, char_start, char_end FROM chunks "
            "WHERE book_id = ? AND char_start IS NOT NULL LIMIT 1",
            (book_id,),
        ).fetchone()
        if row is None:
            continue
        try:
            text = (TEXT_DIR / f"{book_id}.txt").read_text(encoding="utf-8")
        except OSError as e:
            logger.error(f"Cannot read cached text for {book_id}: {e}")
            return False
        if text[row[1]:row[2]].strip() != row[0]:
            logger.error(
                f"Chunk offsets for {book_id} do not match its cached text; "
                "leaving `chunks.text` in place and rebuilding is required."
            )
            return False
    return True


def _migrate_chunk_text_out(conn: sqlite3.Connection) -> bool:
    """
    Drop `chunks.text` / `chunks.anchor_text` and make `chunks_fts` contentless.

    The database held every passage twice — once as a row, once as the file in
    `data/text` it was cut from — which was 329 MB of a 670 MB catalog before
    the FTS index on top. A chunk row now carries only the span it occupies.

    The FTS index is filled from the column *before* it is dropped, so this is
    pure SQL: no file is read and nothing is re-tokenised. Returns True when
    the migration ran. Run VACUUM afterwards to hand the pages back.
    """
    if not _chunk_text_is_recoverable(conn):
        return False

    rows = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    logger.info(f"Moving {rows} chunks' text out of the database (one-time)…")

    columns = ", ".join(CHUNK_COLUMNS)
    with conn:
        conn.executescript(
            """
            DROP TRIGGER IF EXISTS chunks_ai;
            DROP TRIGGER IF EXISTS chunks_ad;
            DROP TRIGGER IF EXISTS chunks_au;
            DROP TABLE IF EXISTS chunks_fts;
            """
        )
        conn.executescript(CHUNKS_FTS_SQL)
        conn.execute("INSERT INTO chunks_fts(rowid, text) SELECT id, text FROM chunks")
        conn.executescript(CHUNKS_SQL.replace("chunks", "chunks_migrated"))
        conn.execute(
            f"INSERT INTO chunks_migrated ({columns}) SELECT {columns} FROM chunks"
        )
        conn.execute("DROP TABLE chunks")
        conn.execute("ALTER TABLE chunks_migrated RENAME TO chunks")
        conn.executescript(CHUNKS_SQL)

    logger.info(
        "Chunk text now lives only in data/text. Run `VACUUM` (or "
        "`python scripts/build_passage_index.py --vacuum`) to reclaim the space."
    )
    return True


def _existing_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _needs_rebuild(conn: sqlite3.Connection, table: str, columns: list[str]) -> bool:
    """
    True when `table` must be (re)built.

    fts5 has no ALTER, so a change to the indexed column set means dropping
    the index and repopulating it from `books`.
    """
    if not _table_exists(conn, table):
        return True
    if _existing_columns(conn, table) != columns:
        conn.execute(f"DROP TABLE {table}")
        return True
    return False


def ensure_schema(conn: sqlite3.Connection):
    """Create or migrate the catalog schema in-place. Safe to call repeatedly."""
    conn.execute("PRAGMA journal_mode=WAL")

    if not _table_exists(conn, "books"):
        cols = ",\n    ".join(f"{name} {decl}" for name, decl in BOOK_COLUMNS)
        conn.execute(f"CREATE TABLE books (\n    {cols}\n)")
    else:
        have = set(_existing_columns(conn, "books"))
        backfill_status = "enrichment_status" not in have
        for name, decl in BOOK_COLUMNS:
            if name not in have:
                # PRIMARY KEY / UNIQUE / NOT NULL cannot be added by ALTER.
                simple = (
                    decl.replace(" PRIMARY KEY", "")
                    .replace(" UNIQUE", "")
                    .replace(" NOT NULL", "")
                )
                conn.execute(f"ALTER TABLE books ADD COLUMN {name} {simple}")
        if backfill_status:
            _backfill_enrichment_status(conn)

    for idx_name, target in _INDEXES:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {target}")

    rebuild_meta = _needs_rebuild(conn, "books_fts", FTS_COLUMNS)
    rebuild_text = _needs_rebuild(conn, "book_text_fts", TEXT_FTS_COLUMNS)

    conn.executescript(_fts_ddl("books_fts", FTS_COLUMNS, "books"))
    conn.executescript(_fts_ddl("book_text_fts", TEXT_FTS_COLUMNS, "books_text"))
    conn.executescript(USER_DATA_SQL)
    conn.executescript(EMBEDDINGS_SQL)
    conn.executescript(ANNOTATIONS_SQL)
    # A `chunks` table that still has its `text` column is the pre-migration
    # shape. Migrate it if the text can be read back from disk; if it cannot,
    # leave the whole chunk schema — table, index and triggers — exactly as it
    # is, so the existing index keeps working until it is rebuilt.
    legacy_chunk_text = (
        _table_exists(conn, "chunks") and "text" in _existing_columns(conn, "chunks")
    )
    if not legacy_chunk_text or _migrate_chunk_text_out(conn):
        conn.executescript(CHUNKS_SQL)
        conn.executescript(CHUNKS_FTS_SQL)
    conn.executescript(CHUNK_INDEX_META_SQL)
    conn.executescript(LLM_THREADS_SQL)
    conn.executescript(READING_SESSIONS_SQL)
    conn.executescript(EPUB_LOCATIONS_SQL)

    if _table_exists(conn, "user_data"):
        have_user = set(_existing_columns(conn, "user_data"))
        for name, decl in USER_DATA_ADDED_COLUMNS:
            if name not in have_user:
                conn.execute(f"ALTER TABLE user_data ADD COLUMN {name} {decl}")

    if _table_exists(conn, "embeddings"):
        have_emb = set(_existing_columns(conn, "embeddings"))
        for name, decl in EMBEDDINGS_ADDED_COLUMNS:
            if name not in have_emb:
                conn.execute(f"ALTER TABLE embeddings ADD COLUMN {name} {decl}")

    for table, needed in (("books_fts", rebuild_meta), ("book_text_fts", rebuild_text)):
        if not needed:
            continue
        try:
            conn.execute(f"INSERT INTO {table}({table}) VALUES('rebuild')")
        except sqlite3.OperationalError:
            pass

    conn.commit()
