"""
LLM enrichment via Ollama.

The LLM is used where it is actually strong:

* summarising the *content sample* (not the copyright page);
* mapping messy external subjects onto the fixed taxonomy — it chooses from an
  enum, it does not invent labels;
* adjudicating borderline (0.45–0.75) candidate matches.

Configuration comes from `catalog.config` only. The module-local copies that
used to shadow it — and the dead OpenAI path that could never run — are gone.
"""
import json
import logging
import re
import threading
from typing import Optional

import requests

from .config import (
    LLM_MAX_CONCURRENCY,
    OLLAMA_BASE_URL,
    OLLAMA_MAX_INPUT_CHARS,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
)
from .models import BookRecord
from .taxonomy import CANONICAL_CATEGORIES, constrain_categories
from .text_utils import is_mostly_boilerplate

logger = logging.getLogger(__name__)

# Ollama serves one generation at a time; keep the pipeline from stampeding it.
_llm_semaphore = threading.Semaphore(max(1, LLM_MAX_CONCURRENCY))
_availability: Optional[bool] = None
_availability_lock = threading.Lock()


class LLMNoResponse(Exception):
    """Ollama returned nothing usable (timeout, error, unparseable output)."""


def _str_list(value) -> list[str]:
    """Model output is JSON-shaped, not schema-checked: a bare string or nested list happens."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()]


def is_available(refresh: bool = False) -> bool:
    """True when Ollama is running and the configured model is installed."""
    global _availability
    with _availability_lock:
        if _availability is not None and not refresh:
            return _availability
        try:
            resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = [m.get("name", "") for m in resp.json().get("models", [])]
                base = OLLAMA_MODEL.split(":")[0]
                _availability = any(
                    m == OLLAMA_MODEL or m.startswith(base) for m in models
                )
                if not _availability:
                    logger.warning(
                        f"Ollama is running but model '{OLLAMA_MODEL}' is not installed. "
                        f"Available: {', '.join(models) or 'none'}"
                    )
            else:
                _availability = False
        except Exception as e:
            logger.debug(f"Ollama unavailable: {e}")
            _availability = False
        return _availability


def _generate(prompt: str, temperature: float = 0.3, num_predict: int = 512) -> Optional[str]:
    """One Ollama generation, serialised by the semaphore."""
    with _llm_semaphore:
        try:
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                    "options": {"temperature": temperature, "num_predict": num_predict},
                },
                timeout=OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except requests.Timeout:
            logger.warning(f"Ollama timed out after {OLLAMA_TIMEOUT}s")
            return None
        except Exception as e:
            logger.debug(f"Ollama call failed: {e}")
            return None


def _content_for_llm(record: BookRecord) -> str:
    """Context for the model: metadata plus prose (never the copyright page)."""
    parts = []
    if record.title:
        parts.append(f"Title: {record.title}")
    if record.subtitle:
        parts.append(f"Subtitle: {record.subtitle}")
    if record.authors:
        parts.append(f"Authors: {', '.join(record.authors)}")
    if record.publisher:
        parts.append(f"Publisher: {record.publisher}")
    if record.publication_year:
        parts.append(f"Year: {record.publication_year}")
    if record.description:
        parts.append(f"Publisher description: {record.description[:600]}")
    if record.subjects_raw:
        parts.append(f"External subjects: {', '.join(record.subjects_raw[:10])}")

    body = record.content_sample or ""
    if body and not is_mostly_boilerplate(body):
        parts.append(f"\nExcerpt from the body of the book:\n{body[:OLLAMA_MAX_INPUT_CHARS]}")
    return "\n".join(parts)


def generate_llm_summary(record: BookRecord, force: bool = False) -> BookRecord:
    """Summarise the book and map it onto the controlled category vocabulary."""
    if not force and record.summary and len(record.summary) > 120 and record.field_source("summary") == "llm":
        return record

    context = _content_for_llm(record)
    if len(context) < 80:
        return record

    allowed = "\n".join(f"- {c}" for c in CANONICAL_CATEGORIES)
    prompt = f"""You are a librarian cataloguing a book. Using only the information given, provide:
