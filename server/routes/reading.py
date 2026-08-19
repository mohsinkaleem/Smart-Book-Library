"""Reading view and LLM integration routes."""
import json
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from ..llm_service import analyze_text_stream, llm_status

router = APIRouter(prefix="/api/reading", tags=["reading"])

# Actions whose prompt is grounded in retrieved material. The other three
# ("explain", "summarize", "critique") are about the passage itself, and
# retrieval for them would only cost a matmul and dilute the prompt.
RETRIEVAL_ACTIONS = {"compare", "related"}

# Per-match excerpt length in the LLM context block. Long enough to carry an
# argument, short enough that five of them fit inside `PROMPT_MAX_CHARS`.
CONTEXT_EXCERPT_CHARS = 600
CONTEXT_MATCH_LIMIT = 4

# What the match card shows. Long enough to recognise the argument, short
# enough that five cards do not become the page.
MATCH_EXCERPT_CHARS = 600


class CompareRequest(BaseModel):
    text: str
    book_id: Optional[str] = None
    limit: int = 5


class AnalyzeRequest(BaseModel):
    text: str
    book_id: Optional[str] = None
    action: str = "explain"  # explain|summarize|compare|critique|related
    # Prose either side of the selection on the same page, sent by the reader.
    # A paragraph read in isolation loses the argument it belongs to.
    surrounding: Optional[str] = None


def _book_meta(book: dict) -> str:
    """Author, year, categories and themes, as one line for the prompt."""
    if not book:
        return ""
    parts = []
    if book.get("author_primary"):
        parts.append(str(book["author_primary"]))
    if book.get("publication_year"):
        parts.append(str(book["publication_year"]))
    for field in ("categories", "themes"):
        raw = book.get(field) or []
        values = json.loads(raw) if isinstance(raw, str) else raw
        if values:
            parts.append(", ".join(str(v) for v in values[:4]))
    return " · ".join(parts)


def _passage_matches(request: Request, text: str, book_id: Optional[str], limit: int) -> list[dict]:
    """
    The real matching passages, from the chunk index.

    This is §1.9.2 — the existing feature finally telling the truth. `excerpt`
    is the passage that actually matched, `page` is where it sits, and
    `deep_link` puts the reader on it.
    """
    from ..passages import (
        MIN_SIMILAR_PASSAGE_SCORE,
        PASSAGE_RELATIVE_FLOOR,
    )
    from .passages import _deep_link

    index = getattr(request.app.state, "passages", None)
    if index is None or not index.available:
        return []

    similarity = request.app.state.similarity
    hits = index.search(
        text, similarity.encode_passage(text), limit=limit,
        exclude_book=book_id, mode="hybrid", rerank=True,
        min_score=MIN_SIMILAR_PASSAGE_SCORE, relative_floor=PASSAGE_RELATIVE_FLOOR,
    )

    db = request.app.state.db
    results: list[dict] = []
    for hit in hits:
        book = db.get_book(hit.book_id)
        if not book:
            continue
        row = {
            "book_id": hit.book_id,
            "chunk_id": hit.chunk_id,
            "title": book.get("title", ""),
            "author": book.get("author_primary", ""),
            "excerpt": hit.text[:MATCH_EXCERPT_CHARS],
            "similarity": round(hit.score * 100, 1),
            "cover_url": book.get("cover_url"),
            "page_start": hit.page_start,
            "page_end": hit.page_end,
            "spine_index": hit.spine_index,
            "section": hit.section,
            "is_passage": True,
        }
        row["deep_link"] = _deep_link(hit.book_id, row)
        results.append(row)
    return results


