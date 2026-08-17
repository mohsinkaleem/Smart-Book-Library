"""
Similar books engine using embeddings + metadata overlap.
"""
import logging
from typing import Iterable, Optional
import numpy as np

from .db import BookDatabase

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384

# Relevance floor for semantic ranking.
#
# Every book gets a cosine score against every query, and on a 544-book
# catalog almost all of them are positive: a nonsense query ("zebra
# husbandry") still scores 306 books above zero. Ranking the whole matrix is
# right — it is what makes `total` honest instead of the size of an arbitrary
# 200-row cap — but "honest" cannot mean reporting the entire library as
# matching. Two floors, and a book must clear both:
#
# * `MIN_SEMANTIC_SCORE` is absolute, and set from the measured distribution:
#   a query with nothing to match tops out around 0.17, while real matches
#   start around 0.35. It is what makes "no results" possible at all.
# * `SEMANTIC_RELATIVE_FLOOR` is proportional to the best hit, and handles
#   the opposite case — a query on this catalog's dominant subject where
#   hundreds of books clear the absolute floor and only the top of the
#   ranking is worth showing.
#
# Neither can drop an exact keyword match: in hybrid mode the FTS side is
# unioned in after this runs.
MIN_SEMANTIC_SCORE = 0.28
SEMANTIC_RELATIVE_FLOOR = 0.55


class SimilarityEngine:
    """Computes book similarity using embeddings and metadata."""

    def __init__(self, db: BookDatabase):
        self.db = db
        self.book_ids: list[str] = []
        self.content_matrix: Optional[np.ndarray] = None   # shape: (N, 384)
        self.metadata_matrix: Optional[np.ndarray] = None   # shape: (N, 384)
        self._id_to_idx: dict[str, int] = {}

    @staticmethod
    def _to_vector(blob: Optional[bytes], book_id: str, kind: str) -> np.ndarray:
        """
        Decode one embedding blob, or a zero vector if it is unusable.

        A single truncated blob used to make `np.vstack` raise at startup,
        which killed similarity for the whole catalog.
        """
        if not blob:
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)
        vec = np.frombuffer(blob, dtype=np.float32)
        if vec.shape != (EMBEDDING_DIM,):
            logger.warning(
                f"Ignoring malformed {kind} embedding for {book_id}: "
                f"expected {EMBEDDING_DIM} floats, got {vec.size}"
            )
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)
        return vec

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
            content_vecs.append(self._to_vector(content_blob, book_id, "content"))
            metadata_vecs.append(self._to_vector(metadata_blob, book_id, "metadata"))

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
        all_books = self.db.query(
            "SELECT id, categories, themes, author_primary, language FROM books "
            "WHERE id != ? AND status != 'missing'",
            (book_id,)
        )

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

    def _rank(
        self,
        matrix: Optional[np.ndarray],
        query_embedding: np.ndarray,
        limit: Optional[int],
        allowed_ids: Optional[Iterable[str]],
        min_score: float = 0.0,
        relative_floor: float = 0.0,
    ) -> list[tuple[str, float]]:
        """
        Score every row of `matrix` against the query, best first.

        `min_score` and `relative_floor` are both applied; a book must clear
        the higher of the two. See `MIN_SEMANTIC_SCORE` for why a floor is
        needed at all.
        """
        if not self.has_embeddings or matrix is None:
            return []

        scores = matrix @ query_embedding
        order = np.argsort(scores)[::-1]

        best = float(scores[order[0]]) if len(order) else 0.0
        cutoff = max(min_score, best * relative_floor)

        allowed = set(allowed_ids) if allowed_ids is not None else None
        results: list[tuple[str, float]] = []
        for i in order:
            score = float(scores[i])
            # Sorted descending, so the first book below the cutoff ends it.
            if score <= 0 or score < cutoff:
                break
            book_id = self.book_ids[i]
            if allowed is not None and book_id not in allowed:
                continue
            results.append((book_id, score))
            if limit is not None and len(results) >= limit:
                break
        return results

    def semantic_search(
        self,
        query_embedding: np.ndarray,
        limit: Optional[int] = None,
        allowed_ids: Optional[Iterable[str]] = None,
    ) -> list[tuple[str, float]]:
        """
        Rank books by *metadata* embedding against a query embedding.

        `limit=None` ranks the whole catalog, which is what paginated search
        needs — one matmul over N×384 is cheap, and it means `total` is the
        real number of matches rather than the size of an arbitrary cap.
        Results below the relevance floor are dropped, so "the real number of
        matches" does not degenerate into "every book in the library".
        """
        return self._rank(
            self.metadata_matrix, query_embedding, limit, allowed_ids,
            min_score=MIN_SEMANTIC_SCORE,
            relative_floor=SEMANTIC_RELATIVE_FLOOR,
        )

    def passage_search(
        self,
        query_embedding: np.ndarray,
        limit: Optional[int] = None,
        allowed_ids: Optional[Iterable[str]] = None,
    ) -> list[tuple[str, float]]:
        """
        Rank books by *content* embedding — for comparing a passage of prose.

        `/api/reading/compare` used to score selected passages against the
        metadata embeddings ("Title: … Authors: … Themes: …"), which is why
        "Similar in Other Books" returned topical near-misses instead of
        passages that actually resemble the selection.
        """
        return self._rank(self.content_matrix, query_embedding, limit, allowed_ids)

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
