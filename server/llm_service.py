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
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
REQUEST_TIMEOUT = 120.0
PROBE_TIMEOUT = 3.0

# The frontend gates its Analysis buttons on this, so it is polled on every
# reader mount. With Ollama down each probe costs the full connect timeout, so
# the answer is cached briefly — long enough that opening five books is one
# probe, short enough that starting Ollama is noticed without a reload.
_STATUS_TTL = 30.0
_status_cache: tuple[float, dict] = (0.0, {})


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
    text: str, action: str, book_title: str = "", context: str = ""
) -> AsyncGenerator[str, None]:
    """Streaming LLM analysis, token by token."""
    prompt = _build_prompt(text, action, book_title, context)
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


def _build_prompt(text: str, action: str, book_title: str = "", context: str = "") -> str:
    """Build the LLM prompt based on the action."""
    book_ref = f' from "{book_title}"' if book_title else ""

    prompts = {
        "explain": f"Explain this passage{book_ref} in simpler terms. Be clear and concise:\n\n{text}",
        "summarize": f"Summarize the key points of this passage{book_ref}:\n\n{text}",
        "compare": f"Compare the ideas in this passage{book_ref} with the following related context:\n\nPassage: {text}\n\nRelated: {context}",
        "critique": f"Provide a critical analysis of this argument{book_ref}:\n\n{text}",
        "related": f"What related concepts, theories, or ideas connect to this passage{book_ref}:\n\n{text}",
    }
    return prompts.get(action, f"Analyze this text:\n\n{text}")
