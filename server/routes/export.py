"""
Markdown export of highlights, notes and LLM threads (Part 5).

    GET /api/export/markdown              the whole library
    GET /api/export/markdown?book_id=…    one book

A local-first library should have portable notes. Everything here is already
stored — `GET /api/annotations` returns annotations in reading order and
`/api/threads` returns the conversations — so this is a formatter, not a new
store, and it deliberately holds no knowledge the other endpoints do not.

Returned as `text/markdown` with a `Content-Disposition` filename, so a browser
saves it rather than rendering it in the tab.
"""
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/api/export", tags=["export"])

KIND_HEADINGS = {
    "highlight": "Highlights",
    "note": "Notes",
    "bookmark": "Bookmarks",
}
KIND_ORDER = ("highlight", "note", "bookmark")


def _safe_filename(name: str, fallback: str) -> str:
    """A filename that survives every filesystem, or the fallback."""
    cleaned = re.sub(r"[^\w\s.-]", "", name or "").strip()
    cleaned = re.sub(r"\s+", "-", cleaned)[:60].strip("-.")
    return cleaned or fallback


def _quote(text: str) -> str:
    """Blockquote a passage, keeping its own line breaks as line breaks."""
    lines = [line.strip() for line in (text or "").strip().splitlines() if line.strip()]
    return "\n".join(f"> {line}" for line in lines) if lines else ""


def _locate(item: dict) -> str:
    if item.get("page"):
        return f"p. {item['page']}"
    if item.get("cfi"):
        return "EPUB location"
    return ""


def _annotation_section(annotations: list[dict]) -> list[str]:
    out: list[str] = []
    for kind in KIND_ORDER:
        items = [a for a in annotations if a.get("kind") == kind]
        if not items:
            continue
        out.append(f"### {KIND_HEADINGS[kind]}\n")
        for item in items:
            where = _locate(item)
            header = f"**{where}**" if where else "**—**"
            colour = item.get("color")
            if kind == "highlight" and colour and colour != "yellow":
                header += f" · {colour}"
            out.append(header + "\n")
            quoted = _quote(item.get("text", ""))
            if quoted:
                out.append(quoted + "\n")
            note = (item.get("note") or "").strip()
            if note:
                out.append(f"{note}\n")
            out.append("")
    return out


def _thread_section(threads: list[dict]) -> list[str]:
    if not threads:
        return []
    out = ["### Conversations\n"]
    for thread in threads:
        out.append(f"#### {thread.get('title') or 'Untitled thread'}\n")
        where = f"p. {thread['page']}" if thread.get("page") else ""
        if where:
            out.append(f"*{where}*\n")
        quoted = _quote(thread.get("passage", ""))
        if quoted:
            out.append(quoted + "\n")
        for message in thread.get("messages", []):
            speaker = "**You**" if message.get("role") == "user" else "**Assistant**"
            body = (message.get("content") or "").strip()
            if body:
                out.append(f"{speaker}: {body}\n")
        out.append("")
    return out


def _book_markdown(db, book: dict, annotations: list[dict], threads: list[dict]) -> list[str]:
    import json

    authors = book.get("authors") or []
    if isinstance(authors, str):
        try:
            authors = json.loads(authors)
        except ValueError:
            authors = []

    lines = [f"## {book.get('title') or book.get('file_name', 'Untitled')}\n"]
    byline = ", ".join(str(a) for a in authors)
    meta = " · ".join(x for x in [byline, str(book.get("publication_year") or "")] if x)
    if meta:
        lines.append(f"*{meta}*\n")
    lines.extend(_annotation_section(annotations))
    lines.extend(_thread_section(threads))
    return lines


@router.get("/markdown", response_class=PlainTextResponse)
def export_markdown(
    request: Request,
    book_id: Optional[str] = None,
    include_threads: bool = Query(True),
):
    """Highlights, notes, bookmarks and LLM threads as one Markdown document."""
    db = request.app.state.db

    if book_id and db.get_book(book_id) is None:
        raise HTTPException(404, "Book not found")

    annotations = db.list_annotations(book_id=book_id, limit=100_000)
    threads = db.list_threads(book_id=book_id) if include_threads else []
    # `list_threads` deliberately omits messages — a transcript is what an
    # export is for, so they are fetched per thread rather than inflating every
    # list response in the app.
    threads = [db.get_thread(t["id"]) or t for t in threads]

    by_book: dict[str, dict] = {}
    for item in annotations:
        by_book.setdefault(item["book_id"], {"annotations": [], "threads": []})["annotations"].append(item)
    for thread in threads:
        by_book.setdefault(thread["book_id"], {"annotations": [], "threads": []})["threads"].append(thread)

    if not by_book:
        body = "# Reading notes\n\nNothing to export yet.\n"
        return PlainTextResponse(body, media_type="text/markdown; charset=utf-8")

    single = db.get_book(book_id) if book_id else None
    heading = (
        f"# {single.get('title') or 'Reading notes'}" if single else "# Reading notes"
    )
    lines = [heading, ""]

    ordered = sorted(
        by_book.items(),
        key=lambda kv: ((db.get_book(kv[0]) or {}).get("title") or "").lower(),
    )
    for bid, payload in ordered:
        book = db.get_book(bid)
        if not book:
            continue
        lines.extend(_book_markdown(db, book, payload["annotations"], payload["threads"]))

    filename = _safe_filename(
        (single or {}).get("title", "") if single else "library-notes", "reading-notes"
    )
    return PlainTextResponse(
        "\n".join(lines).rstrip() + "\n",
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.md"'},
    )
