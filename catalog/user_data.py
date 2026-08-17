"""
User-owned data: ratings, tags, favourites, reading progress and pinned
field corrections.

Kept in its own table so a pipeline run — or a full catalog rebuild — cannot
destroy it, and so a manual correction pins the
field as `source: "user"`, which `BookRecord.set_field` refuses to overwrite
(§M2). The `books` row keeps a mirror of these columns purely so existing
filter/sort queries keep working unchanged.

Both the pipeline store and the web server call these helpers, so the write
path exists once.
"""
import json
import sqlite3
from datetime import datetime
from typing import Any, Optional

USER_FIELDS = {
    "reading_status", "progress_percent", "reader_position", "user_rating",
    "user_tags", "favorite", "last_opened",
}

# Fields a human is allowed to pin. Pinning writes `source: "user"`,
# `confidence: 1.0` — no future run may overwrite them.
PINNABLE_FIELDS = {
    "title", "subtitle", "authors", "publisher", "publication_year",
    "isbn_10", "isbn_13", "language", "description", "summary",
    "categories", "themes", "keywords", "cover_path",
}

_JSON_FIELDS = {"user_tags", "authors", "categories", "themes", "keywords"}


def _encode(name: str, value: Any):
    if name == "favorite":
        return 1 if value else 0
    if name in _JSON_FIELDS:
        return json.dumps(value if value is not None else [], ensure_ascii=False)
    return value


def _decode_json(raw, default):
    if raw in (None, ""):
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default
    return parsed if isinstance(parsed, type(default)) else default


def _ensure_row(conn: sqlite3.Connection, book_id: str, file_path: Optional[str]):
    if file_path is None:
        row = conn.execute("SELECT file_path FROM books WHERE id = ?", (book_id,)).fetchone()
        file_path = row[0] if row else None
    conn.execute(
        """INSERT INTO user_data (book_id, file_path, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(book_id) DO UPDATE SET
               file_path = COALESCE(excluded.file_path, user_data.file_path)""",
        (book_id, file_path, datetime.now().isoformat(timespec="seconds")),
    )


def write_user_fields(
    conn: sqlite3.Connection,
    book_id: str,
    fields: dict,
    file_path: Optional[str] = None,
) -> dict:
    """Persist user-owned fields to `user_data` and mirror them into `books`."""
    updates = {k: _encode(k, v) for k, v in fields.items() if k in USER_FIELDS}
    if not updates:
        return {}

    _ensure_row(conn, book_id, file_path)
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE user_data SET {set_clause}, updated_at = ? WHERE book_id = ?",
        [*updates.values(), datetime.now().isoformat(timespec="seconds"), book_id],
    )
    conn.execute(
        f"UPDATE books SET {set_clause} WHERE id = ?",
        [*updates.values(), book_id],
    )
    conn.commit()
    return updates


def read_user_fields(conn: sqlite3.Connection, book_id: str) -> dict:
    row = conn.execute("SELECT * FROM user_data WHERE book_id = ?", (book_id,)).fetchone()
    if row is None:
        return {}
    data = dict(row)
    data["user_tags"] = _decode_json(data.get("user_tags"), [])
    data["field_overrides"] = _decode_json(data.get("field_overrides"), {})
    data["favorite"] = bool(data.get("favorite"))
    return data


def pin_field(
    conn: sqlite3.Connection,
    book_id: str,
    name: str,
    value: Any,
    file_path: Optional[str] = None,
) -> bool:
    """
    Record a human correction for one field.

    The value is written to the `books` row, stamped in `field_sources` as
    `user`/1.0, and stored in `user_data.field_overrides` so it is re-applied
    after any rebuild.
    """
    if name not in PINNABLE_FIELDS:
        return False

    now = datetime.now().isoformat(timespec="seconds")
    stamp = {"source": "user", "confidence": 1.0, "at": now}

    row = conn.execute(
        "SELECT field_sources, file_path FROM books WHERE id = ?", (book_id,)
    ).fetchone()
    if row is None:
        return False
    sources = _decode_json(row[0], {})
    sources[name] = stamp
    file_path = file_path or row[1]

    conn.execute(
        f"UPDATE books SET {name} = ?, field_sources = ? WHERE id = ?",
        (_encode(name, value), json.dumps(sources, ensure_ascii=False), book_id),
    )
    if name == "authors":
        primary = value[0] if isinstance(value, list) and value else ""
        conn.execute("UPDATE books SET author_primary = ? WHERE id = ?", (primary, book_id))

    _ensure_row(conn, book_id, file_path)
    overrides_row = conn.execute(
        "SELECT field_overrides FROM user_data WHERE book_id = ?", (book_id,)
    ).fetchone()
    overrides = _decode_json(overrides_row[0] if overrides_row else None, {})
    overrides[name] = {"value": value, "at": now}
    conn.execute(
        "UPDATE user_data SET field_overrides = ?, updated_at = ? WHERE book_id = ?",
        (json.dumps(overrides, ensure_ascii=False), now, book_id),
    )
    conn.commit()
    return True


def clear_review(conn: sqlite3.Connection, book_id: str, resolution: str = "confirmed") -> bool:
    """Mark a review-queue entry as handled."""
    cur = conn.execute(
        "UPDATE books SET needs_review = 0, review_reasons = ? WHERE id = ?",
        (json.dumps([f"resolved: {resolution}"], ensure_ascii=False), book_id),
    )
    conn.commit()
    return cur.rowcount > 0
