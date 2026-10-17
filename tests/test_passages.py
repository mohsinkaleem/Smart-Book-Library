"""
Passage index and retrieval (Part 1).

Builds a real index over synthetic books with a stub embedder, so the fusion,
floor and scoping logic are exercised end to end without downloading a model.
The stub is deliberately *meaningful* rather than random: vectors are built
from term overlap, so "documents about oceans rank above documents about
compilers" is a property the tests can assert rather than a coincidence.
"""
import sqlite3
import zlib

import numpy as np
import pytest

from catalog import full_text
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
    # `hash()` on a str is salted per process, so this used to seed the noise
    # differently on every run. The topic axes are orthogonal, which leaves
    # the noise as the entire dot product between two unrelated topics — and
    # `dense_search` drops a hit scoring <= 0. The scoping tests therefore
    # failed roughly one run in twelve, on a coin flip rather than on
    # anything they were asserting. crc32 is stable across processes.
    noise = np.random.default_rng(zlib.crc32(lowered[:200].encode())).normal(0, 1, DIM - 8)
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
    """A built passage index over the fixture's books, one topic each."""
    import catalog.passage_index as pi

    monkeypatch.setattr(pi, "CHUNK_VECTORS_FILE", catalog_db.parent / "chunk_vectors.npy")

    # Chunk rows store a span into `data/text/{book_id}.txt`, not the text, so
    # the cache the real extractor writes has to exist here too — carry-over
    # and every read path go through it.
    text_dir = catalog_db.parent / "text"
    text_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("catalog.full_text.TEXT_DIR", text_dir)
    full_text.clear_text_cache()

    def fake_encode_passages(texts, batch_size=32):
        return np.vstack([stub_vector(t) for t in texts])

    monkeypatch.setattr("catalog.embeddings.encode_passages", fake_encode_passages)
    monkeypatch.setattr("catalog.embeddings.model_id", lambda: "stub-model")

    conn = sqlite3.connect(str(catalog_db))
    # `book-one-again` is the fixture's hidden duplicate of `book-one`, and
    # carries the same topic — so if library-wide search ever stopped
    # excluding it, every ocean hit would come back twice.
    books = {
        "book-one": "ocean",
        "book-one-again": "ocean",
        "book-two": "compiler",
        "book-junk-lang": "history",
    }

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
        full_text.save_cached(book_id, doc)
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


OCEAN_BOOKS = {"book-one", "book-one-again"}


def test_dense_search_ranks_by_topic(index):
    hits = index.dense_search(stub_vector(sentences("ocean", 3)), limit=5)
    assert hits
    conn_rows = index.get_chunks([cid for cid, _ in hits])
    # Unfiltered: both copies of the ocean book are in the index and this
    # call says nothing about which the library shows.
    assert all(row["book_id"] in OCEAN_BOOKS for row in conn_rows.values())


def test_exclude_books_drops_a_hidden_duplicates_passages(index):
    """
    The library lists one copy of a book; its passages must not arrive from
    the other. Without this the top two hits for any query were the same
    paragraph twice — once per copy — which is what the Duplicates page
    exists to stop and what every search was doing anyway.
    """
    query = stub_vector(sentences("ocean", 3))
    unfiltered = index.get_chunks(
        [cid for cid, _ in index.dense_search(query, limit=20)]
    )
    assert any(r["book_id"] == "book-one-again" for r in unfiltered.values())

    hits = index.dense_search(query, limit=20, exclude_books=["book-one-again"])
    rows = index.get_chunks([cid for cid, _ in hits])
    assert rows, "excluding the copy must not empty the result"
    assert all(row["book_id"] != "book-one-again" for row in rows.values())
    assert any(row["book_id"] == "book-one" for row in rows.values())


def test_exclude_books_applies_to_the_lexical_side_too(index):
    """RRF fuses two lists; a copy filtered out of one still arrives via the other."""
    text = sentences("ocean", 3)
    unfiltered = index.get_chunks(
        [cid for cid, _ in index.lexical_search(text, limit=20)]
    )
    assert any(r["book_id"] == "book-one-again" for r in unfiltered.values())

    hits = index.lexical_search(text, limit=20, exclude_books=["book-one-again"])
    rows = index.get_chunks([cid for cid, _ in hits])
    assert all(row["book_id"] != "book-one-again" for row in rows.values())


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


# ── Chunk text lives on disk, not in the row ────────────────────────────────

