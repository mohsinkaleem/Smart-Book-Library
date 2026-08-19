"""
Passage-scoped LLM threads (§4.2).

    GET/POST      /api/threads
    GET/PATCH/DEL /api/threads/{id}
    POST          /api/threads/{id}/messages   → SSE, and both turns are stored

The two open items in §4.2 — "no follow-up" and "nothing is saved" — are one
feature, because the thing that makes a follow-up answerable is the same thing
that makes it worth keeping: a frame that outlives the request.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..llm_service import chat_stream, llm_status, thread_system_prompt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads", tags=["threads"])

MAX_PASSAGE_CHARS = 8000
MAX_MESSAGE_CHARS = 4000

# How many earlier turns are replayed to the model. The pinned frame is always
# sent, so this bounds the conversation, not the grounding — and an unbounded
# transcript against a 4k window silently truncates from the front, which is
# exactly where the system prompt lives.
MAX_HISTORY_TURNS = 12


class ThreadCreate(BaseModel):
    book_id: str
    passage: str = ""
    surrounding: str = ""
    title: str = ""
    page: Optional[int] = Field(default=None, ge=1)
    cfi: str = ""
    # Retrieve and pin related passages at creation. On by default: the whole
    # point of pinning context is that it is fixed for the thread, so gathering
    # it per-turn would mean the model's evidence changes under the reader.
    retrieve: bool = True


class ThreadUpdate(BaseModel):
    title: Optional[str] = None


class MessageCreate(BaseModel):
    content: str
    action: str = "ask"


def _retrieved_context(request: Request, passage: str, book_id: str) -> str:
    """The citable block, built once per thread by the same path `/analyze` uses."""
    if not passage:
        return ""
    try:
        from .reading import CONTEXT_MATCH_LIMIT, _context_block, _find_matches
        return _context_block(_find_matches(request, passage, book_id, CONTEXT_MATCH_LIMIT))
    except Exception as e:
        logger.warning(f"Thread context retrieval failed: {e}")
        return ""


@router.get("")
def list_threads(
    request: Request,
    book_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
):
    items = request.app.state.db.list_threads(book_id=book_id, limit=limit)
    return {"threads": items, "total": len(items)}


@router.post("", status_code=201)
def create_thread(body: ThreadCreate, request: Request):
    db = request.app.state.db
    context = (
        _retrieved_context(request, body.passage, body.book_id) if body.retrieve else ""
    )
    thread = db.create_thread(
        body.book_id,
        passage=body.passage[:MAX_PASSAGE_CHARS],
        surrounding=body.surrounding[:MAX_PASSAGE_CHARS],
        context=context,
        title=body.title,
        page=body.page,
        cfi=body.cfi,
    )
    if thread is None:
        raise HTTPException(404, "Book not found")
    return thread


@router.get("/{thread_id}")
def get_thread(thread_id: str, request: Request):
    thread = request.app.state.db.get_thread(thread_id)
    if thread is None:
        raise HTTPException(404, "Thread not found")
    return thread


@router.patch("/{thread_id}")
def update_thread(thread_id: str, body: ThreadUpdate, request: Request):
    if request.app.state.db.get_thread(thread_id) is None:
        raise HTTPException(404, "Thread not found")
    return request.app.state.db.update_thread(thread_id, body.model_dump(exclude_none=True))


@router.delete("/{thread_id}", status_code=204)
def delete_thread(thread_id: str, request: Request):
    if not request.app.state.db.delete_thread(thread_id):
        raise HTTPException(404, "Thread not found")
    return None


@router.post("/{thread_id}/messages")
async def post_message(thread_id: str, body: MessageCreate, request: Request):
    """
    Ask a follow-up. Streams the reply and stores both turns.

    The assistant turn is written **after** the stream completes, from the
    accumulated text. Writing it per token would rewrite a growing row on every
    token; writing it before would leave an empty assistant message behind
    whenever the model or the connection failed, which is worse than no message
    at all because it looks like an answer.
    """
    db = request.app.state.db
    thread = db.get_thread(thread_id)
    if thread is None:
        raise HTTPException(404, "Thread not found")

    status = llm_status()
    if not status.get("available"):
        raise HTTPException(503, status.get("reason") or "LLM unavailable")

    content = body.content.strip()[:MAX_MESSAGE_CHARS]
    if not content:
        raise HTTPException(422, "content is required")
    db.add_message(thread_id, "user", content, body.action)

    book = db.get_book(thread["book_id"]) or {}
    from .reading import _book_meta

    system = thread_system_prompt(
        passage=thread.get("passage", ""),
        book_title=book.get("title", ""),
        book_meta=_book_meta(book),
        surrounding=thread.get("surrounding", ""),
        context=thread.get("context", ""),
    )
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in db.get_thread(thread_id)["messages"][-MAX_HISTORY_TURNS:]
    ]

    async def event_stream():
        collected: list[str] = []
        async for token in chat_stream(history, system=system):
            collected.append(token)
            yield f"data: {json.dumps({'token': token})}\n\n"
        reply = "".join(collected).strip()
        if reply:
            db.add_message(thread_id, "assistant", reply, body.action)
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
