"""
LLM service for reading view analysis with streaming.
"""
import json
import logging
from typing import AsyncGenerator, Optional

import requests

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2"


def check_llm_available() -> bool:
    """Check if Ollama is running."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def analyze_text(text: str, action: str, book_title: str = "", context: str = "") -> str:
    """Non-streaming LLM analysis."""
    prompt = _build_prompt(text, action, book_title, context)
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "")
    except Exception as e:
        logger.error(f"LLM analysis failed: {e}")
    return "LLM is not available. Please ensure Ollama is running."


async def analyze_text_stream(text: str, action: str, book_title: str = "", context: str = "") -> AsyncGenerator[str, None]:
    """Streaming LLM analysis via SSE."""
    prompt = _build_prompt(text, action, book_title, context)
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": True},
            timeout=120,
            stream=True,
        )
        for line in resp.iter_lines():
            if line:
                try:
                    data = json.loads(line)
                    token = data.get("response", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
                except json.JSONDecodeError:
                    continue
    except Exception as e:
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