def test_chunk_rows_carry_a_span_not_the_text(indexed):
    """
    The database must not hold a second copy of the library's prose. It held
    329 MB of one — more than the extracted text itself, because chunks
    overlap — plus a third copy inside the FTS index.
    """
    conn = sqlite3.connect(str(indexed))
    columns = {r[1] for r in conn.execute("PRAGMA table_info(chunks)")}
    conn.close()
    assert "text" not in columns
    assert "anchor_text" not in columns
    assert {"char_start", "char_end"} <= columns


def test_chunks_fts_is_contentless(indexed):
    conn = sqlite3.connect(str(indexed))
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'chunks_fts'"
    ).fetchone()[0]
    triggers = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' "
        "AND name LIKE 'chunks_a%'"
    ).fetchone()[0]
    conn.close()
    assert "content=''" in ddl
    assert triggers == 0, "a contentless index has no column for a trigger to read"


def test_every_chunk_reads_back_from_its_span(indexed):
    """The whole storage change rests on this: the span is the text."""
    from catalog.full_text import read_span

    conn = sqlite3.connect(str(indexed))
    rows = conn.execute(
        "SELECT book_id, chunk_idx, char_start, char_end FROM chunks ORDER BY id"
    ).fetchall()
    conn.close()
    assert rows
    for book_id, _, start, end in rows:
        text = read_span(book_id, start, end)
        assert text, f"{book_id} span {start}:{end} read back empty"
        assert len(text) <= end - start


def test_lexical_search_still_matches_after_the_text_moved(indexed):
    """BM25 over a contentless index is the half that had to keep working."""
    from server.db import BookDatabase
    from server.passages import PassageIndex

    db = BookDatabase(indexed)
    index = PassageIndex(db)
    index.load()
    hits = index.lexical_search("compiler", limit=5)
    assert hits, "the contentless FTS index returned nothing"

    chunks = index.get_chunks([cid for cid, _ in hits])
    assert all(c["text"] for c in chunks.values()), "hydration from disk failed"
    assert any("compiler" in c["text"].lower() for c in chunks.values())
    db.close()


def test_neighbours_are_hydrated_too(indexed):
    from server.db import BookDatabase
    from server.passages import PassageIndex

    db = BookDatabase(indexed)
    index = PassageIndex(db)
    index.load()
    conn = sqlite3.connect(str(indexed))
    middle = conn.execute(
        "SELECT id FROM chunks WHERE book_id = 'book-one' ORDER BY chunk_idx LIMIT 1 OFFSET 1"
    ).fetchone()[0]
    conn.close()

    around = index.neighbours(middle, span=1)
    assert len(around) >= 2
    assert all(c["text"] for c in around)
    assert sum(1 for c in around if c["is_match"]) == 1
    db.close()


# ── Diversity (§1.11) ───────────────────────────────────────────────────────

def test_consecutive_chunks_from_one_book_are_demoted(index):
    """
    Consecutive chunks overlap by `CHUNK_OVERLAP_CHARS`, so a page of them
    shows the reader the same prose two or three times. The fixture's books
    are each one topic repeated, which is the worst case for this: unordered,
    every hit is an adjacent chunk of the best one.
    """
    query = stub_vector(sentences("ocean", 3))
    hits = index.search(sentences("ocean", 3), query, limit=6, mode="hybrid",
                        rerank=False, min_score=0.0, relative_floor=0.0)
    assert len(hits) >= 4

    seen: dict[str, list[int]] = {}
    for hit in hits[:4]:
        for idx in seen.get(hit.book_id, []):
            assert abs(hit.chunk_idx - idx) > 1, (
                f"chunk {hit.chunk_idx} sits next to {idx} in {hit.book_id}"
            )
        seen.setdefault(hit.book_id, []).append(hit.chunk_idx)


def test_one_book_cannot_own_the_whole_page(index):
    """
    Measured on the real index before this existed: "quantum tunnelling"
    filled 8 of the dense top 20 from a single book. Other books discussing
    the topic were below the fold.
    """
    from catalog.config import PASSAGE_MAX_PER_BOOK

    query = stub_vector(sentences("ocean", 3))
    hits = index.search(sentences("ocean", 3), query, limit=6, mode="hybrid",
                        rerank=False, min_score=0.0, relative_floor=0.0)
    counts: dict[str, int] = {}
    for hit in hits:
        counts[hit.book_id] = counts.get(hit.book_id, 0) + 1
    # The fixture has two ocean books (one is the hidden duplicate) plus two
    # off-topic ones, so there is somewhere else for the page to go.
    assert max(counts.values()) <= PASSAGE_MAX_PER_BOOK


