"""
LLM-powered enrichment using Ollama (local) or OpenAI-compatible APIs.

Generates:
- High-quality summaries from text excerpts
- Refined themes and categories
- Better descriptions for books missing API descriptions

Requires a running Ollama instance (or compatible API).
    ollama pull llama3.2       # or any model you prefer
    ollama serve               # starts the local API server
"""
import json
import logging
import re
from typing import Optional

import requests

from .models import BookRecord

logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2"          # Change to your preferred model
OLLAMA_TIMEOUT = 120               # LLM generation can be slow
OLLAMA_MAX_INPUT_CHARS = 3000      # Limit context sent to model

# OpenAI-compatible API (alternative)
OPENAI_API_URL = ""                # e.g. "https://api.openai.com/v1"
OPENAI_API_KEY = ""                # Set via env or config
OPENAI_MODEL = "gpt-4o-mini"


def is_available() -> bool:
    """Check if Ollama is running and the model is available."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            # Check if our model (or a variant) is available
            return any(OLLAMA_MODEL in m for m in models)
    except Exception:
        pass
    return False


def generate_llm_summary(record: BookRecord, force: bool = False) -> BookRecord:
    """
    Use an LLM to generate a summary, refine themes, and improve description.
    Updates the record in-place.
    """
    # Skip if already has a good summary and not forcing
    if not force and record.summary and len(record.summary) > 100:
        return record

    # Need some text to work with
    text_input = _build_llm_input(record)
    if not text_input or len(text_input) < 50:
        return record

    # Try Ollama first, fall back to OpenAI-compatible API
    result = _call_ollama(text_input, record)
    if result is None and OPENAI_API_URL:
        result = _call_openai_compatible(text_input, record)

    if result:
        _apply_llm_result(record, result)

    return record


def generate_llm_description(record: BookRecord) -> BookRecord:
    """Generate a description for books missing one."""
    if record.description and len(record.description) > 50:
        return record

    text_input = _build_llm_input(record)
    if not text_input or len(text_input) < 50:
        return record

    prompt = _build_description_prompt(record, text_input)
    response = _raw_ollama_generate(prompt)
    if response:
        record.description = response.strip()[:2000]
        logger.info(f"   🤖 Generated LLM description for {record.file_name}")

    return record


def _build_llm_input(record: BookRecord) -> str:
    """Build context string for the LLM from available record data."""
    parts = []
    if record.title:
        parts.append(f"Title: {record.title}")
    if record.authors:
        parts.append(f"Authors: {', '.join(record.authors)}")
    if record.publisher:
        parts.append(f"Publisher: {record.publisher}")
    if record.publication_year:
        parts.append(f"Year: {record.publication_year}")
    if record.description:
        parts.append(f"Existing description: {record.description[:500]}")
    if record.categories:
        parts.append(f"Categories: {', '.join(record.categories[:5])}")
    if record.text_excerpt:
        excerpt = record.text_excerpt[:OLLAMA_MAX_INPUT_CHARS]
        parts.append(f"\nText excerpt:\n{excerpt}")

    return "\n".join(parts)


def _build_summary_prompt(record: BookRecord, text_input: str) -> str:
    """Build the prompt for summary generation."""
    return f"""You are a librarian cataloging a book. Based on the following information, provide:
1. A concise 2-3 sentence summary of what this book is about
2. Up to 5 thematic tags (broad concepts the book covers)
3. Up to 3 category labels (e.g. "Computer Science", "History", "Self-Help")

Respond ONLY in this exact JSON format, no other text:
{{
  "summary": "...",
  "themes": ["theme1", "theme2", ...],
  "categories": ["cat1", "cat2", ...]
}}

Book information:
{text_input}"""


def _build_description_prompt(record: BookRecord, text_input: str) -> str:
    """Build the prompt for description generation."""
    return f"""You are a librarian writing a catalog description. Based on the following book information, 
write a clear, informative 3-5 sentence description of the book suitable for a library catalog.
Do not include any preamble or labels — just the description text.

Book information:
{text_input}"""


def _call_ollama(text_input: str, record: BookRecord) -> Optional[dict]:
    """Call Ollama API for structured summary generation."""
    prompt = _build_summary_prompt(record, text_input)

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 512,
                },
            },
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")

        # Parse the JSON response from the LLM
        return _parse_llm_json(raw)

    except requests.ConnectionError:
        logger.debug("Ollama not running (connection refused)")
        return None
    except requests.Timeout:
        logger.warning(f"Ollama timed out for {record.file_name}")
        return None
    except Exception as e:
        logger.debug(f"Ollama call failed for {record.file_name}: {e}")
        return None


def _raw_ollama_generate(prompt: str) -> Optional[str]:
    """Raw text generation from Ollama (not JSON-structured)."""
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.4,
                    "num_predict": 512,
                },
            },
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        logger.debug(f"Ollama raw generate failed: {e}")
        return None


def _call_openai_compatible(text_input: str, record: BookRecord) -> Optional[dict]:
    """Call an OpenAI-compatible API as fallback."""
    if not OPENAI_API_URL or not OPENAI_API_KEY:
        return None

    prompt = _build_summary_prompt(record, text_input)

    try:
        resp = requests.post(
            f"{OPENAI_API_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a librarian cataloging books. Respond only in valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 512,
            },
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        return _parse_llm_json(raw)

    except Exception as e:
        logger.debug(f"OpenAI-compatible API call failed for {record.file_name}: {e}")
        return None


def _parse_llm_json(raw: str) -> Optional[dict]:
    """Parse structured JSON from LLM output (tolerant of markdown fences)."""
    if not raw:
        return None

    # Strip markdown code fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "summary" in data:
            return data
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from the response
    json_match = re.search(r'\{[^{}]*"summary"[^{}]*\}', raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    logger.debug(f"Failed to parse LLM JSON response: {raw[:200]}...")
    return None


def _apply_llm_result(record: BookRecord, result: dict):
    """Apply parsed LLM result to the book record."""
    summary = result.get("summary", "")
    if summary and (not record.summary or len(summary) > len(record.summary)):
        record.summary = summary[:500]

    themes = result.get("themes", [])
    if themes and isinstance(themes, list):
        # Merge with existing themes without duplicates
        existing = {t.lower() for t in record.themes}
        for t in themes:
            if isinstance(t, str) and t.lower() not in existing:
                record.themes.append(t)
                existing.add(t.lower())
        record.themes = record.themes[:10]

    categories = result.get("categories", [])
    if categories and isinstance(categories, list):
        existing = {c.lower() for c in record.categories}
        for c in categories:
            if isinstance(c, str) and c.lower() not in existing:
                record.categories.append(c)
                existing.add(c.lower())
        record.categories = record.categories[:8]

    logger.info(f"   🤖 LLM enriched: {record.file_name}")
