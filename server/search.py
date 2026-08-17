"""
Unified search engine: FTS5 + semantic + hybrid.

Semantic and hybrid used to take the top 200 embedding hits, filter them in
Python, and report `len(that list)` as `total` — so `total` was really "200 or
fewer", and paging to page 5 recomputed every similarity and re-fetched every
book before slicing. They also filtered through a second, hand-written copy of
the filter predicates that had already drifted from the SQL one and silently
ignored `tag`.

Now: score the whole matrix in one matmul, intersect with the ID set SQL says
matches the filters, and paginate over the real result.
"""
import logging
from typing import Optional

from .db import BookDatabase
from .similarity import SimilarityEngine

logger = logging.getLogger(__name__)


class SearchEngine:
    """Unified search across FTS5 text search and semantic embeddings."""

    def __init__(self, db: BookDatabase, similarity: SimilarityEngine):
        self.db = db
        self.similarity = similarity

    def search(
        self,
        query: str,
        mode: str = "text",
        page: int = 1,
        per_page: int = 48,
        **filters,
    ) -> dict:
        """Run search in the specified mode."""
        if mode == "semantic":
            return self._semantic_search(query, page, per_page, **filters)
        elif mode == "hybrid":
            return self._hybrid_search(query, page, per_page, **filters)
        else:
            return self._text_search(query, page, per_page, **filters)

    def _text_search(self, query: str, page: int, per_page: int, **filters) -> dict:
        """FTS5 text search."""
        result = self.db.search_fts(query, page=page, per_page=per_page, **filters)
        for item in result["items"]:
            item["match_type"] = "fts"
        return result

    def _page(
        self,
        scored: list[tuple[str, float]],
        page: int,
        per_page: int,
        match_type: str,
        snippets: Optional[dict[str, str]] = None,
    ) -> dict:
        """
        Hydrate one page out of a ranked (book_id, score) list.

        `snippets` carries the FTS side's `snippet()` output through, so a
        hybrid result that matched on text still shows why. Semantic-only
        hits have nothing to highlight and get no snippet.
        """
        total = len(scored)
        start = (page - 1) * per_page
        window = scored[start:start + per_page]

        books = self.db.get_books_by_ids([bid for bid, _ in window])
        items = []
        for book_id, score in window:
            book = books.get(book_id)
            if not book:
                continue
            book["_score"] = score
            book["match_type"] = match_type
            if snippets and book_id in snippets:
                book["snippet"] = snippets[book_id]
                book["match_field"] = "text"
            items.append(book)

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def _semantic_search(self, query: str, page: int, per_page: int, **filters) -> dict:
        """Semantic embedding search over the full catalog."""
        query_embedding = self.similarity.encode_query(query)
        if query_embedding is None:
            return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}

        allowed = self.db.filtered_ids(**filters)
        scored = self.similarity.semantic_search(query_embedding, allowed_ids=allowed)
        if not scored:
            return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}

        return self._page(scored, page, per_page, "semantic")

    def _hybrid_search(self, query: str, page: int, per_page: int, **filters) -> dict:
        """Hybrid: FTS5 + semantic, merged on normalised scores."""
        allowed = self.db.filtered_ids(**filters)

        # FTS side — one pass over the whole matching set, not just page 1.
        fts_result = self.db.search_fts(query, page=1, per_page=10_000, **filters)
        fts_scores = {item["id"]: abs(item.get("_score", 0)) for item in fts_result["items"]}
        snippets = {
            item["id"]: item["snippet"]
            for item in fts_result["items"]
            if item.get("snippet")
        }

        # Semantic side
        sem_scores: dict[str, float] = {}
        query_embedding = self.similarity.encode_query(query)
        if query_embedding is not None:
            sem_scores = dict(
                self.similarity.semantic_search(query_embedding, allowed_ids=allowed)
            )

        max_fts = max(fts_scores.values(), default=0.0)
        max_sem = max(sem_scores.values(), default=0.0)

        combined: list[tuple[str, float]] = []
        for bid in set(fts_scores) | set(sem_scores):
            fts_norm = fts_scores.get(bid, 0) / max_fts if max_fts > 0 else 0
            sem_norm = sem_scores.get(bid, 0) / max_sem if max_sem > 0 else 0
            combined.append((bid, 0.4 * fts_norm + 0.6 * sem_norm))
        combined.sort(key=lambda pair: pair[1], reverse=True)

        return self._page(combined, page, per_page, "hybrid", snippets)

    def suggest(self, query: str, limit: int = 8) -> list[dict]:
        return self.db.suggest(query, limit)
