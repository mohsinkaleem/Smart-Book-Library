"""Search routes."""
from typing import Optional
from fastapi import APIRouter, Request, Query

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search_books(
    request: Request,
    q: str = Query("", description="Search query"),
    mode: str = Query("text", description="text|semantic|hybrid"),
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=200),
    file_type: Optional[str] = None,
    category: Optional[str] = None,
    theme: Optional[str] = None,
    language: Optional[str] = None,
    reading_status: Optional[str] = None,
    favorite: Optional[bool] = None,
):
    engine = request.app.state.search_engine
    filters = {}
    if file_type:
        filters["file_type"] = file_type
    if category:
        filters["category"] = category
    if theme:
        filters["theme"] = theme
    if language:
        filters["language"] = language
    if reading_status:
        filters["reading_status"] = reading_status
    if favorite:
        filters["favorite"] = favorite

    return engine.search(q, mode=mode, page=page, per_page=per_page, **filters)


@router.get("/suggest")
def suggest(request: Request, q: str = Query(""), limit: int = Query(8, ge=1, le=20)):
    engine = request.app.state.search_engine
    return engine.suggest(q, limit=limit)
