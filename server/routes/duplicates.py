"""
Duplicate resolution (Part 5).

    GET    /api/duplicates              groups, canonical first
    POST   /api/duplicates/{id}/keep    make this copy the canonical one
    DELETE /api/duplicates/{id}         dismiss: this is not a duplicate

`catalog/duplicate_detector.py` and the `duplicate_of` column have existed
since the pipeline shipped, and nothing surfaced them — the detector marked at
least two literal duplicates in `epubs/` and no screen ever said so.

**Nothing here deletes a file.** Resolving a duplicate reassigns `duplicate_of`
and hides a copy from the library view. Deciding which of two files on disk to
destroy is the user's call to make in a file manager, and a wrong call is not
recoverable from inside this app.
"""
import json

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/duplicates", tags=["duplicates"])

# What the card shows so a human can tell the copies apart at a glance. Size
# and page count are the two that actually differ between a good scan and a bad
# one; the rest is identical by definition of "duplicate".
GROUP_FIELDS = (
    "id", "title", "subtitle", "author_primary", "authors", "publication_year",
    "file_name", "file_path", "file_type", "size", "page_count", "language",
    "cover_path", "has_text", "ocr_required", "duplicate_of",
)


def _row_to_book(db, book_id: str) -> dict:
    book = db.get_book(book_id)
    if not book:
        return {}
    out = {k: book.get(k) for k in GROUP_FIELDS}
    out["cover_url"] = book.get("cover_url")
    if isinstance(out.get("authors"), str):
        try:
            out["authors"] = json.loads(out["authors"])
        except ValueError:
            out["authors"] = []
    return out


def _duplicate_groups(db, limit: int = 100) -> dict:
    """
    Duplicate groups: the canonical book, then every copy pointing at it.

    Grouped by the canonical id rather than returned flat, because "these two
    files are the same book" is the unit a person acts on.

    A plain function rather than the route handler, because the route handler
    is not one: its `limit` default is a FastAPI `Query` object, and calling it
    from `keep_copy` slid that object into a list slice.
    """
    rows = db.query(
        "SELECT duplicate_of, id FROM books "
        "WHERE duplicate_of IS NOT NULL AND duplicate_of != '' AND status != 'missing' "
        "ORDER BY duplicate_of"
    )

    grouped: dict[str, list[str]] = {}
    for canonical_id, book_id in rows:
        grouped.setdefault(canonical_id, []).append(book_id)

    groups = []
    for canonical_id, copies in list(grouped.items())[:limit]:
        canonical = _row_to_book(db, canonical_id)
        if not canonical:
            # The canonical book was removed from the catalog and its copies
            # now point at nothing. Report the group anyway — otherwise those
            # books are marked as duplicates of an invisible record and there
            # is no screen on which to unmark them.
            members = [_row_to_book(db, c) for c in copies]
            groups.append({
                "canonical_id": canonical_id,
                "canonical": None,
                "orphaned": True,
                "copies": [m for m in members if m],
            })
            continue
        groups.append({
            "canonical_id": canonical_id,
            "canonical": canonical,
            "orphaned": False,
            "copies": [b for b in (_row_to_book(db, c) for c in copies) if b],
        })

    return {"groups": groups, "total": len(grouped)}


@router.get("")
def list_duplicates(request: Request, limit: int = Query(100, ge=1, le=500)):
    """Duplicate groups, canonical first."""
    return _duplicate_groups(request.app.state.db, limit)


@router.post("/{book_id}/keep")
def keep_copy(book_id: str, request: Request):
    """
    Make `book_id` the canonical copy of its group.

    The whole group is repointed in one statement, including the book that was
    canonical before — a group with two canonical members, or with a chain of
    `duplicate_of` pointers, is a state nothing downstream expects.
    """
    db = request.app.state.db
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")

    canonical_id = book.get("duplicate_of") or book_id
    with db._lock:
        db.conn.execute(
            "UPDATE books SET duplicate_of = ? "
            "WHERE id = ? OR duplicate_of = ? OR id = ?",
            (book_id, canonical_id, canonical_id, book_id),
        )
        db.conn.execute("UPDATE books SET duplicate_of = NULL WHERE id = ?", (book_id,))
        db.conn.commit()

    return {"canonical_id": book_id, "groups": _duplicate_groups(db)["groups"]}


@router.delete("/{book_id}", status_code=200)
def dismiss_duplicate(book_id: str, request: Request):
    """Not a duplicate after all: clear the mark and leave both books in the library."""
    db = request.app.state.db
    if not db.get_book(book_id):
        raise HTTPException(404, "Book not found")
    with db._lock:
        db.conn.execute("UPDATE books SET duplicate_of = NULL WHERE id = ?", (book_id,))
        db.conn.commit()
    return {"book_id": book_id, "duplicate_of": None}
