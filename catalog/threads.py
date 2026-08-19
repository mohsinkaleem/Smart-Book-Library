"""
Passage-scoped LLM threads (§4.2).

Two gaps the roadmap names as one: "no follow-up" and "nothing is saved". They
are one because the fix is the same object. A thread pins the passage and the
retrieved context once, so a follow-up question does not have to restate what
"it" refers to — and because that frame is stored rather than assembled per
request, the exchange survives closing the reader.

Lives beside `annotations` and `user_data`, and for the same reason: this is
data a human produced, so a pipeline run or a full rebuild must not be able to
destroy it. `file_path` is stored alongside `book_id` because book ids are
content hashes — re-encoding a PDF gives it a new id and would otherwise
orphan every thread against it.
"""
import sqlite3
import uuid
from datetime import datetime
from typing import Optional

ROLES = ("user", "assistant")

# What a thread is called in the list before anyone renames it: the opening
# question, or failing that the passage. Long enough to tell two apart.
TITLE_CHARS = 80


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _rows(conn: sqlite3.Connection, sql: str, params=()) -> list[sqlite3.Row]:
    """Query with a row factory scoped to this cursor — see `annotations._rows`."""
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    return cur.execute(sql, params).fetchall()


def make_title(text: str) -> str:
    return " ".join((text or "").split())[:TITLE_CHARS]


def create_thread(
    conn: sqlite3.Connection,
    book_id: str,
    passage: str = "",
    surrounding: str = "",
    context: str = "",
    title: str = "",
    page: Optional[int] = None,
    cfi: str = "",
    file_path: Optional[str] = None,
) -> Optional[dict]:
    """Open a thread against a passage. Returns the stored row, or None for an unknown book."""
    row = conn.execute("SELECT file_path FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        return None
    now = _now()
    thread_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO llm_threads (id, book_id, file_path, title, passage, surrounding, "
        "                         context, page, cfi, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            thread_id, book_id, file_path or row[0], title or make_title(passage),
            passage, surrounding, context, page, cfi, now, now,
        ),
    )
    conn.commit()
    return get_thread(conn, thread_id)


def get_thread(conn: sqlite3.Connection, thread_id: str) -> Optional[dict]:
    rows = _rows(conn, "SELECT * FROM llm_threads WHERE id = ?", (thread_id,))
    if not rows:
        return None
    thread = dict(rows[0])
    thread["messages"] = list_messages(conn, thread_id)
    return thread


def list_threads(
    conn: sqlite3.Connection, book_id: Optional[str] = None, limit: Optional[int] = None
) -> list[dict]:
    """Threads newest-updated first, each with its message count but not its messages."""
    sql = [
        "SELECT t.*, (SELECT COUNT(*) FROM llm_messages m WHERE m.thread_id = t.id) "
        "AS message_count FROM llm_threads t"
    ]
    params: list = []
    if book_id:
        sql.append("WHERE t.book_id = ?")
        params.append(book_id)
    sql.append("ORDER BY t.updated_at DESC")
    if limit:
        sql.append("LIMIT ?")
        params.append(limit)
    return [dict(r) for r in _rows(conn, " ".join(sql), params)]


def update_thread(conn: sqlite3.Connection, thread_id: str, fields: dict) -> Optional[dict]:
    """
    Rename a thread. Only the title is editable.

    The passage and context are the thread's identity: changing them would
    leave every existing answer in the transcript grounded in material that is
    no longer shown, which reads as the model having made it up.
    """
    title = fields.get("title")
    if title is None:
        return get_thread(conn, thread_id)
    conn.execute(
        "UPDATE llm_threads SET title = ?, updated_at = ? WHERE id = ?",
        (make_title(title), _now(), thread_id),
    )
    conn.commit()
    return get_thread(conn, thread_id)


def delete_thread(conn: sqlite3.Connection, thread_id: str) -> bool:
    cur = conn.execute("DELETE FROM llm_threads WHERE id = ?", (thread_id,))
    # The ON DELETE CASCADE only fires with `PRAGMA foreign_keys=ON`, which the
    # server sets and a bare sqlite3 connection does not. Delete explicitly so
    # this is true either way rather than leaving orphaned messages behind.
    conn.execute("DELETE FROM llm_messages WHERE thread_id = ?", (thread_id,))
    conn.commit()
    return cur.rowcount > 0


def add_message(
    conn: sqlite3.Connection, thread_id: str, role: str, content: str, action: str = ""
) -> Optional[dict]:
    if role not in ROLES:
        return None
    if conn.execute("SELECT 1 FROM llm_threads WHERE id = ?", (thread_id,)).fetchone() is None:
        return None
    now = _now()
    message_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO llm_messages (id, thread_id, role, content, action, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (message_id, thread_id, role, content, action, now),
    )
    conn.execute("UPDATE llm_threads SET updated_at = ? WHERE id = ?", (now, thread_id))
    conn.commit()
    rows = _rows(conn, "SELECT * FROM llm_messages WHERE id = ?", (message_id,))
    return dict(rows[0]) if rows else None


def list_messages(conn: sqlite3.Connection, thread_id: str) -> list[dict]:
    return [
        dict(r) for r in _rows(
            conn,
            "SELECT * FROM llm_messages WHERE thread_id = ? ORDER BY created_at, rowid",
            (thread_id,),
        )
    ]


def relink_orphans(conn: sqlite3.Connection) -> int:
    """
    Re-point threads whose `book_id` no longer exists at the book now holding
    their path. Same contract as `annotations.relink_orphans`.
    """
    rows = conn.execute(
        "SELECT t.id, b.id FROM llm_threads t JOIN books b ON b.file_path = t.file_path "
        "WHERE t.file_path IS NOT NULL AND t.file_path != '' "
        "AND t.book_id NOT IN (SELECT id FROM books)"
    ).fetchall()
    for thread_id, new_book_id in rows:
        conn.execute("UPDATE llm_threads SET book_id = ? WHERE id = ?", (new_book_id, thread_id))
    if rows:
        conn.commit()
    return len(rows)
