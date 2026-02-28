"""
Similar books engine using embeddings + metadata overlap.
"""
import logging
from typing import Optional
import numpy as np

from .db import BookDatabase

logger = logging.getLogger(__name__)


class SimilarityEngine:
    """Computes book similarity using embeddings and metadata."""

    def __init__(self, db: BookDatabase):
        self.db = db
        self.book_ids: list[str] = []
        self.content_matrix: Optional[np.ndarray] = None   # shape: (N, 384)
        self.metadata_matrix: Optional[np.ndarray] = None   # shape: (N, 384)
        self._id_to_idx: dict[str, int] = {}

    def load_embeddings(self):
        """Load all embeddings into NumPy matrices."""
        rows = self.db.get_all_embeddings()
        if not rows:
            logger.info("No embeddings found in database")
            return

        ids = []
        content_vecs = []
        metadata_vecs = []
        for book_id, content_blob, metadata_blob in rows:
            ids.append(book_id)
            if content_blob:
                content_vecs.append(np.frombuffer(content_blob, dtype=np.float32))
            else:
                content_vecs.append(np.zeros(384, dtype=np.float32))
            if metadata_blob:
                metadata_vecs.append(np.frombuffer(metadata_blob, dtype=np.float32))
            else:
                metadata_vecs.append(np.zeros(384, dtype=np.float32))

        self.book_ids = ids
        self._id_to_idx = {bid: i for i, bid in enumerate(ids)}
        self.content_matrix = np.vstack(content_vecs) if content_vecs else None
        self.metadata_matrix = np.vstack(metadata_vecs) if metadata_vecs else None

        logger.info(f"Loaded {len(ids)} embeddings into memory "
                     f"({self.content_matrix.nbytes / 1024:.0f} KB content, "
                     f"{self.metadata_matrix.nbytes / 1024:.0f} KB metadata)")

    @property
    def has_embeddings(self) -> bool:
        return self.content_matrix is not None and len(self.book_ids) > 0

    def find_similar(self, book_id: str, limit: int = 8, method: str = "combined") -> list[dict]:
        """Find similar books by embedding cosine similarity, with metadata fallback."""
        # Try embedding-based similarity first
        if self.has_embeddings and book_id in self._id_to_idx:
            idx = self._id_to_idx[book_id]

            if method == "content" and self.content_matrix is not None:
                vec = self.content_matrix[idx]
                scores = self.content_matrix @ vec
            elif method == "metadata" and self.metadata_matrix is not None:
                vec = self.metadata_matrix[idx]
                scores = self.metadata_matrix @ vec
            else:  # combined
                scores = np.zeros(len(self.book_ids))
                if self.content_matrix is not None:
                    vec_c = self.content_matrix[idx]
                    scores += 0.4 * (self.content_matrix @ vec_c)
                if self.metadata_matrix is not None:
                    vec_m = self.metadata_matrix[idx]
                    scores += 0.6 * (self.metadata_matrix @ vec_m)

            # Zero out self
            scores[idx] = -1.0

            # Get top-k
            top_indices = np.argsort(scores)[::-1][:limit]
            results = []
            for i in top_indices:
                if scores[i] <= 0:
                    continue
                bid = self.book_ids[i]
                book = self.db.get_book(bid)
                if book:
                    book["similarity_score"] = round(float(scores[i]) * 100, 1)
                    results.append(book)
            if results:
                return results

        # Fallback: metadata-based similarity (categories, themes, author)
        return self._metadata_fallback(book_id, limit)

    def _metadata_fallback(self, book_id: str, limit: int = 8) -> list[dict]:
        """Find similar books based on shared categories, themes, and author."""
        book = self.db.get_book(book_id)
        if not book:
            return []

        import json
        categories = json.loads(book.get("categories", "[]")) if isinstance(book.get("categories"), str) else (book.get("categories") or [])
        themes = json.loads(book.get("themes", "[]")) if isinstance(book.get("themes"), str) else (book.get("themes") or [])
        author = book.get("author_primary", "") or ""
        language = book.get("language", "")

        # Query all other books and score them
        all_books = self.db.conn.execute(
            "SELECT id, categories, themes, author_primary, language FROM books WHERE id != ?",
            (book_id,)
        ).fetchall()

        scored = []
        for row in all_books:
            other_id = row[0]
            other_cats = json.loads(row[1] or "[]") if isinstance(row[1], str) else (row[1] or [])
            other_themes = json.loads(row[2] or "[]") if isinstance(row[2], str) else (row[2] or [])
            other_author = row[3] or ""
            other_lang = row[4] or ""

            score = 0.0
            # Category overlap
            cat_overlap = len(set(categories) & set(other_cats))
            if cat_overlap > 0:
                score += cat_overlap * 25

            # Theme overlap
            theme_overlap = len(set(themes) & set(other_themes))
            if theme_overlap > 0:
                score += theme_overlap * 15

            # Same author
            if author and other_author and author.lower() == other_author.lower():
                score += 30

            # Same language
            if language and other_lang and language.lower() == other_lang.lower():
                score += 5

            if score > 0:
                scored.append((other_id, min(score, 99.0)))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        results = []
        for other_id, score in scored[:limit]:
            other_book = self.db.get_book(other_id)
            if other_book:
                other_book["similarity_score"] = round(score, 1)
                results.append(other_book)
        return results

    def semantic_search(self, query_embedding: np.ndarray, limit: int = 20) -> list[tuple[str, float]]:
        """Search by query embedding against all metadata embeddings."""
        if not self.has_embeddings or self.metadata_matrix is None:
            return []

        scores = self.metadata_matrix @ query_embedding
        top_indices = np.argsort(scores)[::-1][:limit]
        return [(self.book_ids[i], float(scores[i])) for i in top_indices if scores[i] > 0]

    def encode_query(self, text: str) -> Optional[np.ndarray]:
        """Encode a text query using sentence-transformers."""
        try:
            from catalog.embeddings import _get_model
            model = _get_model()
            if model:
                return model.encode(text, normalize_embeddings=True)
        except Exception as e:
            logger.warning(f"Failed to encode query: {e}")
        return None
