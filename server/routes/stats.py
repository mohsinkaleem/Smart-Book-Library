"""Stats dashboard routes."""
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("")
def get_stats(request: Request):
    return request.app.state.db.get_stats()


@router.get("/reading")
def get_reading_stats(request: Request):
    db = request.app.state.db
    rows = db.conn.execute(
        "SELECT reading_status, COUNT(*) as cnt FROM books GROUP BY reading_status"
    ).fetchall()
    return {r["reading_status"]: r["cnt"] for r in rows}
