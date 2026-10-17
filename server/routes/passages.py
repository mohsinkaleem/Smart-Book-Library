"""
Passage search endpoints (§1.8).

    POST /api/passages/search        text | query, scope, filters
    GET  /api/passages/{chunk_id}    one chunk, its neighbours and a deep link
    POST /api/passages/similar       passages resembling a selection
    POST /api/passages/stance        supports / complicates / contradicts (§1.9.3)
    GET  /api/books/{id}/threads     recurring concepts within one book (§1.9.4)
    GET  /api/passages/status        whether the index is built, and what of

Every hit carries a deep link. That is not decoration: a retrieved passage the
reader cannot jump to is the feature §1.9.1 exists to replace.
"""
import json
import logging
import re
from urllib.parse import quote
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..passages import (
    MIN_PASSAGE_SCORE,
    MIN_SIMILAR_PASSAGE_SCORE,
    PASSAGE_RELATIVE_FLOOR,
    PassageHit,
    is_apparatus,
)
from .params import Filters

logger = logging.getLogger(__name__)

router = APIRouter(tags=["passages"])

Scope = Literal["book", "catalog", "category", "author"]

# Long enough to carry an argument into the stance prompt, short enough that a
# dozen of them stay inside the model's window.
STANCE_EXCERPT_CHARS = 700
STANCE_MAX_PASSAGES = 8

# A concept thread must be about a concept — see `is_apparatus`, which this
# module used to own a private copy of.
#
# The first run of §1.9.4 over a conference proceedings returned four threads
# at strength 0.935, and every one of them was a *bibliography* — each paper in
# the volume ends in a reference list, and reference lists resemble each other
# more than any two arguments do. They are recurring, and they are not a
# finding. Passage search had the same leak and now shares the fix.


class PassageSearchRequest(BaseModel):
    """
    `text` and `query` differ in how they are *encoded*, not just in name.

    bge is asymmetric: a short search phrase wants the retrieval instruction
    prefix, a passage of prose must never have it. Sending a paragraph as
    `query` silently degrades the results rather than failing, which is why
    they are separate fields rather than one field and a flag.
    """

    query: Optional[str] = None       # a short search phrase → encode_query
    text: Optional[str] = None        # a passage of prose     → encode_passage
    scope: Scope = "catalog"
    book_id: Optional[str] = None
    exclude_book: Optional[str] = None
    limit: int = Field(10, ge=1, le=100)
    # `hybrid` is the default and what almost everything wants. `keyword` is
    # §1.9.5 — "every mention of X across all 618 books" — where an exact term
    # match is the answer and the semantic floor would suppress exactly the
    # rare-word hits being looked for. `semantic` skips BM25 entirely.
    mode: Literal["hybrid", "semantic", "keyword"] = "hybrid"
    rerank: bool = True


class SimilarPassagesRequest(BaseModel):
    text: str
    book_id: Optional[str] = None
    scope: Scope = "catalog"
    limit: int = Field(8, ge=1, le=50)


class StanceRequest(BaseModel):
    text: str
    book_id: Optional[str] = None
    limit: int = Field(8, ge=1, le=STANCE_MAX_PASSAGES)


def _deep_link(book_id: str, hit: dict) -> str:
    """
    A URL that puts the reader on the passage.

    PDF navigates by page, which the reader already does (`goToPage`). EPUB has
    no offline CFI, so it carries `spine` plus the `anchor` needle and the
    reader locates the text in the rendered document — less elegant than a CFI,
    robust in practice (§1.5).
    """
    if hit.get("page_start"):
        return f"/read/{book_id}?page={hit['page_start']}&chunk={hit['chunk_id']}"
    if hit.get("spine_index") is not None:
        # The anchor rides along: `spine_index` gets the reader to the right
        # section, and the needle is what locates the passage inside it. There
        # is no offline CFI to send instead (§1.5).
        anchor = quote(hit.get("anchor_text") or "")
        return f"/read/{book_id}?spine={hit['spine_index']}&chunk={hit['chunk_id']}&anchor={anchor}"
    return f"/read/{book_id}?chunk={hit['chunk_id']}"


def _book_label(db, book_id: str, cache: dict) -> dict:
    if book_id not in cache:
        book = db.get_book(book_id) or {}
        cache[book_id] = {
            "title": book.get("title", ""),
            "author": book.get("author_primary", ""),
            "year": book.get("publication_year"),
            "cover_url": book.get("cover_url"),
            "file_type": book.get("file_type", ""),
        }
    return cache[book_id]


