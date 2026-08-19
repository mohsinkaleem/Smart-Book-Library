"""
LLM service for reading view analysis with streaming.

`analyze_text_stream` is consumed by a `StreamingResponse`, so it runs on the
event loop. It used to do that with synchronous `requests.post(stream=True)`
and a blocking `for line in resp.iter_lines()`, which meant one user pressing
"Explain" froze every other request for the length of the generation — up to
the full 120 s timeout. It is `httpx.AsyncClient` now, and a client
disconnecting closes the upstream request instead of leaving Ollama
generating into a dead socket.
"""
import json
import logging
import os
import time
from typing import AsyncGenerator, Optional

import httpx
import requests

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")
REQUEST_TIMEOUT = 120.0

# Prompt budget. A 4B model with a 4k-token window silently truncates from the
# front, which drops the instruction and keeps the retrieved noise — so the
# retrieved and surrounding blocks are capped before assembly and the whole
# prompt is capped after it.
PROMPT_MAX_CHARS = int(os.getenv("LLM_PROMPT_MAX_CHARS", "8000"))
SURROUNDING_MAX_CHARS = 1200
PROBE_TIMEOUT = 3.0

# The frontend gates its Analysis buttons on this, so it is polled on every
# reader mount. With Ollama down each probe costs the full connect timeout, so
# the answer is cached briefly — long enough that opening five books is one
# probe, short enough that starting Ollama is noticed without a reload.
_STATUS_TTL = 30.0
_status_cache: tuple[float, dict] = (0.0, {})


def _clip(value: str, limit: int) -> str:
    """Truncate on a word boundary, with an explicit marker."""
    value = (value or "").strip()
    if len(value) <= limit:
        return value
    cut = value[:limit].rsplit(" ", 1)[0]
    return f"{cut} […]"


