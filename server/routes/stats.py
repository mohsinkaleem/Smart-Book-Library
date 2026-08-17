"""Stats dashboard routes."""
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("")
def get_stats(request: Request):
    # `GET /api/stats/reading` used to live here too — never called, and its
    # per-status counts are already in this response as `by_status`.
    return request.app.state.db.get_stats()
