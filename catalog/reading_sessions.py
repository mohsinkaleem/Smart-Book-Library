"""
Reading sessions (Part 5).

`progress_percent` and `reader_position` record *where* a reader is. Nothing
recorded *when*, or for how long, so pages/week, streaks and time-to-finish
were all unanswerable and the Dashboard had nothing but counts to show.

**Sessions are heartbeat-closed, not close-closed.** The obvious design — open
on mount, close on unmount — loses to the way people actually stop reading,
which is closing the laptop. There is no unmount event for that, and a session
left open reports a fourteen-hour reading day. So the reader beats every
`HEARTBEAT_SECONDS`, each beat moves `ended_at` forward, and a beat that
arrives after a gap longer than `SESSION_GAP_SECONDS` starts a new session
instead of extending the abandoned one. The worst case is losing the last
heartbeat interval, not gaining a night.
"""
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Optional

# How often the reader is expected to beat. Also the granularity of the worst
# case above: a session abandoned mid-interval loses at most this much.
HEARTBEAT_SECONDS = 60

# A beat further than this from the last one is a new session. Generous enough
# to survive a phone call, short enough that lunch does not become reading.
SESSION_GAP_SECONDS = 15 * 60

# Sessions shorter than this are page-flips, not reading, and would otherwise
# pad the streak with every accidental click into a book.
MIN_SESSION_SECONDS = 30


def _now() -> datetime:
    return datetime.now()


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _parse(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _rows(conn: sqlite3.Connection, sql: str, params=()) -> list[sqlite3.Row]:
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    return cur.execute(sql, params).fetchall()


def heartbeat(
    conn: sqlite3.Connection, book_id: str, page: Optional[int] = None
) -> Optional[dict]:
    """
    Record that this book is being read right now.

    Extends the open session for the book when one is recent enough, otherwise
    opens a new one. Returns the session row, or None for an unknown book.
    """
    book = conn.execute("SELECT file_path FROM books WHERE id = ?", (book_id,)).fetchone()
    if book is None:
        return None

    now = _now()
    latest = _rows(
        conn,
        "SELECT * FROM reading_sessions WHERE book_id = ? ORDER BY ended_at DESC LIMIT 1",
        (book_id,),
    )
    if latest:
        session = latest[0]
        ended = _parse(session["ended_at"])
        if ended and (now - ended).total_seconds() <= SESSION_GAP_SECONDS:
            started = _parse(session["started_at"]) or now
            start_page = session["start_page"]
            end_page = page if page is not None else session["end_page"]
            conn.execute(
                "UPDATE reading_sessions SET ended_at = ?, seconds = ?, end_page = ?, "
                "       pages = ? WHERE id = ?",
                (
                    _iso(now),
                    int((now - started).total_seconds()),
                    end_page,
                    _page_span(start_page, end_page),
                    session["id"],
                ),
            )
            conn.commit()
            return get_session(conn, session["id"])

    session_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO reading_sessions (id, book_id, file_path, started_at, ended_at, "
        "                              seconds, start_page, end_page, pages) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (session_id, book_id, book[0], _iso(now), _iso(now), 0, page, page, 0),
    )
    conn.commit()
    return get_session(conn, session_id)


def _page_span(start: Optional[int], end: Optional[int]) -> int:
    """
    Pages covered, never negative.

    A reader who pages backwards to re-read has not un-read anything, and
    `max(0, …)` is the difference between a sane weekly total and one that goes
    down when someone checks an earlier chapter.
    """
    if start is None or end is None:
        return 0
    return max(0, end - start)


def get_session(conn: sqlite3.Connection, session_id: str) -> Optional[dict]:
    rows = _rows(conn, "SELECT * FROM reading_sessions WHERE id = ?", (session_id,))
    return dict(rows[0]) if rows else None


def list_sessions(
    conn: sqlite3.Connection, book_id: Optional[str] = None, limit: int = 200
) -> list[dict]:
    sql = "SELECT * FROM reading_sessions"
    params: list = []
    if book_id:
        sql += " WHERE book_id = ?"
        params.append(book_id)
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in _rows(conn, sql, params)]


