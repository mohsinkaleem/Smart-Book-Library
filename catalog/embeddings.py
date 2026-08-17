"""
Embedding generation for semantic search and similarity.

Uses sentence-transformers to generate embeddings for:
1. content_sample (content embedding) - for similar book discovery
2. title + themes + description (metadata embedding) - for metadata search

Encoding is batched: `model.encode` on a list amortises the forward pass and is
an order of magnitude faster than one call per record.
"""
import logging
from typing import Iterable

from .config import EMBEDDING_BATCH_SIZE, EMBEDDING_MAX_INPUT_CHARS, EMBEDDING_MODEL
from .models import BookRecord
from .text_utils import is_mostly_boilerplate

logger = logging.getLogger(__name__)

_model = None


def _get_model():
    """Lazy-load the sentence-transformers model."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
            _model = SentenceTransformer(EMBEDDING_MODEL)
            logger.info("Embedding model loaded successfully")
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Run: pip install 'books[embed]'\n"
                "Embeddings will be skipped."
            )
            return None
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            return None
    return _model


def _content_text(record: BookRecord) -> str:
    """
    Prose past the TOC, never front matter. Embedding copyright pages made
    unrelated books look similar to each other, which is exactly wrong for
    "find books like this".
    """
    body = record.content_sample or ""
    if not body or is_mostly_boilerplate(body):
        return ""
    return body[:EMBEDDING_MAX_INPUT_CHARS]


def embed_records(records: Iterable[BookRecord], force: bool = False) -> list[BookRecord]:
    """Generate content and metadata embeddings for a batch of records."""
    records = list(records)
    model = _get_model()
    if model is None or not records:
        return records

    jobs: list[tuple[BookRecord, str, str]] = []
    for record in records:
        if force or not record.embedding:
            text = _content_text(record)
            if text:
                jobs.append((record, "embedding", text))
        if force or not record.metadata_embedding:
            meta = _build_metadata_text(record)
            if meta:
                jobs.append((record, "metadata_embedding", meta))
    if not jobs:
        return records

    try:
        vectors = model.encode(
            [text for _, _, text in jobs],
            batch_size=EMBEDDING_BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    except Exception as e:
        logger.error(f"Embedding batch of {len(jobs)} failed: {e}")
        for record, _, _ in jobs:
            record.processing_errors.append(f"Embedding failed: {e}")
        return records

    for (record, attr, _), vector in zip(jobs, vectors):
        setattr(record, attr, vector.tolist())
    return records


def generate_embeddings(record: BookRecord, force: bool = False) -> BookRecord:
    """Single-record convenience wrapper around `embed_records`."""
    embed_records([record], force=force)
    return record


def _build_metadata_text(record: BookRecord) -> str:
    """Build a text string from metadata fields for embedding."""
    parts = []

    if record.title:
        parts.append(f"Title: {record.title}")
    if record.authors:
        parts.append(f"Authors: {', '.join(record.authors)}")
    if record.subtitle:
        parts.append(f"Subtitle: {record.subtitle}")
    if record.description:
        parts.append(f"Description: {record.description[:500]}")
    if record.themes:
        parts.append(f"Themes: {', '.join(record.themes)}")
    if record.categories:
        parts.append(f"Categories: {', '.join(record.categories)}")
    if record.keywords:
        parts.append(f"Keywords: {', '.join(record.keywords)}")
    if record.summary:
        parts.append(f"Summary: {record.summary[:300]}")

    return ". ".join(parts)