def test_diversity_demotes_rather_than_drops(index):
    """
    The page must not get shorter. Every demotion is a reordering: a hit is
    only lost when the candidate pool genuinely runs out, which is the
    difference between "nine books instead of one" and "four results instead
    of ten".
    """
    from server.passages import PassageIndex

    text = sentences("ocean", 3)
    query = stub_vector(text)
    diverse = index.search(text, query, limit=6, mode="hybrid", rerank=False,
                           min_score=0.0, relative_floor=0.0)

    # The same candidates, ranked by relevance alone.
    pool = index.to_hits(
        PassageIndex.fuse(
            index.dense_search(query, limit=18),
            index.lexical_search(text, limit=18),
        ),
        18,
    )
    flat = PassageIndex.diversify(
        pool, 6, max_per_book=0, neighbour_gap=0, demote_apparatus=False
    )

    assert len(diverse) == len(flat), "diversity must reorder the page, not shorten it"
    # And it must actually have reordered something: the fixture's books are
    # each one topic repeated, so relevance alone returns adjacent chunks.
    assert [h.chunk_id for h in diverse] != [h.chunk_id for h in flat]


def test_in_book_search_is_not_capped_per_book(index):
    """
    "Elsewhere in this book" is every hit from one book by definition. A
    per-book cap there would cut the page to three and call it diversity.
    """
    query = stub_vector(sentences("compiler", 3))
    hits = index.search(sentences("compiler", 3), query, limit=5, book_id="book-two",
                        mode="hybrid", rerank=False, min_score=0.0, relative_floor=0.0)
    assert len(hits) > 3
    assert all(hit.book_id == "book-two" for hit in hits)


# ── Apparatus, not argument ─────────────────────────────────────────────────

def test_apparatus_detection_catches_bibliographies():
    from server.passages import is_apparatus

    bibliography = (
        "Cambridge, MA: Harvard University Press. Wilson, Edward O. 1995. "
        "“The Morality of the Gene.” In Paul Thompson, ed. Issues in "
        "Evolutionary Ethics. New York: SUNY Press, pp. 153-168. Ruse, M. 1986. "
        "Taking Darwin Seriously. Oxford: Blackwell, vol. 2, no. 4. "
        "Retrieved from doi:10.1017/S0031819100065955. Available at "
        "proceedings of the Royal Society, ibid., pp. 12-18. "
    ) * 2
    assert is_apparatus(bibliography)

    contents = "Data Models and Query Languages. . . . . . . . . 27 " * 20
    assert is_apparatus(contents)


def test_footnoted_prose_is_not_apparatus():
    """
    The regression that made this a shared predicate instead of two copies:
    `vol.`, `p.` and `no.` appear three times in a page of real argument the
    moment it carries footnotes, and "three markers and out" demoted it. A
    bibliography has the markers and no sentences; a footnoted argument has
    both.
    """
    from server.passages import is_apparatus

    prose = (
        "The Ijtihaads of the Prophet were essentially a means of giving the "
        "companions lessons in the methods of Ijtihaad, and the Ijtihaads of the "
        "Sahaabah were at this early stage basically for practice. Islamic law in "
        "this period consisted of the laws of Sharee'ah which were revealed and "
        "recorded in the Qur'aan and the Sunnah. They relate mainly to the "
        "ideological foundation of Islam and to the socio-economic laws that were "
        "necessary for the organisation of the fledgling Muslim state. The basis "
        "of legislation in that period was therefore revelation itself, and the "
        "scholars who came later worked from it rather than beside it. "
        "See vol. 2, p. 41, no. 7 for the chain of transmission. "
    )
    assert not is_apparatus(prose)


def test_keyword_mode_keeps_apparatus(index):
    """
    §1.9.5 is "every mention of X across all 618 books". A reader hunting a
    citation is exactly the person a bibliography is the right answer for, so
    `keyword` mode does not demote it.
    """
    query = stub_vector(sentences("compiler", 3))
    hits = index.search("bytecode parser", query, limit=5, mode="keyword", rerank=False)
    assert hits


def test_the_same_passage_from_two_book_ids_is_shown_once(index):
    """
    `book-one-again` is the fixture's copy of `book-one` with the same text.
    `exclude_books` handles the copies the catalog has linked; on the real
    index three unlinked copies of one book each returned the same paragraph
    at the same score, so the text itself has to be checked too.
    """
    text = sentences("ocean", 3)
    hits = index.search(text, stub_vector(text), limit=6, mode="hybrid",
                        rerank=False, min_score=0.0, relative_floor=0.0)
    seen = [" ".join(hit.text.split())[:300].lower() for hit in hits]
    assert len(set(seen)) == len(seen), "the same passage came back twice"
