"""
Highlights, bookmarks and margin notes.

Lives beside `user_data` and for the same reason: this is the only data in the
catalog a human typed, and a pipeline run — or a full rebuild — must not be
able to destroy it. Both the pipeline store and the web server call these
helpers, so the write path exists once.

Anchoring is per-format and deliberately imperfect (§1.5 of the features doc):
a PDF highlight is a page number plus a short `anchor_text` needle, an EPUB
highlight is a CFI with the same needle as fallback. Neither is exact after the
underlying file changes, and the fallback search is what makes that survivable
rather than silent.
"""
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Optional

from .schema import ANNOTATION_KINDS

# The needle used to relocate a highlight when its page or CFI no longer
# resolves. Long enough to be unique inside a page, short enough to survive
# the whitespace and ligature differences between two renderings of one book.
ANCHOR_TEXT_CHARS = 60

# Fields a client may write. `id`, `book_id` and `created_at` are set once at
# creation and are not patchable — an update that could move an annotation to
# a different book is a bug surface with no feature behind it.
EDITABLE_FIELDS = {"kind", "text", "note", "color", "page", "cfi", "anchor_text"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def make_anchor_text(text: str) -> str:
    """The leading `ANCHOR_TEXT_CHARS` of `text`, whitespace collapsed."""
    return " ".join((text or "").split())[:ANCHOR_TEXT_CHARS]


def _rows(conn: sqlite3.Connection, sql: str, params=()) -> list[sqlite3.Row]:
    """
    Query with a row factory scoped to this cursor.

    Setting `conn.row_factory` here would change how every *other* caller of
    this connection sees its results — `catalog.store` reads tuples by index.
    A cursor carries its own factory, so the mapping access below is local.
    """
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    return cur.execute(sql, params).fetchall()


def _row_to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["page"] = int(data["page"]) if data.get("page") is not None else None
    return data


def create_annotation(
    conn: sqlite3.Connection,
    book_id: str,
    kind: str = "highlight",
    text: str = "",
    note: str = "",
    color: str = "yellow",
    page: Optional[int] = None,
    cfi: str = "",
    anchor_text: str = "",
    file_path: Optional[str] = None,
) -> Optional[dict]:
    """
    Store one annotation. Returns the stored row, or None for an unknown book.

    `file_path` is resolved from the book when not given, so it is recorded
    even though no caller passes it — that is the column a rebuild relinks on.
    """
    if kind not in ANNOTATION_KINDS:
        return None

    row = conn.execute(
        "SELECT file_path FROM books WHERE id = ?", (book_id,)
    ).fetchone()
    if row is None:
        return None
    file_path = file_path or row[0]

    now = _now()
    ann_id = uuid.uuid4().hex
    conn.execute(
        """INSERT INTO annotations
               (id, book_id, file_path, kind, text, note, color,
                page, cfi, anchor_text, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ann_id, book_id, file_path, kind, text, note, color,
            page, cfi, anchor_text or make_anchor_text(text), now, now,
        ),
    )
    conn.commit()
    return get_annotation(conn, ann_id)


def get_annotation(conn: sqlite3.Connection, ann_id: str) -> Optional[dict]:
    rows = _rows(conn, "SELECT * FROM annotations WHERE id = ?", (ann_id,))
    return _row_to_dict(rows[0]) if rows else None


def list_annotations(
    conn: sqlite3.Connection,
    book_id: Optional[str] = None,
    kind: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Annotations, newest first within a book but ordered by position across a
    book so the sidebar reads in reading order.

    PDFs sort by page and EPUBs by CFI; `page` is NULL for EPUBs and CFIs are
    empty for PDFs, so one ORDER BY covers both without a branch.
    """
    where = []
    params: list[Any] = []
    if book_id:
        where.append("book_id = ?")
        params.append(book_id)
    if kind:
        where.append("kind = ?")
        params.append(kind)

    sql = "SELECT * FROM annotations"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY page IS NULL, page ASC, cfi ASC, created_at ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    return [_row_to_dict(r) for r in _rows(conn, sql, params)]


def update_annotation(conn: sqlite3.Connection, ann_id: str, fields: dict) -> Optional[dict]:
    """Patch an existing annotation. Unknown fields are ignored."""
    updates = {k: v for k, v in fields.items() if k in EDITABLE_FIELDS}
    if "kind" in updates and updates["kind"] not in ANNOTATION_KINDS:
        return None
    if not updates:
        return get_annotation(conn, ann_id)

    if conn.execute("SELECT 1 FROM annotations WHERE id = ?", (ann_id,)).fetchone() is None:
        return None

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE annotations SET {set_clause}, updated_at = ? WHERE id = ?",
        [*updates.values(), _now(), ann_id],
    )
    conn.commit()
    return get_annotation(conn, ann_id)


def delete_annotation(conn: sqlite3.Connection, ann_id: str) -> bool:
    cur = conn.execute("DELETE FROM annotations WHERE id = ?", (ann_id,))
    conn.commit()
    return cur.rowcount > 0


def counts_by_book(conn: sqlite3.Connection) -> dict[str, int]:
    """`{book_id: count}` — for badging the library without N queries."""
    return {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT book_id, COUNT(*) FROM annotations GROUP BY book_id"
        ).fetchall()
    }


def relink_orphans(conn: sqlite3.Connection) -> int:
    """
    Re-point annotations whose `book_id` no longer exists at the book that now
    holds their `file_path`.

    A rebuild derives ids from file content, so re-encoding a PDF gives it a
    new id and orphans every highlight in it. The path is what survived.
    Returns the number relinked.
    """
    rows = conn.execute(
        """SELECT a.id, b.id AS new_book_id
             FROM annotations a
             JOIN books b ON b.file_path = a.file_path
            WHERE a.file_path IS NOT NULL
              AND a.book_id NOT IN (SELECT id FROM books)"""
    ).fetchall()
    for ann_id, new_book_id in rows:
        conn.execute(
            "UPDATE annotations SET book_id = ?, updated_at = ? WHERE id = ?",
            (new_book_id, _now(), ann_id),
        )
    if rows:
        conn.commit()
    return len(rows)
