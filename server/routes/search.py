"""Search routes."""
from fastapi import APIRouter, Query, Request

from ..config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .params import Filters

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search_books(
    request: Request,
    filters: Filters,
    q: str = Query("", description="Search query"),
    # `hybrid`, matching `README.md` and the UI. The server defaulted to
    # `text` while the README documented `hybrid` and the UI sent `text`;
    # three places, two answers. Every book has embeddings, so hybrid has
    # real recall to add and still ranks exact matches first.
    mode: str = Query("hybrid", description="text|semantic|hybrid"),
    page: int = Query(1, ge=1),
    per_page: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    engine = request.app.state.search_engine
    # `search` belongs to the list endpoint; here the query is `q`.
    return engine.search(q, mode=mode, page=page, per_page=per_page,
                         **filters.as_dict(include_search=False))


@router.get("/suggest")
def suggest(request: Request, q: str = Query(""), limit: int = Query(8, ge=1, le=20)):
    return request.app.state.search_engine.suggest(q, limit=limit)