def _book_matches(request: Request, text: str, book_id: Optional[str], limit: int) -> list[dict]:
    """
    Book-level fallback for books the passage index has not reached.

    Honest about what it is: `is_passage` is False and there is no page to
    cite, because the excerpt is the matched book's opening prose rather than
    anything resembling the selection. That was the *only* behaviour available
    before Part 1, and §1.9.2 measured its ceiling — topically right books,
    scored 0.58-0.61, with an excerpt from the front matter. It stays as a
    fallback so a partly-built index degrades instead of going blank.
    """
    similarity = request.app.state.similarity
    if not similarity.has_embeddings:
        return []

    query_emb = similarity.encode_passage(text)
    if query_emb is None:
        return []

    db = request.app.state.db
    results: list[dict] = []
    for match_id, score in similarity.passage_search(query_emb, limit=limit + 1):
        if match_id == book_id:
            continue
        book = db.get_book(match_id)
        if not book:
            continue
        results.append({
            "book_id": match_id,
            "title": book.get("title", ""),
            "author": book.get("author_primary", ""),
            "excerpt": (book.get("content_sample") or book.get("text_excerpt") or "")[:MATCH_EXCERPT_CHARS],
            "similarity": round(score * 100, 1),
            "cover_url": book.get("cover_url"),
            "is_passage": False,
        })
        if len(results) >= limit:
            break
    return results


def _find_matches(request: Request, text: str, book_id: Optional[str], limit: int) -> list[dict]:
    """
    Material resembling `text`, current book excluded — passages if the index
    has them, books if it does not.

    Shared by `/compare` and by the retrieval-grounded `/analyze` actions so
    the reader and the model are looking at the same evidence.
    """
    matches = _passage_matches(request, text, book_id, limit)
    if matches:
        return matches
    return _book_matches(request, text, book_id, limit)


def _context_block(matches: list[dict]) -> str:
    """Retrieved matches as a numbered, citable block for the prompt."""
    lines = []
    for i, match in enumerate(matches[:CONTEXT_MATCH_LIMIT], start=1):
        author = f" — {match['author']}" if match.get("author") else ""
        excerpt = (match.get("excerpt") or "").strip()[:CONTEXT_EXCERPT_CHARS]
        if not excerpt:
            continue
        # §4.2's "ground every citation" is only true once there is a page to
        # cite. With the passage index there is one, so it goes in the prompt
        # and the model can attribute a claim to a place rather than a book.
        where = ""
        if match.get("page_start"):
            where = f", p. {match['page_start']}"
        elif match.get("section"):
            where = f", {match['section']}"
        lines.append(f"[{i}] {match['title']}{author}{where}\n{excerpt}")
    return "\n\n".join(lines)


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

    Reimplemented on the passage index, keeping this response shape. The
    difference is what `excerpt` now contains: the passage that actually
    matched, with the page it sits on, rather than `content_sample` — which was
    prose past the front matter but was never the matching passage, because
    until Part 1 there was no matching passage in the system to return.

    Falls back to book-level matching for books not yet indexed, flagged
    `is_passage: false` so the client can say which kind of answer it got.
    """
    similarity = request.app.state.similarity
    index = getattr(request.app.state, "passages", None)
    if not similarity.has_embeddings and not (index and index.available):
        return {"matches": [], "message": "No embeddings available"}
    matches = _find_matches(request, body.text, body.book_id, body.limit)
    return {
        "matches": matches,
        "source": "passages" if matches and matches[0].get("is_passage") else "books",
    }


@router.post("/analyze")
async def analyze(body: AnalyzeRequest, request: Request):
    """Streaming LLM analysis via SSE."""
    book_title = ""
    book_meta = ""
    if body.book_id:
        book = request.app.state.db.get_book(body.book_id)
        if book:
            book_title = book.get("title", "")
            book_meta = _book_meta(book)

    # The retrieved block. `_build_prompt` interpolates this into the
    # "compare" and "related" templates; before this it was never populated,
    # so every Compare request ended in a bare "Related:" with nothing after.
    context = ""
    if body.action in RETRIEVAL_ACTIONS and body.text:
        context = _context_block(
            _find_matches(request, body.text, body.book_id, CONTEXT_MATCH_LIMIT)
        )

    async def event_stream():
        async for token in analyze_text_stream(
            body.text,
            body.action,
            book_title,
            context=context,
            surrounding=body.surrounding or "",
            book_meta=book_meta,
        ):
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
