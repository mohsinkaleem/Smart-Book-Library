"""
Highlights, bookmarks and margin notes.

The catalog had no annotation storage at all — the largest gap for a "smart"
library, and the one thing in it a human authors directly. `catalog.annotations`
owns the SQL; this module is the HTTP surface over it.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from catalog.schema import ANNOTATION_KINDS

router = APIRouter(prefix="/api/annotations", tags=["annotations"])

# A highlight carries the selected passage, which on a full page can be long.
# Cap it rather than storing an unbounded blob per annotation.
MAX_TEXT_CHARS = 8000
MAX_NOTE_CHARS = 8000


class AnnotationCreate(BaseModel):
    book_id: str
    kind: str = "highlight"
    text: str = ""
    note: str = ""
    color: str = "yellow"
    page: Optional[int] = Field(default=None, ge=1)
    cfi: str = ""
    anchor_text: str = ""


class AnnotationUpdate(BaseModel):
    kind: Optional[str] = None
    text: Optional[str] = None
    note: Optional[str] = None
    color: Optional[str] = None
    page: Optional[int] = Field(default=None, ge=1)
    cfi: Optional[str] = None
    anchor_text: Optional[str] = None


@router.get("")
def list_annotations(
    request: Request,
    book_id: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = Query(500, ge=1, le=2000),
):
    """Annotations in reading order, optionally scoped to one book or kind."""
    if kind and kind not in ANNOTATION_KINDS:
        raise HTTPException(422, f"Unknown kind {kind!r}")
    items = request.app.state.db.list_annotations(book_id=book_id, kind=kind, limit=limit)
    return {"annotations": items, "total": len(items)}


@router.post("", status_code=201)
def create_annotation(body: AnnotationCreate, request: Request):
    if body.kind not in ANNOTATION_KINDS:
        raise HTTPException(422, f"Unknown kind {body.kind!r}")

    db = request.app.state.db
    created = db.create_annotation(
        body.book_id,
        kind=body.kind,
        text=body.text[:MAX_TEXT_CHARS],
        note=body.note[:MAX_NOTE_CHARS],
        color=body.color,
        page=body.page,
        cfi=body.cfi,
        anchor_text=body.anchor_text,
    )
    # `create_annotation` returns None only when the book id does not resolve;
    # the kind was already validated above.
    if created is None:
        raise HTTPException(404, "Book not found")
    return created


@router.patch("/{annotation_id}")
def update_annotation(annotation_id: str, body: AnnotationUpdate, request: Request):
    fields = body.model_dump(exclude_none=True)
    if "kind" in fields and fields["kind"] not in ANNOTATION_KINDS:
        raise HTTPException(422, f"Unknown kind {fields['kind']!r}")
    if "text" in fields:
        fields["text"] = fields["text"][:MAX_TEXT_CHARS]
    if "note" in fields:
        fields["note"] = fields["note"][:MAX_NOTE_CHARS]

    updated = request.app.state.db.update_annotation(annotation_id, fields)
    if updated is None:
        raise HTTPException(404, "Annotation not found")
    return updated


@router.delete("/{annotation_id}", status_code=204)
def delete_annotation(annotation_id: str, request: Request):
    if not request.app.state.db.delete_annotation(annotation_id):
        raise HTTPException(404, "Annotation not found")
    return None
