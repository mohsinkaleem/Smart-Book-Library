"""
Reading sessions and EPUB locations (Part 5, §2.1).

    POST /api/sessions/heartbeat        the reader says "still reading"
    GET  /api/sessions                  raw sessions, newest first
    GET  /api/sessions/stats            time, pages/week, streaks — for the Dashboard
    GET  /api/books/{id}/locations      cached EPUB locations index
    POST /api/books/{id}/locations      store one the reader generated
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["sessions"])

# `book.locations.save()` is a JSON array of CFIs — around 60 bytes each, so a
# long book runs to a few hundred KB. Capped so a malformed client cannot post
# an unbounded blob into the catalog.
MAX_LOCATIONS_CHARS = 4_000_000


class Heartbeat(BaseModel):
    book_id: str
    page: Optional[int] = Field(default=None, ge=1)


class LocationsPayload(BaseModel):
    locations: str
    total: int = Field(ge=0)
    chars: int = Field(default=1024, ge=1)


@router.post("/api/sessions/heartbeat")
def heartbeat(body: Heartbeat, request: Request):
    """
    Extend the current reading session, or open one.

    Called on a timer by the reader rather than on open and close: there is no
    reliable "closed the laptop" event, and a session closed only on unmount
    reports a fourteen-hour reading day. See `catalog.reading_sessions`.
    """
    session = request.app.state.db.session_heartbeat(body.book_id, body.page)
    if session is None:
        raise HTTPException(404, "Book not found")
    return session


@router.get("/api/sessions")
def list_sessions(
    request: Request,
    book_id: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    items = request.app.state.db.list_sessions(book_id=book_id, limit=limit)
    return {"sessions": items, "total": len(items)}


@router.get("/api/sessions/stats")
def session_stats(request: Request, days: int = Query(30, ge=1, le=365)):
    """Reading time, pages per week and streaks over a window."""
    return request.app.state.db.session_stats(days=days)


@router.get("/api/books/{book_id}/locations")
def get_locations(book_id: str, request: Request):
    """
    The cached EPUB locations index, or `generated: false` if there is none.

    Generating it walks the whole book and costs seconds, which is why EPUB
    progress was an approximate spine ratio. The reader generates it once in
    the background on first open and posts it back here; every later open gets
    exact "page X of Y" for free.
    """
    cached = request.app.state.db.get_epub_locations(book_id)
    if cached is None:
        return {"generated": False, "locations": "", "total": 0}
    return {"generated": True, **cached}


@router.post("/api/books/{book_id}/locations", status_code=201)
def store_locations(book_id: str, body: LocationsPayload, request: Request):
    db = request.app.state.db
    if db.get_book(book_id) is None:
        raise HTTPException(404, "Book not found")
    if len(body.locations) > MAX_LOCATIONS_CHARS:
        raise HTTPException(413, "Locations index is too large to store")
    db.store_epub_locations(book_id, body.locations, body.total, body.chars)
    return {"generated": True, "total": body.total}
