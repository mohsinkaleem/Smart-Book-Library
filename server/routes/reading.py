"""Reading view and LLM integration routes."""
import json
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from ..llm_service import analyze_text_stream, llm_status

router = APIRouter(prefix="/api/reading", tags=["reading"])


class CompareRequest(BaseModel):
    text: str
    book_id: Optional[str] = None
    limit: int = 5


class AnalyzeRequest(BaseModel):
    text: str
    book_id: Optional[str] = None
    action: str = "explain"  # explain|summarize|compare|critique|related


@router.get("/llm-status")
def get_llm_status():
    """
    Whether the Analysis buttons will work, and why not when they won't.

    This endpoint existed and nothing called it: the LLM panel offered its
    five buttons unconditionally and only failed on click, with a string in
    the response pane. The panel gates on this now.
    """
    return llm_status()


@router.get("/{book_id}/text")
def get_reading_text(book_id: str, request: Request):
    db = request.app.state.db
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    return {
        "id": book_id,
        "title": book.get("title", ""),
        "text": book.get("text_excerpt", ""),
    }


@router.post("/compare")
def compare_text(body: CompareRequest, request: Request):
    """
    Find passages in other books that resemble the selected text.

    Scored against the *content* embeddings. This used to call
    `semantic_search`, which compares against the metadata embeddings —
    "Title: … Authors: … Themes: …" — so a selected paragraph of prose was
    matched on topic labels rather than on the prose itself.
    """
    similarity = request.app.state.similarity
    if not similarity.has_embeddings:
        return {"matches": [], "message": "No embeddings available"}

    query_emb = similarity.encode_query(body.text)
    if query_emb is None:
        return {"matches": [], "message": "Failed to encode query"}

    matches = similarity.passage_search(query_emb, limit=body.limit + 1)
    db = request.app.state.db
    results = []
    for book_id, score in matches:
        if book_id == body.book_id:
            continue
        book = db.get_book(book_id)
        if book:
            results.append({
                "book_id": book_id,
                "title": book.get("title", ""),
                "author": book.get("author_primary", ""),
                "excerpt": (book.get("text_excerpt", "") or "")[:300],
                "similarity": round(score * 100, 1),
                "cover_url": book.get("cover_url"),
            })
        if len(results) >= body.limit:
            break
    return {"matches": results}


@router.post("/analyze")
async def analyze(body: AnalyzeRequest, request: Request):
    """Streaming LLM analysis via SSE."""
    book_title = ""
    if body.book_id:
        db = request.app.state.db
        book = db.get_book(body.book_id)
        if book:
            book_title = book.get("title", "")

    async def event_stream():
        async for token in analyze_text_stream(body.text, body.action, book_title):
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
