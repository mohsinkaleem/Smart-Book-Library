"""
SQLite database wrapper with FTS5 full-text search.

The schema itself lives in `catalog.schema` — the pipeline and the server read
and write the same `data/catalog.db`, so the DDL exists in one place only
User-owned fields are written through
`catalog.user_data`, which keeps them in their own table so a pipeline run can
never overwrite them (R5).
"""
import json
import sqlite3
import logging
import sys
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from .config import DB_PATH, PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT))

from catalog.fts import fts_query  # noqa: E402
from catalog.languages import UNKNOWN as LANG_UNKNOWN  # noqa: E402
from catalog.languages import normalise_language  # noqa: E402
from catalog.schema import PIPELINE_COLUMNS, ensure_schema  # noqa: E402
from catalog.user_data import clear_review as _clear_review  # noqa: E402
from catalog.user_data import pin_field as _pin_field  # noqa: E402
from catalog.user_data import write_user_fields as _write_user_fields  # noqa: E402

logger = logging.getLogger(__name__)

# Markers wrapped around matched terms by FTS5's `snippet()`.
#
# Control characters rather than something like `<b>`, because the frontend
# renders snippets as text and must not have to trust the server not to have
# sent markup — and because these two bytes cannot occur in extracted book
# text. `docs/API.md` documents them as part of the search response.
SNIPPET_OPEN = ""
SNIPPET_CLOSE = ""

# How much a match in the book's own prose counts relative to a match in its
# metadata. bm25 returns negative scores (more negative is better) and the two
# indexes are summed, so a weight below 1 keeps a title hit ahead of a body
# hit. Without it, a 5 000-character excerpt beats an exact title on term
# frequency alone.
TEXT_MATCH_WEIGHT = 0.35

# Rowids of every book matching a query in *either* index. Takes the same
# match expression twice. Used wherever a search has to be expressed as a
# containment test rather than a ranking — the list endpoint's `search=`
# parameter and the facet counts — so those two agree with `/api/search`
# about what "matches" means.
MATCHING_ROWIDS_SQL = (
    "SELECT rowid FROM books_fts WHERE books_fts MATCH ? "
    "UNION SELECT rowid FROM book_text_fts WHERE book_text_fts MATCH ?"
)

def _json_field(val: Any) -> str:
    """Convert a list/dict to JSON string for storage."""
    if isinstance(val, (list, dict)):
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, str):
        return val
    return json.dumps(val or [], ensure_ascii=False)


