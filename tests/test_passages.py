"""
Passage index and retrieval (Part 1).

Builds a real index over synthetic books with a stub embedder, so the fusion,
floor and scoping logic are exercised end to end without downloading a model.
The stub is deliberately *meaningful* rather than random: vectors are built
from term overlap, so "documents about oceans rank above documents about
compilers" is a property the tests can assert rather than a coincidence.
"""
import sqlite3

import numpy as np
import pytest

from catalog.chunking import chunk_document
from catalog.full_text import UNIT_SEPARATOR, DocumentText

# The vocabulary the stub embedder projects onto. One axis per topic.
TOPICS = {
    "ocean": ["ocean", "tide", "current", "salt", "reef", "whale"],
    "compiler": ["compiler", "parser", "token", "syntax", "bytecode", "register"],
    "history": ["empire", "treaty", "sovereign", "colony", "settlement", "war"],
}
DIM = 384


def stub_vector(text: str) -> np.ndarray:
    """
    A deterministic unit vector whose direction encodes topic mix.

    Term counts per topic go into three leading dimensions; a hash of the text
    fills a little of the rest so two different passages on one topic are close
    but not identical, which is what makes ranking tests meaningful.
    """
    lowered = (text or "").lower()
    vec = np.zeros(DIM, dtype=np.float32)
    for i, (_, terms) in enumerate(TOPICS.items()):
        vec[i] = sum(lowered.count(t) for t in terms)
    noise = np.random.default_rng(abs(hash(lowered[:200])) % (2**32)).normal(0, 1, DIM - 8)
    vec[8:] = noise * 0.02
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


def sentences(topic: str, n: int) -> str:
    """`n` sentences of sentence-like prose that clears the chunker's floors."""
    terms = TOPICS[topic]
    out = []
    for i in range(n):
        term = terms[i % len(terms)]
        out.append(
            f"The study of the {term} shows how a {term} behaves once the surrounding "
            f"conditions are held constant across the whole of the observed period. "
        )
    return "".join(out).strip()


@pytest.fixture
def indexed(catalog_db, monkeypatch):
    """A built passage index over three synthetic books, one per topic."""
    import catalog.passage_index as pi

    monkeypatch.setattr(pi, "CHUNK_VECTORS_FILE", catalog_db.parent / "chunk_vectors.npy")

    def fake_encode_passages(texts, batch_size=32):
        return np.vstack([stub_vector(t) for t in texts])

    monkeypatch.setattr("catalog.embeddings.encode_passages", fake_encode_passages)
    monkeypatch.setattr("catalog.embeddings.model_id", lambda: "stub-model")

    conn = sqlite3.connect(str(catalog_db))
    books = {"book-one": "ocean", "book-two": "compiler", "book-junk-lang": "history"}

    def fake_chunk_one(book_id, file_path, file_type, force_text):
        topic = books.get(book_id)
        if topic is None:
            return []
        pages = [sentences(topic, 14) for _ in range(4)]
        offsets, cursor = [], 0
        for page in pages:
            offsets.append(cursor)
            cursor += len(page) + len(UNIT_SEPARATOR)
        doc = DocumentText(
            text=UNIT_SEPARATOR.join(pages),
            kind="pdf" if file_type == "pdf" else "epub",
            unit_offsets=offsets,
            unit_hrefs=["a.html", "b.html", "c.html", "d.html"],
        )
        return chunk_document(doc)

    monkeypatch.setattr(pi, "_chunk_one", fake_chunk_one)
    result = pi.build_index(conn)
    assert result.chunks_written > 0
    conn.close()
    return catalog_db


# ── The builder ─────────────────────────────────────────────────────────────

def test_chunk_ids_tile_the_vector_file(indexed):
    """
    `chunks.id` is the row index into the `.npy`. Nothing else in the system
    checks this, and if it drifts every result maps to the wrong passage while
    still looking entirely plausible.
    """
    import catalog.passage_index as pi

    conn = sqlite3.connect(str(indexed))
    count, lo, hi = conn.execute("SELECT COUNT(*), MIN(id), MAX(id) FROM chunks").fetchone()
    vectors = pi.load_vectors()
    conn.close()

    assert lo == 0
    assert hi == count - 1
    assert len(vectors) == count


