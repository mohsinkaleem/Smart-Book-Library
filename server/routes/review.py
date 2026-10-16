"""
Review queue routes.

11% of records were wrong and there was no way to see that, and no way to
correct one. A record the verification gate could not confirm now surfaces
here; a human correction is pinned as `source: "user"`, `confidence: 1.0`, and
no future pipeline run may overwrite it.

The queue is split in two (see `bucket`): "not in OpenLibrary" is a fact about
the provider, not a defect to confirm, and mixing the two put 153 unactionable
records in front of the few that needed a person.
"""
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from catalog.user_data import PINNABLE_FIELDS

router = APIRouter(prefix="/api/review", tags=["review"])


class PinFieldRequest(BaseModel):
    field: str
    value: Any


class ResolveRequest(BaseModel):
    resolution: Optional[str] = "confirmed"


@router.get("/queue")
def review_queue(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    bucket: str = Query("review", pattern="^(review|unidentified)$"),
):
    """
    Records awaiting attention, lowest confidence first.

    Two buckets, because they ask for different things. `review` holds the
    records a human's judgement would change — a borderline match we declined
    to trust, a record with no title at all. `unidentified` holds the ones no
    provider could name; there is nothing to confirm, but a title read off
    the cover is still worth pinning. The response carries both counts so the
    caller can show them side by side.
    """
    return request.app.state.db.get_review_queue(
        page=page, per_page=per_page, bucket=bucket
    )


@router.post("/{book_id}/pin")
def pin_field(book_id: str, body: PinFieldRequest, request: Request):
    """Pin a corrected value so no future run can overwrite it."""
    if body.field not in PINNABLE_FIELDS:
        raise HTTPException(400, f"Field '{body.field}' cannot be pinned")
    book = request.app.state.db.pin_field(book_id, body.field, body.value)
    if not book:
        raise HTTPException(404, "Book not found")
    return book


@router.post("/{book_id}/resolve")
def resolve(book_id: str, body: ResolveRequest, request: Request):
    """Mark a record as reviewed."""
    book = request.app.state.db.resolve_review(book_id, body.resolution or "confirmed")
    if not book:
        raise HTTPException(404, "Book not found")
    return book
