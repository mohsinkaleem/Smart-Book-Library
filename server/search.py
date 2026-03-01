"""
Unified search engine: FTS5 + semantic + hybrid.
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

    def _semantic_search(self, query: str, page: int, per_page: int, **filters) -> dict:
        """Semantic embedding search."""
        query_embedding = self.similarity.encode_query(query)
        if query_embedding is None:
            return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}

        # Get all matches (we'll paginate after)
        matches = self.similarity.semantic_search(query_embedding, limit=200)
        if not matches:
            return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}

        # Fetch and filter
        items = []
        for book_id, score in matches:
            book = self.db.get_book(book_id)
            if book and self._matches_filters(book, filters):
                book["_score"] = score
                book["match_type"] = "semantic"
                items.append(book)

        total = len(items)
        start = (page - 1) * per_page
        end = start + per_page
        pages = max(1, (total + per_page - 1) // per_page)

        return {
            "items": items[start:end],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }

    def _hybrid_search(self, query: str, page: int, per_page: int, **filters) -> dict:
        """Hybrid: FTS5 + semantic, merged scores."""
        # Get FTS results (all pages)
        fts_result = self.db.search_fts(query, page=1, per_page=200, **filters)
        fts_scores = {}
        for item in fts_result["items"]:
            fts_scores[item["id"]] = abs(item.get("_score", 0))

        # Get semantic results
        sem_items = []
        query_embedding = self.similarity.encode_query(query)
        sem_scores = {}
        if query_embedding is not None:
            matches = self.similarity.semantic_search(query_embedding, limit=200)
            for book_id, score in matches:
                sem_scores[book_id] = score

        # Normalize and merge
        all_ids = set(fts_scores.keys()) | set(sem_scores.keys())
        max_fts = max(fts_scores.values()) if fts_scores else 1.0
        max_sem = max(sem_scores.values()) if sem_scores else 1.0

        combined = {}
        for bid in all_ids:
            fts_norm = fts_scores.get(bid, 0) / max_fts if max_fts > 0 else 0
            sem_norm = sem_scores.get(bid, 0) / max_sem if max_sem > 0 else 0
            combined[bid] = 0.4 * fts_norm + 0.6 * sem_norm

        # Sort
        sorted_ids = sorted(combined.keys(), key=lambda x: combined[x], reverse=True)

        # Fetch and filter
        items = []
        for bid in sorted_ids:
            book = self.db.get_book(bid)
            if book and self._matches_filters(book, filters):
                book["_score"] = combined[bid]
                book["match_type"] = "hybrid"
                items.append(book)

        total = len(items)
        start = (page - 1) * per_page
        end = start + per_page
        pages = max(1, (total + per_page - 1) // per_page)

        return {
            "items": items[start:end],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }

    def suggest(self, query: str, limit: int = 8) -> list[dict]:
        return self.db.suggest(query, limit)

    def _matches_filters(self, book: dict, filters: dict) -> bool:
        """Client-side filter check (for semantic results)."""
        if filters.get("file_type") and book.get("file_type") != filters["file_type"]:
            return False
        if filters.get("category"):
            cats = book.get("categories", [])
            if filters["category"] not in cats:
                return False
        if filters.get("theme"):
            themes = book.get("themes", [])
            if filters["theme"] not in themes:
                return False
        if filters.get("language") and book.get("language") != filters["language"]:
            return False
        if filters.get("reading_status") and book.get("reading_status") != filters["reading_status"]:
            return False
        if filters.get("favorite") and not book.get("favorite"):
            return False
        if filters.get("has_cover") and not book.get("has_cover"):
            return False
        if filters.get("has_description") and not book.get("has_description"):
            return False
        if filters.get("year_min") is not None:
            year = book.get("publication_year")
            if year is None or year < int(filters["year_min"]):
                return False
        if filters.get("year_max") is not None:
            year = book.get("publication_year")
            if year is None or year > int(filters["year_max"]):
                return False
        if filters.get("author"):
            authors = book.get("authors", [])
            if filters["author"] not in authors:
                return False
        return True