def _serialise(db, hits: list[PassageHit]) -> list[dict]:
    cache: dict = {}
    out = []
    for hit in hits:
        label = _book_label(db, hit.book_id, cache)
        row = {
            "chunk_id": hit.chunk_id,
            "book_id": hit.book_id,
            "chunk_idx": hit.chunk_idx,
            "text": hit.text,
            "score": round(hit.score, 4),      # cosine — comparable between queries
            "rrf": round(hit.rrf, 5),           # fusion value — decides order only
            "page_start": hit.page_start,
            "page_end": hit.page_end,
            "spine_index": hit.spine_index,
            "anchor_text": hit.anchor_text,
            "section": hit.section,
            # Which system found it. A hit only the lexical side proposed is a
            # keyword match; one both proposed is the strongest kind there is.
            "matched": (
                "both" if hit.dense_rank is not None and hit.lexical_rank is not None
                else "semantic" if hit.dense_rank is not None
                else "keyword"
            ),
            **label,
        }
        row["deep_link"] = _deep_link(hit.book_id, row)
        out.append(row)
    return out


def _index(request: Request):
    index = getattr(request.app.state, "passages", None)
    if index is None or not index.available:
        raise HTTPException(
            503,
            "The passage index is not built. Run "
            "`python scripts/build_passage_index.py` to build it.",
        )
    return index


def _resolve_scope(request: Request, body, filters_dict: dict) -> dict:
    """
    Turn a scope into the arguments `PassageIndex.search` takes.

    `category` and `author` go through `db.filtered_ids` rather than
    re-implementing the predicates — that second copy had already drifted once
    and silently ignored `tag`.
    """
    db = request.app.state.db
    scope = body.scope
    if scope == "book":
        if not body.book_id:
            raise HTTPException(422, "scope='book' requires book_id")
        return {"book_id": body.book_id}
    # Searching one book is the user pointing at that book, duplicate or not.
    # Every other scope is a search of "the library", which shows one copy of
    # each book — so the hidden copies' passages must not come back either.
    duplicates = db.duplicate_book_ids()
    if scope in ("category", "author"):
        if not filters_dict:
            raise HTTPException(422, f"scope='{scope}' requires a category or author filter")
        return {
            "allowed_books": db.filtered_ids(**filters_dict),
            "exclude_book": getattr(body, "exclude_book", None),
            "exclude_books": duplicates,
        }
    return {
        "exclude_book": getattr(body, "exclude_book", None) or body.book_id,
        "exclude_books": duplicates,
    }


@router.get("/api/passages/status")
def passage_status(request: Request):
    """
    Whether passage features will work, and why not when they will not.

    The reader gates on this so "Elsewhere in this book" says "not indexed yet"
    rather than rendering an empty panel that looks like "no matches".
    """
    index = getattr(request.app.state, "passages", None)
    meta = dict(index.meta) if index else {}
    meta["available"] = bool(index and index.available)
    return meta


@router.post("/api/passages/search")
def search_passages(body: PassageSearchRequest, request: Request, filters: Filters):
    """Hybrid passage search across the catalog, one book, or a filtered slice."""
    index = _index(request)
    similarity = request.app.state.similarity

    raw = (body.query or body.text or "").strip()
    if not raw:
        raise HTTPException(422, "query or text is required")

    # Asymmetric encoding, chosen by which field was sent — see the request model.
    vector = (
        similarity.encode_query(raw) if body.query else similarity.encode_passage(raw)
    )

    scope_args = _resolve_scope(request, body, filters.as_dict(include_search=False))
    hits = index.search(
        raw, vector, limit=body.limit, mode=body.mode, rerank=body.rerank,
        min_score=MIN_PASSAGE_SCORE if body.query else MIN_SIMILAR_PASSAGE_SCORE,
        relative_floor=PASSAGE_RELATIVE_FLOOR,
        **scope_args,
    )
    return {
        "results": _serialise(request.app.state.db, hits),
        "scope": body.scope,
        "reranked": bool(body.rerank and index._reranker is not None),
    }