1. "summary": 2-3 sentences describing what this book is about.
2. "themes": up to 5 short thematic tags.
3. "categories": up to 3 labels chosen ONLY from this exact list (copy the label verbatim; if none fit, return an empty list):
{allowed}

Respond with JSON only, no commentary:
{{"summary": "...", "themes": ["..."], "categories": ["..."]}}

Book information:
{context}"""

    raw = _generate(prompt)
    result = _parse_llm_json(raw)
    if not result:
        raise LLMNoResponse(f"no usable summary for {record.file_name}")

    summary = " ".join(_str_list(result.get("summary")))
    if summary and len(summary) > 40:
        record.set_field("summary", summary[:600], "llm", 0.6)

    themes = _str_list(result.get("themes"))
    if themes:
        merged = list(dict.fromkeys([*record.themes, *themes]))[:8]
        record.set_field("themes", merged, "llm", 0.5, allow_equal=True)

    categories = constrain_categories(_str_list(result.get("categories")))
    if categories:
        merged = list(dict.fromkeys([*record.categories, *categories]))[:5]
        record.set_field("categories", merged, "llm", 0.5, allow_equal=True)

    logger.info(f"   🤖 LLM enriched: {record.file_name}")
    return record


def generate_llm_description(record: BookRecord) -> BookRecord:
    """Write a catalog description for books the providers had none for."""
    if record.description and len(record.description) > 80:
        return record

    context = _content_for_llm(record)
    if len(context) < 80:
        return record

    prompt = f"""You are a librarian writing a catalog description. Using only the information
given, write a clear, factual 3-5 sentence description of this book. Do not invent facts you
cannot support from the information. Output the description text only, with no preamble.

Book information:
{context}"""

    response = _generate(prompt, temperature=0.4)
    if response is None:
        raise LLMNoResponse(f"no description for {record.file_name}")
    if len(response.strip()) > 60:
        record.set_field("description", response.strip()[:2000], "llm", 0.45)
        logger.info(f"   🤖 Generated LLM description for {record.file_name}")
    return record


def adjudicate_match(record: BookRecord, candidate, evidence) -> Optional[bool]:
    """
    Judge a borderline candidate match.

    Returns True (same book), False (different book) or None (no opinion /
    LLM unavailable). Only called for scores in the 0.45–0.75 band.
    """
    if not is_available():
        return None

    local = [f"file name: {record.file_name}"]
    for clue in evidence.titles[:4]:
        local.append(f"{clue.source} title: {clue.text}")
    if evidence.authors:
        local.append(f"authors seen locally: {', '.join(evidence.authors[:3])}")
    if record.front_matter:
        local.append(f"title page text:\n{record.front_matter[:600]}")

    prompt = f"""Decide whether a local book file and a catalog record describe the SAME book.

LOCAL FILE:
{chr(10).join(local)}

CANDIDATE CATALOG RECORD ({candidate.provider}):
title: {candidate.full_title}
authors: {', '.join(candidate.authors) or 'unknown'}
year: {candidate.year or 'unknown'}
publisher: {candidate.publisher or 'unknown'}

Answer with JSON only: {{"same_book": true|false, "confidence": 0.0-1.0, "why": "short reason"}}"""

    raw = _generate(prompt, temperature=0.0, num_predict=200)
    parsed = _parse_llm_json(raw, required_key="same_book")
    if not parsed:
        return None

    decision = parsed.get("same_book")
    try:
        confidence = float(parsed.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return None
    if not isinstance(decision, bool) or confidence < 0.6:
        return None
    logger.info(
        f"   🤖 LLM adjudication for {record.file_name}: "
        f"{'match' if decision else 'mismatch'} ({str(parsed.get('why', ''))[:80]})"
    )
    return decision


def _parse_llm_json(raw: Optional[str], required_key: str = "summary") -> Optional[dict]:
    """Parse JSON from model output, tolerating fences and stray prose."""
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
        if isinstance(data, dict) and required_key in data:
            return data
    except json.JSONDecodeError:
        pass

    for match in re.finditer(r"\{.*?\}", text, re.DOTALL):
        try:
            data = json.loads(match.group())
            if isinstance(data, dict) and required_key in data:
                return data
        except json.JSONDecodeError:
            continue

    logger.debug(f"Failed to parse LLM JSON: {(raw or '')[:200]}")
    return None