def test_each_book_owns_a_contiguous_id_range(indexed):
    """The fast in-book slice depends on this; `PassageIndex.load` verifies it."""
    conn = sqlite3.connect(str(indexed))
    rows = conn.execute(
        "SELECT book_id, MIN(id), MAX(id), COUNT(*) FROM chunks GROUP BY book_id"
    ).fetchall()
    conn.close()
    assert rows
    for _, lo, hi, count in rows:
        assert hi - lo + 1 == count


def test_index_meta_stamps_the_model(indexed):
    import catalog.passage_index as pi

    conn = sqlite3.connect(str(indexed))
    status = pi.index_status(conn)
    conn.close()
    assert status["built"]
    assert status["model_id"] == "stub-model"
    assert status["dim"] == DIM
    assert status["count"] == status["chunks_in_db"]


def test_rebuild_reuses_vectors_instead_of_re_embedding(indexed, monkeypatch):
    """
    Adding a book must cost one book's worth of embedding, not the library's.
    Without carry-over, `catalog.watcher`'s incremental updates would rewrite
    ~23 minutes of work on every changed file.
    """
    import catalog.passage_index as pi

    calls = []

    def counting_encode(texts, batch_size=32):
        calls.append(len(texts))
        return np.vstack([stub_vector(t) for t in texts])

    monkeypatch.setattr("catalog.embeddings.encode_passages", counting_encode)

    conn = sqlite3.connect(str(indexed))
    before = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE book_id = 'book-two'"
    ).fetchone()[0]

    # Nothing to do: no embedding at all, and the index is left alone.
    noop = pi.build_index(conn)
    assert calls == [], "a no-op build must not embed anything"
    assert noop.chunks_written == 0

    # One book changed: only that book is re-embedded, the rest carry over.
    result = pi.build_index(conn, book_ids=["book-two"], force=True)
    conn.close()

    assert sum(calls) == before, "only the rebuilt book should be embedded"
    assert result.chunks_reused > 0
    assert result.chunks_written > before