@router.post("/api/passages/similar")
def similar_passages(body: SimilarPassagesRequest, request: Request):
    """
    Passages resembling a selection — §1.9.1 and §1.9.2.

    `scope='book'` is "elsewhere in this book", which was structurally
    impossible before this index: the old compare endpoint skipped the current
    book outright, and there was only one vector per book to match against
    anyway.
    """
    index = _index(request)
    similarity = request.app.state.similarity
    vector = similarity.encode_passage(body.text)

    if body.scope == "book":
        if not body.book_id:
            raise HTTPException(422, "scope='book' requires book_id")
        scope_args = {"book_id": body.book_id}
    else:
        # "Where else does this idea appear" must not answer with the same
        # paragraph out of the library's hidden second copy of this book.
        scope_args = {
            "exclude_book": body.book_id,
            "exclude_books": request.app.state.db.duplicate_book_ids(),
        }

    # Ask for one extra: in-book search will return the selection's own chunk,
    # which is a 1.0 match and tells the reader nothing.
    hits = index.search(
        body.text, vector, limit=body.limit + 2, mode="hybrid", rerank=True,
        min_score=MIN_SIMILAR_PASSAGE_SCORE, relative_floor=PASSAGE_RELATIVE_FLOOR,
        **scope_args,
    )
    results = [
        row for row in _serialise(request.app.state.db, hits)
        if row["text"].strip() not in body.text and body.text.strip() not in row["text"]
    ]
    return {"results": results[:body.limit], "scope": body.scope}


@router.get("/api/passages/{chunk_id}")
def get_passage(chunk_id: int, request: Request, span: int = Query(1, ge=0, le=5)):
    """One chunk with its neighbours, so a hit can be read in context."""
    index = _index(request)
    rows = index.get_chunks([chunk_id])
    if chunk_id not in rows:
        raise HTTPException(404, "Passage not found")
    row = rows[chunk_id]
    book = request.app.state.db.get_book(row["book_id"]) or {}
    return {
        **row,
        "title": book.get("title", ""),
        "author": book.get("author_primary", ""),
        "deep_link": _deep_link(row["book_id"], row),
        "neighbours": index.neighbours(chunk_id, span=span),
    }


@router.post("/api/passages/stance")
async def passage_stance(body: StanceRequest, request: Request):
    """
    Group retrieved passages into supports / complicates / contradicts (§1.9.3).

    Grounded entirely in retrieved text: the model is handed numbered passages
    and asked to sort them, never to recall anything. Every returned item keeps
    its `chunk_id` and page, so each claim stays citable — which is the whole
    reason this is worth building on retrieval rather than on a summary.
    """
    from ..llm_service import analyze_text, llm_status

    index = _index(request)
    status = llm_status()
    if not status.get("available"):
        raise HTTPException(503, status.get("message") or "LLM unavailable")

    similarity = request.app.state.similarity
    hits = index.search(
        body.text, similarity.encode_passage(body.text),
        limit=body.limit, mode="hybrid", rerank=True,
        exclude_book=body.book_id,
        exclude_books=request.app.state.db.duplicate_book_ids(),
        min_score=MIN_SIMILAR_PASSAGE_SCORE, relative_floor=PASSAGE_RELATIVE_FLOOR,
    )
    passages = _serialise(request.app.state.db, hits)
    if not passages:
        return {"groups": {}, "passages": [], "message": "No related passages found"}

    numbered = "\n\n".join(
        f"[{i}] {p['title']} — {p['author'] or 'unknown'}\n"
        f"{p['text'][:STANCE_EXCERPT_CHARS]}"
        for i, p in enumerate(passages, start=1)
    )
    verdict = await analyze_text(
        body.text, "stance", context=numbered, book_title="",
    )
    groups = _parse_stance(verdict, passages)
    return {"groups": groups, "passages": passages, "raw": verdict}


