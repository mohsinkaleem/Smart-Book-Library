"""
The semantic relevance floors, and the fact that they are model-specific.

These constants were tuned to `all-MiniLM-L6-v2`'s score spread. Carried over
unchanged to `BAAI/bge-small-en-v1.5` — which packs every score into a high,
narrow band — they sat below the *noise* floor, and a nonsense query returned
all 618 books. The numbers below are the measured band for the current model;
if a model change moves it, these tests fail rather than the search silently
returning the whole library.
"""
import numpy as np
import pytest

from server.similarity import (
    EMBEDDING_DIM,
    MIN_SEMANTIC_SCORE,
    SEMANTIC_RELATIVE_FLOOR,
    SimilarityEngine,
)

# Measured on this catalog, 2026-08-19, bge-small-en-v1.5 — see `similarity.py`.
REAL_QUERY_TOP_SCORES = (0.655, 0.834)
NONSENSE_TOP_SCORES = (0.564, 0.621)


class FakeDB:
    """Just enough of `BookDatabase` for the ranking path."""

    def __init__(self, rows):
        self._rows = rows

    def get_all_embeddings(self):
        return self._rows

    def get_book(self, book_id):
        return {"id": book_id, "title": book_id}


def engine_over(scores: list[float]) -> SimilarityEngine:
    """
    An engine whose books score exactly `scores` against a fixed query.

    Built by putting each score in the first dimension of an otherwise-zero
    unit vector, so `matrix @ query` reproduces them verbatim.
    """
    rows = []
    for i, score in enumerate(scores):
        vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        vec[0] = score
        rows.append((f"book-{i}", vec.tobytes(), vec.tobytes(), ""))

    engine = SimilarityEngine(FakeDB(rows))
    engine.load_embeddings()
    return engine


@pytest.fixture
def query():
    q = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    q[0] = 1.0
    return q


def test_the_absolute_floor_sits_above_the_nonsense_band():
    """What makes "no results" possible at all."""
    assert MIN_SEMANTIC_SCORE > NONSENSE_TOP_SCORES[1]


def test_the_absolute_floor_sits_below_the_weakest_real_query():
    """A real query on a subject the library barely covers must still match."""
    assert MIN_SEMANTIC_SCORE < REAL_QUERY_TOP_SCORES[0]


def test_a_nonsense_query_returns_nothing(query):
    """The regression: every book in the library, reported as a match."""
    engine = engine_over([0.62, 0.60, 0.58, 0.56, 0.54])
    assert engine.semantic_search(query, limit=None) == []


def test_a_real_query_returns_its_matches(query):
    engine = engine_over([0.83, 0.78, 0.75, 0.71, 0.55])
    results = engine.semantic_search(query, limit=None)
    assert [book_id for book_id, _ in results] == ["book-0", "book-1", "book-2", "book-3"]


def test_the_relative_floor_cuts_the_tail_of_a_dominant_subject(query):
    """
    Hundreds of books can clear the absolute floor on this catalog's main
    subject; only the top of that ranking is worth showing.
    """
    engine = engine_over([0.90, 0.88, 0.86, 0.70, 0.68])
    returned = [book_id for book_id, _ in engine.semantic_search(query, limit=None)]
    # 0.70 is above MIN_SEMANTIC_SCORE but below 0.84 x 0.90.
    assert returned == ["book-0", "book-1", "book-2"]


def test_results_are_ordered_best_first(query):
    engine = engine_over([0.70, 0.83, 0.75])
    scores = [score for _, score in engine.semantic_search(query, limit=None)]
    assert scores == sorted(scores, reverse=True)


def test_limit_truncates_without_changing_the_floor(query):
    engine = engine_over([0.83, 0.80, 0.78, 0.76])
    assert len(engine.semantic_search(query, limit=2)) == 2


def test_passage_search_is_not_floored(query):
    """
    Compare ranks a paragraph against book-level vectors and takes the best
    few whatever they score — a floor tuned for search-box queries would make
    "Similar in Other Books" empty on most selections.
    """
    engine = engine_over([0.42, 0.38, 0.31])
    assert len(engine.passage_search(query, limit=None)) == 3


def test_the_floors_are_documented_as_model_specific():
    """A model swap must re-measure these; the comment is the only warning."""
    import inspect

    import server.similarity as module

    source = inspect.getsource(module)
    assert "bge-small-en-v1.5" in source
    assert "re-measured" in source or "re-measure" in source
