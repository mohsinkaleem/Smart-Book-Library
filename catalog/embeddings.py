"""
Embedding generation for semantic search and similarity.

Uses sentence-transformers to generate embeddings for:
1. text_excerpt (content embedding) - for similar book discovery
2. title + themes + description (metadata embedding) - for metadata search
"""
import logging
from typing import Optional

from .config import EMBEDDING_MODEL, EMBEDDING_DIMENSION
from .models import BookRecord

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
                "Run: pip install sentence-transformers\n"
                "Embeddings will be skipped."
            )
            return None
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            return None
    return _model


def generate_embeddings(record: BookRecord, force: bool = False) -> BookRecord:
    """
    Generate embeddings for a BookRecord.

    Creates two embeddings:
    1. Content embedding from text_excerpt
    2. Metadata embedding from title + themes + description + categories

    Args:
        record: BookRecord to generate embeddings for
        force: If True, regenerate even if embeddings exist
    """
    model = _get_model()
    if model is None:
        return record

    # Content embedding
    if (not record.embedding or force) and record.text_excerpt:
        try:
            text = record.text_excerpt[:2000]  # Limit input size
            embedding = model.encode(text, normalize_embeddings=True)
            record.embedding = embedding.tolist()
            logger.debug(f"Generated content embedding for {record.file_name}")
        except Exception as e:
            logger.error(f"Content embedding failed for {record.file_name}: {e}")
            record.processing_errors.append(f"Content embedding failed: {e}")

    # Metadata embedding
    if not record.metadata_embedding or force:
        meta_text = _build_metadata_text(record)
        if meta_text:
            try:
                embedding = model.encode(meta_text, normalize_embeddings=True)
                record.metadata_embedding = embedding.tolist()
                logger.debug(f"Generated metadata embedding for {record.file_name}")
            except Exception as e:
                logger.error(f"Metadata embedding failed for {record.file_name}: {e}")
                record.processing_errors.append(f"Metadata embedding failed: {e}")

    return record


def _build_metadata_text(record: BookRecord) -> str:
    """Build a text string from metadata fields for embedding."""
    parts = []

    if record.title:
        parts.append(f"Title: {record.title}")
    if record.authors:
        parts.append(f"Authors: {', '.join(record.authors)}")
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


def compute_similarity(embedding1: list, embedding2: list) -> float:
    """Compute cosine similarity between two embeddings."""
    if not embedding1 or not embedding2:
        return 0.0

    try:
        import numpy as np
        a = np.array(embedding1)
        b = np.array(embedding2)
        # Embeddings are already normalized, so dot product = cosine similarity
        return float(np.dot(a, b))
    except ImportError:
        # Fallback without numpy
        dot = sum(a * b for a, b in zip(embedding1, embedding2))
        norm_a = sum(a * a for a in embedding1) ** 0.5
        norm_b = sum(b * b for b in embedding2) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


def find_similar_books(
    target: BookRecord,
    all_records: list[BookRecord],
    top_k: int = 5,
    use_content: bool = True,
) -> list[tuple[BookRecord, float]]:
    """
    Find the most similar books to a target book.

    Args:
        target: The book to find similar ones for
        all_records: All books in the catalog
        top_k: Number of similar books to return
        use_content: If True, use content embedding; else metadata embedding

    Returns:
        List of (BookRecord, similarity_score) tuples, sorted by score desc
    """
    target_emb = target.embedding if use_content else target.metadata_embedding
    if not target_emb:
        return []

    similarities = []
    for record in all_records:
        if record.id == target.id:
            continue
        other_emb = record.embedding if use_content else record.metadata_embedding
        if other_emb:
            score = compute_similarity(target_emb, other_emb)
            similarities.append((record, score))

    similarities.sort(key=lambda x: x[1], reverse=True)
    return similarities[:top_k]