def _parse_stance(raw: str, passages: list[dict]) -> dict:
    """
    Pull the model's grouping out of its reply.

    A 4B model does not reliably emit clean JSON, so a failed parse falls back
    to line scraping rather than throwing away a usable answer — and anything
    still unassigned is reported as `unsorted` rather than silently dropped.
    A passage the model did not mention is a passage the reader should still
    see.
    """
    groups: dict[str, list[dict]] = {
        "supports": [], "complicates": [], "contradicts": [], "unsorted": []
    }
    by_number = {i: p for i, p in enumerate(passages, start=1)}
    assigned: set[int] = set()

    parsed = None
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start:end + 1])
        except ValueError:
            parsed = None

    if isinstance(parsed, dict):
        for key in ("supports", "complicates", "contradicts"):
            for entry in parsed.get(key) or []:
                if isinstance(entry, dict):
                    number, why = entry.get("passage"), entry.get("why", "")
                else:
                    number, why = entry, ""
                try:
                    number = int(number)
                except (TypeError, ValueError):
                    continue
                if number in by_number and number not in assigned:
                    groups[key].append({**by_number[number], "why": str(why)[:400]})
                    assigned.add(number)

    if not assigned:
        import re
        current = None
        for line in raw.splitlines():
            lowered = line.lower()
            for key in ("supports", "complicates", "contradicts"):
                if key in lowered and len(line) < 80:
                    current = key
            if current is None:
                continue
            for match in re.finditer(r"\[(\d+)\]", line):
                number = int(match.group(1))
                if number in by_number and number not in assigned:
                    groups[current].append({**by_number[number], "why": line.strip()[:400]})
                    assigned.add(number)

    for number, passage in by_number.items():
        if number not in assigned:
            groups["unsorted"].append({**passage, "why": ""})
    return groups


@router.get("/api/books/{book_id}/threads")
def concept_threads(
    book_id: str,
    request: Request,
    limit: int = Query(6, ge=1, le=20),
    per_thread: int = Query(4, ge=2, le=10),
):
    """
    Recurring concepts within one book (§1.9.4).

    A thread is a chunk plus the other chunks in the same book that resemble
    it, from a *different part* of the book — chapter 2 and chapter 11 making
    the same argument is the finding; chapter 2 resembling chapter 2 is not.
    Seeds are spread across the book so the result is a map of it rather than
    six views of its densest chapter.
    """
    import numpy as np

    index = _index(request)
    span = index.book_ranges.get(book_id)
    if span is None:
        return {"threads": [], "message": "This book is not in the passage index"}

    lo, hi = span
    matrix = index.matrix[lo:hi]
    count = hi - lo
    if count < 4:
        return {"threads": [], "message": "Too few passages in this book"}

    # Every passage against every other, once. A book is ~600 chunks, so this
    # is a 600x600 matmul — under a millisecond, and far simpler than trying to
    # be clever about which pairs to score.
    scores = matrix @ matrix.T
    np.fill_diagonal(scores, -1.0)

    # "A different part of the book": neighbouring chunks overlap by
    # construction, so without this every thread would be a chunk and the two
    # chunks either side of it.
    apart = max(3, count // 20)
    for offset in range(-apart, apart + 1):
        if offset:
            np.fill_diagonal(scores[max(0, offset):, max(0, -offset):], -1.0)

    strength = scores.max(axis=1)
    order = np.argsort(strength)[::-1]

    threads = []
    used: set[int] = set()
    for local in order:
        local = int(local)
        if len(threads) >= limit:
            break
        if local in used or strength[local] < MIN_SIMILAR_PASSAGE_SCORE:
            continue
        if not _is_conceptual(index.get_chunks([lo + local]).get(lo + local, {}).get("text", "")):
            continue
        members = np.argsort(scores[local])[::-1][:per_thread - 1]
        members = [int(m) for m in members if scores[local][m] >= MIN_SIMILAR_PASSAGE_SCORE]
        if not members:
            continue
        picked = [local] + members
        if len(set(picked) & used) > len(picked) // 2:
            continue
        used.update(picked)
        rows = index.get_chunks([lo + p for p in picked])
        passages = []
        for p in picked:
            row = rows.get(lo + p)
            if row:
                passages.append({
                    **row,
                    "score": round(float(scores[local][p]) if p != local else 1.0, 4),
                    "deep_link": _deep_link(book_id, row),
                })
        if len(passages) < 2:
            continue
        threads.append({
            "strength": round(float(strength[local]), 4),
            "section": passages[0].get("section", ""),
            "passages": sorted(passages, key=lambda p: p["chunk_idx"]),
        })

    return {"threads": threads, "book_id": book_id}


def _is_conceptual(text: str) -> bool:
    """
    Whether a passage is an argument rather than an apparatus.

    The signals live in `is_apparatus`, which passage search applies too. This
    adds the one rule that is specific to threads: a thread is a claim about a
    recurring *passage*, and anything under 200 characters is a heading or a
    page number that happens to recur.
    """
    body = (text or "").strip()
    if len(body) < 200:
        return False
    return not is_apparatus(body)
