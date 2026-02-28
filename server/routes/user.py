"""User field routes (ratings, tags, favorites, reading status)."""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/user", tags=["user"])


class UpdateFieldsRequest(BaseModel):
    user_rating: Optional[float] = None
    user_tags: Optional[list[str]] = None
    favorite: Optional[bool] = None
    reading_status: Optional[str] = None
    progress_percent: Optional[float] = None


@router.patch("/books/{book_id}")
def update_user_fields(book_id: str, body: UpdateFieldsRequest, request: Request):
    db = request.app.state.db
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "No fields to update")
    result = db.update_user_fields(book_id, fields)
    if not result:
        raise HTTPException(404, "Book not found")
    return result