def _as_year(val: Any) -> Optional[int]:
    """Coerce a year filter to int, or None. `?year_min=abc` used to be a 500."""
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


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
    """
    SQLite database for the book catalog with FTS5 search.

    One connection is shared by every caller (`check_same_thread=False`), and
    those callers are genuinely concurrent: FastAPI runs the sync route
    handlers in a threadpool and `server.tasks` spawns background pipeline and
    embedding threads against the same file. Every statement therefore goes
    through `self._lock`, the way `catalog.store.CatalogStore` already does it.

    Read it through `query`/`query_one` rather than reaching for `.conn`
    directly, so the lock is not bypassed.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self):
        """Create or migrate the shared catalog schema."""
        ensure_schema(self.conn)

    def close(self):
        with self._lock:
            self.conn.close()

    # ── Locked access ────────────────────────────────────────────────────

    def query(self, sql: str, params: Any = ()) -> list[sqlite3.Row]:
        """Run a read query under the connection lock."""
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Any = ()) -> Optional[sqlite3.Row]:
        """Run a read query under the connection lock, first row only."""
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    # ── Book CRUD ────────────────────────────────────────────────────────

    def upsert_book(self, book: dict):
        """
        Insert or update a book from a pipeline record.

        Only pipeline-owned columns are written. The old `INSERT OR REPLACE`
        listed `reading_status`, `progress_percent`, `user_rating`, `user_tags`
        and `favorite` too, so every sync overwrote the user's edits with stale
        defaults from catalog.json (R5).
        """
        authors = book.get("authors", [])
        author_primary = authors[0] if isinstance(authors, list) and authors else ""

        values: dict[str, Any] = {}
        for column in PIPELINE_COLUMNS:
            if column == "author_primary":
                values[column] = author_primary
                continue
            raw = book.get(column)
            if column in ("authors", "themes", "categories", "keywords", "api_sources",
                          "processing_errors", "subjects_raw", "source_ids",
                          "review_reasons", "rejected_candidates"):
                values[column] = _json_field(raw if raw is not None else [])
            elif column in ("field_sources", "stage_versions"):
                values[column] = json.dumps(raw or {}, ensure_ascii=False)
            elif column in ("has_text",):
                values[column] = 1 if book.get(column, True) else 0
            elif column in ("ocr_required", "needs_review"):
                values[column] = 1 if book.get(column, False) else 0
            else:
                values[column] = raw

        columns = list(values.keys())
        placeholders = ", ".join("?" for _ in columns)
        update_clause = ", ".join(f"{c} = excluded.{c}" for c in columns if c != "id")
        with self._lock:
            self.conn.execute(
                f"""INSERT INTO books ({", ".join(columns)})
                    VALUES ({placeholders})
                    ON CONFLICT(id) DO UPDATE SET {update_clause}""",
                [values[c] for c in columns],
            )
            self.conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a SQLite Row to a book dict with parsed JSON fields."""
        d = dict(row)
        # Parse JSON array fields
        for field in ("authors", "themes", "categories", "keywords",
                      "api_sources", "user_tags", "processing_errors",
                      "subjects_raw", "source_ids", "review_reasons",
                      "rejected_candidates"):
            if field in d:
                d[field] = _parse_json_field(d.get(field))
        # Provenance is an object, not an array.
        if "field_sources" in d:
            try:
                d["field_sources"] = json.loads(d.get("field_sources") or "{}")
            except (json.JSONDecodeError, TypeError):
                d["field_sources"] = {}
        # Convert int booleans
        d["has_text"] = bool(d.get("has_text", 1))
        d["ocr_required"] = bool(d.get("ocr_required", 0))
        d["favorite"] = bool(d.get("favorite", 0))
        d["needs_review"] = bool(d.get("needs_review", 0))
        # Add computed fields
        d["has_cover"] = bool(d.get("cover_path"))
        d["has_description"] = bool(d.get("description"))
        d["title_source"] = (d.get("field_sources") or {}).get("title", {}).get("source", "")
        d["title_verified"] = d["title_source"] in ("user", "isbn_match", "api_verified")
        # Cover URL
        if d.get("cover_path"):
            cover_name = Path(d["cover_path"]).name
            d["cover_url"] = f"/covers/{cover_name}"
        else:
            d["cover_url"] = None
        return d

    def get_book(self, book_id: str) -> Optional[dict]:
        """Get a single book by ID."""
        row = self.query_one("SELECT * FROM books WHERE id = ?", (book_id,))
        return self._row_to_dict(row) if row else None

    def get_books_by_ids(self, book_ids: list[str]) -> dict[str, dict]:
        """
        Fetch many books in one round-trip, keyed by id.

        Semantic and hybrid search used to call `get_book()` once per
        candidate — 200 queries to render a page of 48.
        """
        if not book_ids:
            return {}
        out: dict[str, dict] = {}
        # SQLITE_MAX_VARIABLE_NUMBER is 999 on older builds; chunk to stay under it.
        for start in range(0, len(book_ids), 500):
            chunk = book_ids[start:start + 500]
            placeholders = ", ".join("?" for _ in chunk)
            rows = self.query(f"SELECT * FROM books WHERE id IN ({placeholders})", chunk)
            for row in rows:
                book = self._row_to_dict(row)
                out[book["id"]] = book
        return out

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
        # This used to re-implement every predicate inline, which is how the
        # two copies drifted: `has_cover=false` was honoured here and ignored
        # by `_apply_filters`, and `language` matched the raw column here
        # while the facets offered normalised codes. One implementation now —
        # `status != 'missing'` is applied by `_apply_filters` itself (M7).
        where_clauses: list[str] = []
        params: list[Any] = []
        self._apply_filters(where_clauses, params, {
            "file_type": file_type, "category": category, "theme": theme,
            "language": language, "reading_status": reading_status,
            "has_cover": has_cover, "has_description": has_description,
            "year_min": year_min, "year_max": year_max,
            "rating_min": rating_min, "favorite": favorite,
            "author": author, "tag": tag,
        })

        if search:
            # Raw user input used to go straight into MATCH here, so any FTS5
            # metacharacter was a 500: `?search=self-help`, `?search=AND`.
            match_expr = fts_query(search, prefix=True)
            if not match_expr:
                return self._empty_page(page, per_page)
            where_clauses.append(f"rowid IN ({MATCHING_ROWIDS_SQL})")
            params.extend([match_expr, match_expr])

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
        count_row = self.query_one(
            f"SELECT COUNT(*) as cnt FROM books WHERE {where_sql}", params
        )
        total = count_row["cnt"]

        # Fetch page
        offset = (page - 1) * per_page
        rows = self.query(
            f"SELECT * FROM books WHERE {where_sql} ORDER BY {sort_col} {sort_dir} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        )

        pages = max(1, (total + per_page - 1) // per_page)
        return {
            "items": [self._row_to_dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }

    @staticmethod
    def _empty_page(page: int, per_page: int) -> dict:
        return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 1}

    def get_continue_reading(self, limit: int = 8) -> list[dict]:
        """
        Books the user has opened and not finished, most recent first.

        `last_opened` and `progress_percent` were in the schema, in
        `USER_FIELDS`, in the TypeScript type and offered as `sort=last_opened`
        — and nothing in the app ever wrote either one, so this shelf could
        not have existed. The readers stamp them now.
        """
        rows = self.query(
            """SELECT * FROM books
               WHERE status != 'missing'
                 AND last_opened IS NOT NULL AND last_opened != ''
                 AND reading_status != 'finished'
               ORDER BY last_opened DESC
               LIMIT ?""",
            (limit,),
        )
        return [self._row_to_dict(r) for r in rows]

    def filtered_ids(self, **filters) -> set[str]:
        """
        The set of book IDs matching a filter set (always excluding `missing`).

        Semantic and hybrid search filter their candidates against this rather
        than re-implementing the predicates in Python — that second copy had
        already drifted and silently ignored `tag`.
        """
        where_clauses: list[str] = []
        params: list[Any] = []
        self._apply_filters(where_clauses, params, filters)
        where_sql = " AND ".join(where_clauses)
        rows = self.query(f"SELECT id FROM books WHERE {where_sql}", params)
        return {r["id"] for r in rows}

    def update_user_fields(self, book_id: str, fields: dict) -> Optional[dict]:
        """
        Update user-modifiable fields.

        Writes go to `user_data` first and are mirrored into `books`, so they
        survive a pipeline run or a full catalog rebuild (R5).

        The book must already exist: `_ensure_row` INSERTs into `user_data`
        unconditionally, so a PATCH against an unknown id used to 404 *and*
        leave an orphan row behind.
        """
        with self._lock:
            if self.conn.execute(
                "SELECT 1 FROM books WHERE id = ?", (book_id,)
            ).fetchone() is None:
                return None
            if not _write_user_fields(self.conn, book_id, fields):
                return None
            return self.get_book(book_id)

    # ── Review queue (M2) ────────────────────────────────────────────────

    def get_review_queue(self, page: int = 1, per_page: int = 25) -> dict:
        """Records the verification gate could not confirm, worst first."""
        total = self.query_one(
            "SELECT COUNT(*) AS cnt FROM books WHERE needs_review = 1 AND status != 'missing'"
        )["cnt"]
        offset = (page - 1) * per_page
        rows = self.query(
            """SELECT * FROM books
               WHERE needs_review = 1 AND status != 'missing'
               ORDER BY match_score IS NULL DESC, match_score ASC, file_name
               LIMIT ? OFFSET ?""",
            (per_page, offset),
        )
        return {
            "items": [self._row_to_dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def pin_field(self, book_id: str, name: str, value) -> Optional[dict]:
        """Record a human correction: source `user`, confidence 1.0, forever."""
        with self._lock:
            if not _pin_field(self.conn, book_id, name, value):
                return None
            return self.get_book(book_id)

    def resolve_review(self, book_id: str, resolution: str = "confirmed") -> Optional[dict]:
        with self._lock:
            if not _clear_review(self.conn, book_id, resolution):
                return None
            return self.get_book(book_id)

    # ── Search ───────────────────────────────────────────────────────────

    # Two rankings over the same books: one across the metadata index, one
    # across the extracted prose. Joined back onto `books` rather than
    # UNION'd, so a book matching both is one row scored on both.
    #
    # `snippet()`'s delimiters have to be SQL literals — fts5 auxiliary
    # functions reject bind parameters — hence the f-string. The values are
    # module constants, not user input.
    _SEARCH_CTE = f"""
        WITH meta AS (
            SELECT rowid AS rid,
                   bm25(books_fts) AS score,
                   snippet(books_fts, -1, '{SNIPPET_OPEN}', '{SNIPPET_CLOSE}', '…', 12) AS snip
            FROM books_fts WHERE books_fts MATCH ?
        ),
        body AS (
            SELECT rowid AS rid,
                   bm25(book_text_fts) AS score,
                   snippet(book_text_fts, -1, '{SNIPPET_OPEN}', '{SNIPPET_CLOSE}', '…', 18) AS snip
            FROM book_text_fts WHERE book_text_fts MATCH ?
        )
    """

    def search_fts(self, query: str, page: int = 1, per_page: int = 48, **filters) -> dict:
        """
        Full-text search over metadata *and* the book's own text.

        `books_fts` covers title/authors/description/…; `book_text_fts` covers
        the extracted excerpt, front matter and content sample. Until the
        second index existed, "Full-Text Search" meant full text over
        metadata only — the prose was stored and never searched.

        Each result carries a `snippet` showing why it matched, with the
        matched terms wrapped in `SNIPPET_OPEN`/`SNIPPET_CLOSE`. The prose
        snippet wins when a book matched both ways: "…the %s of the
        proletariat…" says more than the title the user can already see.
        """
        clean_q = query.strip()
        if not clean_q:
            return self.get_books(page=page, per_page=per_page, **filters)

        where_clauses: list[str] = []
        params: list[Any] = []
        self._apply_filters(where_clauses, params, filters)
        filter_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        match_expr = fts_query(clean_q, prefix=True)
        if not match_expr:
            return self._empty_page(page, per_page)

        matched = "(meta.rid IS NOT NULL OR body.rid IS NOT NULL)"
        joins = f"""
            FROM books
            LEFT JOIN meta ON meta.rid = books.rowid
            LEFT JOIN body ON body.rid = books.rowid
            WHERE {matched} AND {filter_sql}
        """
        match_params = [match_expr, match_expr]

        count_row = self.query_one(
            f"{self._SEARCH_CTE} SELECT COUNT(*) AS cnt {joins}",
            match_params + params,
        )
        total = count_row["cnt"]

        offset = (page - 1) * per_page
        rows = self.query(
            f"""{self._SEARCH_CTE}
                SELECT books.*,
                       COALESCE(meta.score, 0) + COALESCE(body.score, 0) * {TEXT_MATCH_WEIGHT}
                           AS score,
                       COALESCE(body.snip, meta.snip) AS snippet,
                       CASE WHEN body.rid IS NOT NULL THEN 'text' ELSE 'metadata' END
                           AS match_field
                {joins}
                ORDER BY score
                LIMIT ? OFFSET ?""",
            match_params + params + [per_page, offset],
        )

        items = []
        for r in rows:
            d = self._row_to_dict(r)
            d["_score"] = r["score"]
            d["snippet"] = r["snippet"] or ""
            d["match_field"] = r["match_field"]
            items.append(d)

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def suggest(self, query: str, limit: int = 8) -> list[dict]:
        """Autocomplete suggestions from title and authors.

        First tries a title-scoped match, then a broader FTS match, then a
        LIKE fallback.
        """
        clean_q = query.strip()
        if not clean_q:
            return []

        results: list[dict] = []
        seen_ids: set[str] = set()

        def _collect(rows) -> bool:
            """Add rows until `limit` is reached; True when full."""
            for r in rows:
                if r["id"] in seen_ids:
                    continue
                results.append({"id": r["id"], "title": r["title"], "author": r["author_primary"]})
                seen_ids.add(r["id"])
                if len(results) >= limit:
                    return True
            return len(results) >= limit

        fts_sql = """
            SELECT books.id, books.title, books.author_primary, bm25(books_fts) as score
            FROM books_fts
            JOIN books ON books.rowid = books_fts.rowid
            WHERE books_fts MATCH ? AND books.status != 'missing'
            ORDER BY score
            LIMIT ?
        """
        broad_expr = fts_query(clean_q, prefix=True)

        # 1. Title-scoped prefix match (highest priority)
        if broad_expr:
            title_expr = f"title : ({broad_expr})"
            try:
                if _collect(self.query(fts_sql, (title_expr, limit))):
                    return results[:limit]
            except sqlite3.OperationalError as e:
                logger.debug(f"Title suggest failed for {query!r}: {e}")

            # 2. Broader FTS match across all indexed fields
            try:
                if _collect(self.query(fts_sql, (broad_expr, limit))):
                    return results[:limit]
            except sqlite3.OperationalError as e:
                logger.debug(f"Broad suggest failed for {query!r}: {e}")

        # 3. LIKE fallback for fuzzy matching if still not enough
        like_q = f"%{clean_q}%"
        _collect(self.query("""
            SELECT id, title, author_primary FROM books
            WHERE status != 'missing'
              AND (title LIKE ? COLLATE NOCASE OR author_primary LIKE ? COLLATE NOCASE)
            LIMIT ?
        """, (like_q, like_q, limit)))

        return results[:limit]

    def _language_variants(self, code: str) -> list[str]:
        """
        Every raw `books.language` value that normalises to `code`.

        Cheap enough to run per query — it is one `SELECT DISTINCT` over an
        indexed column with a dozen distinct values — and it stays correct as
        the pipeline adds new junk rather than needing a hard-coded alias list.
        """
        rows = self.query("SELECT DISTINCT language FROM books")
        target = normalise_language(code) if code != LANG_UNKNOWN else LANG_UNKNOWN
        return [
            r["language"] for r in rows
            if normalise_language(r["language"]) == target
        ]

    def _apply_filters(self, where_clauses: list, params: list, filters: dict):
        """Apply filter clauses from kwargs."""
        where_clauses.append("books.status != 'missing'")
        if filters.get("needs_review"):
            where_clauses.append("books.needs_review = 1")
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
            # The sidebar offers normalised codes, not the raw column values —
            # `en-GB`, `eng` and `EN` are all `en`, and `po`/`sp`/`ge`/`''`
            # are all `unknown`. Expand the chosen code back to every raw
            # value that folds to it.
            raw_values = self._language_variants(filters["language"])
            if not raw_values:
                where_clauses.append("1=0")
            else:
                placeholders = ", ".join("?" for _ in raw_values)
                where_clauses.append(f"books.language IN ({placeholders})")
                params.extend(raw_values)
        if filters.get("reading_status"):
            where_clauses.append("books.reading_status = ?")
            params.append(filters["reading_status"])
        # The three booleans are symmetric: `true` requires the property,
        # `false` requires its absence, absent means no filter at all. Only
        # `has_cover=false` used to mean anything, and only on the list
        # endpoint.
        if filters.get("favorite") is not None:
            where_clauses.append(
                "books.favorite = 1" if filters["favorite"] else "books.favorite = 0"
            )
        if filters.get("rating_min") is not None:
            where_clauses.append("books.user_rating >= ?")
            params.append(filters["rating_min"])
        if filters.get("has_cover") is not None:
            where_clauses.append(
                "books.cover_path IS NOT NULL AND books.cover_path != ''"
                if filters["has_cover"]
                else "(books.cover_path IS NULL OR books.cover_path = '')"
            )
        if filters.get("has_description") is not None:
            where_clauses.append(
                "books.description IS NOT NULL AND books.description != ''"
                if filters["has_description"]
                else "(books.description IS NULL OR books.description = '')"
            )
        year_min = _as_year(filters.get("year_min"))
        if year_min is not None:
            where_clauses.append("books.publication_year >= ?")
            params.append(year_min)
        year_max = _as_year(filters.get("year_max"))
        if year_max is not None:
            where_clauses.append("books.publication_year <= ?")
            params.append(year_max)
        if filters.get("author"):
            where_clauses.append("books.authors LIKE ?")
            params.append(f'%"{filters["author"]}"%')
        if filters.get("tag"):
            where_clauses.append("books.user_tags LIKE ?")
            params.append(f'%"{filters["tag"]}"%')

    # ── Filter Facets ────────────────────────────────────────────────────

    def get_filter_facets(self, **filters) -> dict:
        """Get all filter facet values with counts, scoped to current filters.
        
        Each facet dimension excludes its own filter so users see what's
        available if they change that particular filter, while all other
        filters remain applied. This creates a truly reactive sidebar.
        """
        facets = {}

        # ── Helper: build WHERE clause excluding a specific filter key ──
        def _base_where(exclude_key: str | None = None):
            clauses: list[str] = []
            params: list = []
            f = dict(filters)
            if exclude_key and exclude_key in f:
                del f[exclude_key]
            # `_apply_filters` already covers has_cover/has_description/years;
            # this used to re-append all four on top of it.
            self._apply_filters(clauses, params, f)
            if f.get("search"):
                match_expr = fts_query(f["search"], prefix=True)
                if match_expr:
                    # Both indexes, so the facet counts agree with the result
                    # count the user is looking at.
                    clauses.append(f"books.rowid IN ({MATCHING_ROWIDS_SQL})")
                    params.extend([match_expr, match_expr])
                else:
                    clauses.append("1=0")
            return (" AND ".join(clauses) if clauses else "1=1"), params

        # Categories (exclude own filter)
        where, params = _base_where("category")
        facets["categories"] = self._count_json_array_field("categories", where, params)
        # Themes
        where, params = _base_where("theme")
        facets["themes"] = self._count_json_array_field("themes", where, params)
        # Authors
        where, params = _base_where("author")
        facets["authors"] = self._count_json_array_field("authors", where, params)
        # Languages.
        #
        # Grouped on the *normalised* code, not the raw column. The catalog
        # holds `po`, `sp` and `ge` alongside 25 empty strings, and the sidebar
        # used to offer each as its own option — several of them not
        # ISO-639-1, each matching one or two books. Everything that is not a
        # real code now falls into one `unknown` bucket, which `_apply_filters`
        # expands back to the raw values when it is picked.
        where, params = _base_where("language")
        rows = self.query(
            f"SELECT language, COUNT(*) as cnt FROM books WHERE ({where}) GROUP BY language",
            params
        )
        lang_counts: Counter = Counter()
        for r in rows:
            lang_counts[normalise_language(r["language"])] += r["cnt"]
        facets["languages"] = [
            {"name": name, "count": count}
            # `unknown` sorts last however big it is, so it never heads the list.
            for name, count in sorted(
                lang_counts.items(),
                key=lambda kv: (kv[0] == LANG_UNKNOWN, -kv[1], kv[0]),
            )
            if count
        ]
        # File types
        where, params = _base_where("file_type")
        rows = self.query(
            f"SELECT file_type, COUNT(*) as cnt FROM books WHERE ({where}) GROUP BY file_type ORDER BY cnt DESC",
            params
        )
        facets["file_types"] = [{"name": r["file_type"], "count": r["cnt"]} for r in rows]
        # Year range
        where, params = _base_where("year_min")
        row = self.query_one(
            f"SELECT MIN(publication_year) as min_year, MAX(publication_year) as max_year FROM books WHERE publication_year IS NOT NULL AND ({where})",
            params
        )
        facets["years"] = {"min": row["min_year"], "max": row["max_year"]} if row else {"min": None, "max": None}
        # Reading status
        where, params = _base_where("reading_status")
        rows = self.query(
            f"SELECT reading_status, COUNT(*) as cnt FROM books WHERE ({where}) GROUP BY reading_status ORDER BY cnt DESC",
            params
        )
        facets["reading_statuses"] = [{"name": r["reading_status"], "count": r["cnt"]} for r in rows]
        # Tags
        where, params = _base_where("tag")
        facets["tags"] = self._count_json_array_field("user_tags", where, params)

        # Total matching current full filter set
        where_all, params_all = _base_where(None)
        total_row = self.query_one(
            f"SELECT COUNT(*) as cnt FROM books WHERE ({where_all})", params_all
        )
        facets["total_matching"] = total_row["cnt"]

        return facets

    def _count_json_array_field(
        self, field_name: str, where_sql: str = "1=1", params: Optional[list] = None
    ) -> list[dict]:
        """Count occurrences in a JSON array field, filtered by WHERE clause."""
        rows = self.query(
            f"SELECT {field_name} FROM books WHERE ({where_sql})", params or []
        )
        counter: Counter = Counter()
        for row in rows:
            counter.update(_parse_json_field(row[field_name]))
        return [{"name": name, "count": count} for name, count in counter.most_common(50)]

    # ── Stats ────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """
        Dashboard statistics.

        Every count here excludes `status = 'missing'`, matching `get_books`
        and `get_review_queue`. Without that predicate the dashboard total
        drifted away from the library total the moment a file left the disk.
        """
        live = "status != 'missing'"

        total = self.query_one(f"SELECT COUNT(*) as cnt FROM books WHERE {live}")["cnt"]
        total_size = self.query_one(
            f"SELECT COALESCE(SUM(size), 0) as s FROM books WHERE {live}"
        )["s"]

        by_type = self.query(
            f"SELECT file_type, COUNT(*) as cnt FROM books WHERE {live} GROUP BY file_type"
        )

        by_status = self.query(
            f"SELECT reading_status, COUNT(*) as cnt FROM books WHERE {live} GROUP BY reading_status"
        )

        with_cover = self.query_one(
            f"SELECT COUNT(*) as cnt FROM books WHERE {live} AND cover_path IS NOT NULL AND cover_path != ''"
        )["cnt"]

        with_description = self.query_one(
            f"SELECT COUNT(*) as cnt FROM books WHERE {live} AND description IS NOT NULL AND description != ''"
        )["cnt"]

        with_embeddings = self.query_one(
            f"SELECT COUNT(*) as cnt FROM embeddings WHERE book_id IN (SELECT id FROM books WHERE {live})"
        )["cnt"]

        avg_rating = self.query_one(
            f"SELECT AVG(user_rating) as avg FROM books WHERE {live} AND user_rating IS NOT NULL"
        )["avg"]

        # `duplicate_of` is computed by the pipeline, stored, indexed and
        # present in the TypeScript type — and was never rendered anywhere.
        duplicates = self.query_one(
            f"SELECT COUNT(*) as cnt FROM books "
            f"WHERE {live} AND duplicate_of IS NOT NULL AND duplicate_of != ''"
        )["cnt"]

        categories = self._count_json_array_field("categories", live)
        themes = self._count_json_array_field("themes", live)

        # Year histogram
        year_rows = self.query(
            f"SELECT publication_year, COUNT(*) as cnt FROM books WHERE {live} AND publication_year IS NOT NULL GROUP BY publication_year ORDER BY publication_year"
        )

        # Recently processed
        recent = self.query(
            f"SELECT id, title, author_primary, cover_path, last_processed FROM books WHERE {live} ORDER BY last_processed DESC LIMIT 10"
        )

        return {
            "total_books": total,
            "total_size_bytes": total_size,
            "by_type": {r["file_type"]: r["cnt"] for r in by_type},
            "by_status": {r["reading_status"]: r["cnt"] for r in by_status},
            "with_cover": with_cover,
            "with_description": with_description,
            "with_embeddings": with_embeddings,
            "duplicates": duplicates,
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
        with self._lock:
            self.conn.execute("""
                INSERT OR REPLACE INTO embeddings (book_id, content_embedding, metadata_embedding)
                VALUES (?, ?, ?)
            """, (book_id, content_emb, metadata_emb))
            self.conn.commit()

    def get_all_embeddings(self) -> list[tuple[str, Optional[bytes], Optional[bytes]]]:
        """Get all embeddings for loading into memory."""
        rows = self.query("SELECT book_id, content_embedding, metadata_embedding FROM embeddings")
        return [(r["book_id"], r["content_embedding"], r["metadata_embedding"]) for r in rows]

    def get_book_count(self) -> int:
        return self.query_one("SELECT COUNT(*) as cnt FROM books WHERE status != 'missing'")["cnt"]

    def has_embedding(self, book_id: str) -> bool:
        return self.query_one("SELECT 1 FROM embeddings WHERE book_id = ?", (book_id,)) is not None