def stats(conn: sqlite3.Connection, days: int = 30) -> dict:
    """
    Reading time and streaks, for the Dashboard.

    Only sessions past `MIN_SESSION_SECONDS` count anywhere here.
    """
    cutoff = _iso(_now() - timedelta(days=days))
    rows = _rows(
        conn,
        "SELECT book_id, started_at, seconds, pages FROM reading_sessions "
        "WHERE seconds >= ? ORDER BY started_at",
        (MIN_SESSION_SECONDS,),
    )

    by_day: dict[str, dict] = {}
    total_seconds = 0
    total_pages = 0
    recent_seconds = 0
    recent_pages = 0
    books_touched: set[str] = set()

    for row in rows:
        day = (row["started_at"] or "")[:10]
        if not day:
            continue
        bucket = by_day.setdefault(day, {"date": day, "seconds": 0, "pages": 0, "books": set()})
        bucket["seconds"] += row["seconds"] or 0
        bucket["pages"] += row["pages"] or 0
        bucket["books"].add(row["book_id"])
        total_seconds += row["seconds"] or 0
        total_pages += row["pages"] or 0
        if row["started_at"] >= cutoff:
            recent_seconds += row["seconds"] or 0
            recent_pages += row["pages"] or 0
            books_touched.add(row["book_id"])

    days_sorted = sorted(by_day)
    daily = [
        {"date": d, "seconds": by_day[d]["seconds"], "pages": by_day[d]["pages"],
         "books": len(by_day[d]["books"])}
        for d in days_sorted if d >= cutoff[:10]
    ]

    return {
        "total_seconds": total_seconds,
        "total_pages": total_pages,
        "sessions": len(rows),
        "window_days": days,
        "window_seconds": recent_seconds,
        "window_pages": recent_pages,
        "window_books": len(books_touched),
        "pages_per_week": round(recent_pages / max(days / 7, 1), 1),
        "current_streak": _streak(days_sorted),
        "longest_streak": _longest_streak(days_sorted),
        "daily": daily,
    }


def _streak(days_sorted: list[str]) -> int:
    """
    Consecutive days up to today.

    A streak that ended yesterday is still live — the day is not over. One that
    ended the day before is not.
    """
    if not days_sorted:
        return 0
    have = set(days_sorted)
    today = _now().date()
    if _iso_date(today) not in have and _iso_date(today - timedelta(days=1)) not in have:
        return 0
    cursor = today if _iso_date(today) in have else today - timedelta(days=1)
    count = 0
    while _iso_date(cursor) in have:
        count += 1
        cursor -= timedelta(days=1)
    return count


def _longest_streak(days_sorted: list[str]) -> int:
    if not days_sorted:
        return 0
    best = run = 1
    previous = None
    for day in days_sorted:
        current = _parse(day)
        if current is None:
            continue
        if previous is not None and (current - previous).days == 1:
            run += 1
        elif previous is not None and (current - previous).days > 1:
            run = 1
        best = max(best, run)
        previous = current
    return best


def _iso_date(value) -> str:
    return value.isoformat()[:10]


def book_time(conn: sqlite3.Connection) -> dict[str, int]:
    """Seconds spent per book, for the book detail page."""
    return {
        r[0]: int(r[1] or 0)
        for r in conn.execute(
            "SELECT book_id, SUM(seconds) FROM reading_sessions "
            "WHERE seconds >= ? GROUP BY book_id",
            (MIN_SESSION_SECONDS,),
        )
    }


def relink_orphans(conn: sqlite3.Connection) -> int:
    """Re-point sessions at rebuilt book ids, as `annotations.relink_orphans` does."""
    rows = conn.execute(
        "SELECT s.id, b.id FROM reading_sessions s JOIN books b ON b.file_path = s.file_path "
        "WHERE s.file_path IS NOT NULL AND s.file_path != '' "
        "AND s.book_id NOT IN (SELECT id FROM books)"
    ).fetchall()
    for session_id, new_book_id in rows:
        conn.execute("UPDATE reading_sessions SET book_id = ? WHERE id = ?",
                     (new_book_id, session_id))
    if rows:
        conn.commit()
    return len(rows)