def _probe() -> dict:
    """Ask Ollama what it has loaded. Never raises."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=PROBE_TIMEOUT)
        if resp.status_code != 200:
            return {"available": False, "reason": f"HTTP {resp.status_code}"}
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        # Ollama reports `llama3.2:latest` for a model pulled as `llama3.2`.
        installed = any(n == OLLAMA_MODEL or n.split(":")[0] == OLLAMA_MODEL for n in names)
        return {
            "available": True,
            "model": OLLAMA_MODEL,
            "model_installed": installed,
            "reason": "" if installed else f"model {OLLAMA_MODEL!r} is not pulled",
        }
    except Exception as e:
        return {"available": False, "reason": str(e)}


def llm_status(force: bool = False) -> dict:
    """Cached Ollama readiness, with the configured model and why it is not ready."""
    global _status_cache
    cached_at, cached = _status_cache
    if not force and cached and time.monotonic() - cached_at < _STATUS_TTL:
        return cached
    status = _probe()
    status.setdefault("model", OLLAMA_MODEL)
    status["base_url"] = OLLAMA_BASE_URL
    _status_cache = (time.monotonic(), status)
    return status


def check_llm_available() -> bool:
    """Check if Ollama is running."""
    return bool(llm_status().get("available"))


async def analyze_text_stream(
    text: str,
    action: str,
    book_title: str = "",
    context: str = "",
    surrounding: str = "",
    book_meta: str = "",
) -> AsyncGenerator[str, None]:
    """Streaming LLM analysis, token by token."""
    prompt = _build_prompt(text, action, book_title, context, surrounding, book_meta)
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": True}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            async with client.stream(
                "POST", f"{OLLAMA_BASE_URL}/api/generate", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = data.get("response", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
    except httpx.HTTPError as e:
        logger.warning(f"LLM stream failed: {e}")
        yield f"\n\n[Error: {e}]"


async def analyze_text(
    text: str,
    action: str,
    book_title: str = "",
    context: str = "",
    surrounding: str = "",
    book_meta: str = "",
) -> str:
    """
    One-shot analysis, collected rather than streamed.

    The stance grouping (§1.9.3) needs the *whole* reply before it can parse a
    grouping out of it, so streaming it would only mean buffering it somewhere
    else. Returns "" rather than raising: a failed grouping should degrade to
    "unsorted", which is still a list of real retrieved passages.
    """
    prompt = _build_prompt(text, action, book_title, context, surrounding, book_meta)
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "")
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(f"LLM call failed: {e}")
        return ""


async def chat_stream(
    messages: list[dict],
    system: str = "",
) -> AsyncGenerator[str, None]:
    """
    Multi-turn conversation, token by token (§4.2).

    Uses Ollama's `/api/chat` rather than replaying the whole exchange into
    `/api/generate` as one string: the model applies its own chat template to
    role-tagged turns, and a hand-rolled "User: ... Assistant: ..." transcript
    is the usual reason a follow-up answer starts hallucinating a new question.

    The pinned passage and retrieved context ride in the system message, so
    they are stated once and stay in front of the model for every turn instead
    of scrolling out of the window behind the conversation.
    """
    turns = ([{"role": "system", "content": _clip(system, PROMPT_MAX_CHARS)}] if system else [])
    turns += [
        {"role": m["role"], "content": _clip(m.get("content", ""), PROMPT_MAX_CHARS)}
        for m in messages if m.get("content")
    ]
    payload = {"model": OLLAMA_MODEL, "messages": turns, "stream": True}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            async with client.stream(
                "POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = (data.get("message") or {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
    except httpx.HTTPError as e:
        logger.warning(f"LLM chat failed: {e}")
        yield f"\n\n[Error: {e}]"


def thread_system_prompt(
    passage: str, book_title: str = "", book_meta: str = "",
    surrounding: str = "", context: str = "",
) -> str:
    """
    The pinned frame for a passage-scoped thread.

    Everything the one-shot actions assemble per request is stated once here
    instead, which is what makes a follow-up like "why?" answerable — it refers
    to a passage the model can still see.
    """
    parts = ["You are helping a reader interrogate a passage from their own library."]
    if book_title:
        parts.append(f'The passage is from "{book_title}"' + (f" ({book_meta})." if book_meta else "."))
    parts.append(f"The passage under discussion is:\n\n{passage}")
    if surrounding:
        parts.append(
            "Surrounding text from the same page, for background only:\n"
            f"{_clip(surrounding, SURROUNDING_MAX_CHARS)}"
        )
    if context:
        parts.append(
            "Related material retrieved from the reader's own library. Cite these by "
            "title and page where relevant, and do not invent sources beyond them:\n"
            f"{context}"
        )
    parts.append(
        "Answer the reader's questions about this passage. Be concise and concrete, "
        "and say plainly when the passage does not settle a question."
    )
    return "\n\n".join(parts)


def _build_prompt(
    text: str,
    action: str,
    book_title: str = "",
    context: str = "",
    surrounding: str = "",
    book_meta: str = "",
) -> str:
    """
    Build the LLM prompt for one action.

    `context` is retrieved material from the reader's own library and
    `surrounding` is the prose either side of the selection in the book being
    read. Both used to be unreachable: the route called this with the
    selection alone, so the "compare" template — the one action that
    interpolates `context` — sent a prompt ending in a bare `Related:` with
    nothing after it on every single request.

    Every optional block is omitted entirely when empty rather than rendered
    as an empty heading, so a prompt never asks the model to reason about a
    section that is not there.
    """
    book_ref = f' from "{book_title}"' if book_title else ""

    frame = ""
    if book_meta:
        frame += f"\n\nAbout the book: {book_meta}"
    if surrounding:
        frame += (
            "\n\nSurrounding text from the same page (background only — "
            f"analyse the passage, not this):\n{_clip(surrounding, SURROUNDING_MAX_CHARS)}"
        )

    prompts = {
        "explain": (
            f"Explain this passage{book_ref} in simpler terms. Be clear and concise."
            f"{frame}\n\nPassage:\n{text}"
        ),
        "summarize": (
            f"Summarize the key points of this passage{book_ref}."
            f"{frame}\n\nPassage:\n{text}"
        ),
        "critique": (
            f"Provide a critical analysis of this argument{book_ref}. Name the "
            f"assumptions it rests on and where it is weakest."
            f"{frame}\n\nPassage:\n{text}"
        ),
    }

    if action == "compare":
        if context:
            prompts["compare"] = (
                f"Compare the ideas in this passage{book_ref} against the related "
                f"material retrieved from the reader's own library below. Say where "
                f"they agree, where they diverge, and where they contradict each "
                f"other. Cite the sources by title. Do not invent sources that are "
                f"not listed."
                f"{frame}\n\nPassage:\n{text}"
                f"\n\nRelated material from the library:\n{context}"
            )
        else:
            # Nothing was retrieved — ask for something answerable rather than
            # sending a heading with no body under it.
            prompts["compare"] = (
                f"Compare the ideas in this passage{book_ref} with the major "
                f"competing positions on the same question, naming the thinkers "
                f"who hold them."
                f"{frame}\n\nPassage:\n{text}"
            )
    elif action == "stance":
        # §1.9.3. The model sorts retrieved passages; it never recalls any. The
        # JSON request is a request, not a guarantee — a 4B model will sometimes
        # answer in prose, which is why `_parse_stance` also scrapes lines and
        # reports anything unassigned rather than dropping it.
        prompts["stance"] = (
            "Below is a passage, then numbered passages retrieved from the reader's "
            "own library. Sort the numbered passages by how they stand to the "
            "passage's claim: 'supports', 'complicates', or 'contradicts'. Use only "
            "what is written in them — do not use outside knowledge, and do not "
            "invent passages.\n\n"
            "Reply as JSON:\n"
            '{"supports": [{"passage": 1, "why": "one line"}], '
            '"complicates": [], "contradicts": []}\n'
            f"{frame}\n\nPassage:\n{text}"
            f"\n\nRetrieved passages:\n{context}"
        )
    elif action == "related":
        related_block = (
            f"\n\nRelated material from the reader's library:\n{context}"
            if context else ""
        )
        prompts["related"] = (
            f"What related concepts, theories, or ideas connect to this passage"
            f"{book_ref}?"
            + (
                " Ground your answer in the retrieved material below where it is "
                "relevant, citing sources by title."
                if context else ""
            )
            + f"{frame}\n\nPassage:\n{text}{related_block}"
        )

    return _clip(prompts.get(action, f"Analyze this text:\n\n{text}"), PROMPT_MAX_CHARS)