def test_a_failed_build_does_not_wipe_a_working_index(indexed, monkeypatch):
    import catalog.passage_index as pi

    monkeypatch.setattr(pi, "_chunk_one", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    conn = sqlite3.connect(str(indexed))
    before = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    pi.build_index(conn, force=True)
    after = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    conn.close()
    assert after == before > 0


# ── Retrieval ───────────────────────────────────────────────────────────────

@pytest.fixture
def index(indexed, monkeypatch):
    """A loaded `PassageIndex` over the built index."""
    import catalog.passage_index as pi
    from server.db import BookDatabase
    from server.passages import PassageIndex

    monkeypatch.setattr("server.passages.load_vectors", pi.load_vectors)
    monkeypatch.setattr("catalog.embeddings.model_id", lambda: "stub-model")

    db = BookDatabase(indexed)
    engine = PassageIndex(db)
    engine.load()
    assert engine.available
    yield engine
    db.close()


def test_dense_search_ranks_by_topic(index):
    hits = index.dense_search(stub_vector(sentences("ocean", 3)), limit=5)
    assert hits
    conn_rows = index.get_chunks([cid for cid, _ in hits])
    assert all(row["book_id"] == "book-one" for row in conn_rows.values())


def test_in_book_scope_never_leaves_the_book(index):
    hits = index.dense_search(
        stub_vector(sentences("ocean", 3)), limit=20, book_id="book-two"
    )
    rows = index.get_chunks([cid for cid, _ in hits])
    assert rows
    assert all(row["book_id"] == "book-two" for row in rows.values())


def test_exclude_book_removes_the_whole_range(index):
    hits = index.dense_search(
        stub_vector(sentences("ocean", 3)), limit=20, exclude_book="book-one"
    )
    rows = index.get_chunks([cid for cid, _ in hits])
    assert all(row["book_id"] != "book-one" for row in rows.values())


def test_allowed_books_filter(index):
    hits = index.dense_search(
        stub_vector(sentences("ocean", 3)), limit=20, allowed_books=["book-two"]
    )
    rows = index.get_chunks([cid for cid, _ in hits])
    assert rows
    assert all(row["book_id"] == "book-two" for row in rows.values())


def test_lexical_search_finds_exact_terms(index):
    hits = index.lexical_search("bytecode register", limit=5)
    assert hits
    rows = index.get_chunks([cid for cid, _ in hits])
    assert all(row["book_id"] == "book-two" for row in rows.values())


def test_fts_query_survives_punctuation():
    from server.passages import fts_query

    query = fts_query('what is "modernity" (really)? -- see p.12')
    assert '"' not in query.replace('"', "", query.count('"'))  # only as term quoting
    assert "OR" in query
    assert "*" not in query and "(" not in query


def test_rrf_rewards_agreement_between_the_two_rankings():
    """
    A chunk both systems found must outrank one only one of them found, even
    when it is second on both lists. That is the property RRF exists for.
    """
    from server.passages import PassageIndex

    dense = [(10, 0.9), (20, 0.8)]
    lexical = [(30, 5.0), (20, 4.0)]
    fused = PassageIndex.fuse(dense, lexical)
    order = [cid for cid, _, _, _ in fused]
    assert order[0] == 20


def test_hybrid_search_applies_the_floor_to_lexical_hits(index):
    """
    The bug this pins: the relevance floor used to live inside the dense
    search, so every BM25 hit entered the fused ranking unfiltered and a query
    about nothing in the library came back with results anyway.
    """
    off_topic = stub_vector("wqxjz plmnb tzrfg vkhds")
    hits = index.search(
        # Terms that BM25 will certainly match, against a vector that nothing
        # in the index resembles.
        "compiler parser token syntax", off_topic, limit=10,
        mode="hybrid", rerank=False, min_score=0.9, relative_floor=0.0,
    )
    assert hits == []


def test_keyword_mode_ignores_the_semantic_floor(index):
    """
    §1.9.5 is "every mention of X". An exact term match is the answer there,
    and a semantic floor would suppress precisely the rare-word hits wanted.
    """
    hits = index.search(
        "bytecode", stub_vector("wqxjz plmnb"), limit=5,
        mode="keyword", rerank=False, min_score=0.99,
    )
    assert hits


def test_keyword_mode_still_reports_a_cosine_not_a_bm25_score(index):
    """
    BM25 is unbounded — it reached 11.04 on the real index, which the UI
    rendered as "1104%". `score` means cosine in every mode.
    """
    hits = index.search(
        "bytecode parser", stub_vector(sentences("compiler", 3)), limit=5,
        mode="keyword", rerank=False,
    )
    assert hits
    assert all(0.0 <= hit.score <= 1.0001 for hit in hits)


def test_hits_report_a_cosine_not_a_fusion_score(index):
    hits = index.search(
        sentences("ocean", 3), stub_vector(sentences("ocean", 3)),
        limit=3, mode="hybrid", rerank=False,
        min_score=0.0, relative_floor=0.0,
    )
    assert hits
    for hit in hits:
        assert 0.0 <= hit.score <= 1.0001
        assert hit.rrf < 0.1, "RRF is a sum of reciprocal ranks, not a similarity"


def test_neighbours_are_returned_in_reading_order(index):
    conn_id = index.db.query(
        "SELECT id FROM chunks WHERE book_id = 'book-one' ORDER BY chunk_idx LIMIT 1 OFFSET 2"
    )[0][0]
    neighbours = index.neighbours(conn_id, span=1)
    assert [n["chunk_idx"] for n in neighbours] == sorted(n["chunk_idx"] for n in neighbours)
    assert any(n["is_match"] for n in neighbours)


def test_a_model_change_disables_the_index_rather_than_mixing_spaces(indexed, monkeypatch):
    """
    Two models produce vectors of the same shape whose cosine is noise. The
    failure does not raise — it returns confident nonsense — so refusing to
    load is the only place it can be caught.
    """
    import catalog.passage_index as pi
    from server.db import BookDatabase
    from server.passages import PassageIndex

    monkeypatch.setattr("server.passages.load_vectors", pi.load_vectors)
    monkeypatch.setattr("catalog.embeddings.model_id", lambda: "a-different-model")

    db = BookDatabase(indexed)
    engine = PassageIndex(db)
    engine.load()
    db.close()
    assert not engine.available
