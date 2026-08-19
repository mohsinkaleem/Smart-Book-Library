"""
Passage retrieval over the chunk index (§1.8).

One matrix, one BM25 index, three ways of narrowing them:

| Query                    | Filter                | Measured here |
|--------------------------|-----------------------|---------------|
| Elsewhere in this book   | one contiguous slice  | 0.008 ms      |
| Across the catalog       | exclude current book  | 0.30 ms       |
| Within a category/author | id set intersection   | 0.30 ms       |

Measured over the 23,920-chunk index on 2026-08-19; §1.3 projects 4.8 ms at the
full library's ~272k vectors, and 0.30 ms at 23,920 scales to about that.

Brute force, deliberately. A float32 matmul plus `argpartition` is well inside
a frame at either size. An ANN index would add a dependency, a
build step and approximation error to make an already-imperceptible query
faster, and would cost recall tuning and "why did it miss that paragraph"
debugging forever after.

**The book slice is free because the builder writes books contiguously.**
`catalog.passage_index` assigns ids in book order, so every book owns one
unbroken id range and "elsewhere in this book" slices the matrix before the
matmul rather than masking after it. `load` verifies that contiguity instead of
assuming it — if a future builder breaks it, the slice silently returns another
book's passages, which is exactly the class of failure this codebase keeps
finding the hard way.

**Hybrid retrieval.** Dense search and a `chunks_fts` BM25 search are fused
with Reciprocal Rank Fusion (`score = Σ 1/(k + rank)`). RRF needs no score
normalisation between the two systems, which is the usual source of
hybrid-search bugs: BM25 is unbounded and cosine is not, so any attempt to
average them directly is a hidden weighting.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np

from catalog.config import (
    PASSAGE_RERANK,
    PASSAGE_RERANK_CANDIDATES,
    PASSAGE_RERANK_MODEL,
    RRF_K,
)
from catalog.passage_index import index_status, load_vectors

from .db import BookDatabase

logger = logging.getLogger(__name__)

# ── Relevance floors, measured on this index ────────────────────────────────
#
# §1.4 warned that the floors in `similarity.py` are a property of the model's
# score distribution rather than of the catalog, and would not transfer to
# chunk scores unchanged. They do not — and the way they fail to transfer is
# not the way that warning implied.
#
# Measured on 2026-08-19 over this index (23,920 chunks, 59 books) with the
# §1.4 protocol: six real queries against four nonsense ones.
#
#     real queries    top score 0.694 - 0.844     50th/best 0.88 - 0.95
#     nonsense        top score 0.609 - 0.642     50th/best 0.89 - 0.95
#
# **The absolute floor works and the relative floor does not.** At book level
# the two bands nearly touched (0.03 apart) and the relative floor did the real
# discriminating. At chunk level it is the reverse: the absolute bands separate
# cleanly, by 0.05, and the *relative* bands overlap completely — 0.88-0.95
# against 0.89-0.95, with no gap at all to place a cutoff in.
#
# That is not noise, it is the shape of the data. A book-level ranking over 618
# metadata vectors goes flat for a nonsense query because nothing is genuinely
# more relevant than anything else. A chunk ranking over 23,920 passages is
# always steep — some passage is always more textually similar to any input
# than the 50th one is, real query or not — so the *shape* of the ranking stops
# carrying the signal and only its height does.
#
# So `MIN_PASSAGE_SCORE` sits in the measured gap, and the relative floor is
# kept only as a long-tail trim, not as a relevance judgement. Do not tighten
# it hoping it will reject nonsense; it cannot, and tightening it will start
# discarding real results instead.
MIN_PASSAGE_SCORE = 0.66
PASSAGE_RELATIVE_FLOOR = 0.80

# Passage-to-passage comparison is a third distribution. The query is a real
# 1,500-character passage rather than a short phrase, so everything scores
# higher: measured over six passages drawn from the index, the second-best
# match (the first that is not the passage itself) scores 0.867-0.923 and the
# 200th scores 0.689-0.716. A floor calibrated for short queries would return
# most of the book, so this one is separate and higher.
MIN_SIMILAR_PASSAGE_SCORE = 0.75

# fts5 treats these as syntax. A user typing `what is "modernity"?` should get
# a search, not a `fts5: syntax error near`.
_FTS_UNSAFE = re.compile(r'["*():^-]')


@dataclass
class PassageHit:
    """One retrieved chunk, with everything needed to show and cite it."""

    chunk_id: int
    book_id: str
    chunk_idx: int
    text: str
    # The cosine against the query — interpretable, comparable between
    # queries, and the number every floor in this module is calibrated on.
    score: float
    # The Reciprocal Rank Fusion value. It decides the *order* and nothing
    # else: it is a sum of reciprocal ranks, so it lives around 0.03 and means
    # nothing on its own. Returning it as `score` made every result look like a
    # 3% match and, worse, made the floors unenforceable — they are cosine
    # thresholds and RRF is not a cosine.
    rrf: float = 0.0
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    spine_index: Optional[int] = None
    anchor_text: str = ""
    section: str = ""
    dense_rank: Optional[int] = None
    lexical_rank: Optional[int] = None


def fts_query(text: str, max_terms: int = 24) -> str:
    """
    A safe fts5 query from arbitrary user text.

    Terms are OR'd rather than AND'd: this is the lexical half of a hybrid
    search, and its job is recall on exact terminology and proper nouns. RRF
    handles precision by only rewarding terms that also rank well densely.
    """
    cleaned = _FTS_UNSAFE.sub(" ", text or "")
    terms = [t for t in cleaned.split() if len(t) > 2][:max_terms]
    return " OR ".join(f'"{t}"' for t in terms)


class PassageIndex:
    """The loaded chunk index. One instance, held on `app.state`."""

    def __init__(self, db: BookDatabase):
        self.db = db
        self.matrix: Optional[np.ndarray] = None
        self.meta: dict = {}
        self.book_ranges: dict[str, tuple[int, int]] = {}   # book_id -> [start, end)
        self._reranker = None
        self._reranker_tried = False

    # ── Loading ────────────────────────────────────────────────────────────

    def load(self) -> None:
        """
        Load the vector file and the book→id-range map.

        Refuses to load an index built by another model, for the same reason
        `SimilarityEngine.load_embeddings` skips mismatched rows: two models
        produce vectors of the same shape whose cosine is noise. That failure
        does not raise, it returns confident nonsense, so it has to be caught
        here or not at all.
        """
        status = index_status(self.db.conn)
        self.meta = status
        if not status.get("built") or not status.get("chunks_in_db"):
            logger.info("No passage index built; passage search is unavailable")
            return

        try:
            from catalog.embeddings import model_id
            expected = model_id()
        except Exception:
            expected = ""

        stored = status.get("model_id") or ""
        if expected and stored and stored != expected:
            logger.warning(
                f"Passage index was built with {stored!r} but the catalog is configured "
                f"for {expected!r}. Passage search is disabled — rebuild with "
                f"`python scripts/build_passage_index.py --force`."
            )
            return

        matrix = load_vectors()
        if matrix is None:
            logger.warning("Passage index rows exist but the vector file is missing")
            return

        rows = self.db.query(
            "SELECT book_id, MIN(id), MAX(id), COUNT(*) FROM chunks GROUP BY book_id"
        )
        if rows and rows[0][2] + 1 != len(matrix) and max(r[2] for r in rows) >= len(matrix):
            logger.warning(
                f"Passage index is inconsistent: {len(matrix)} vectors but chunk ids "
                f"reach {max(r[2] for r in rows)}. Rebuild the index."
            )
            return

        ranges: dict[str, tuple[int, int]] = {}
        broken = []
        for book_id, lo, hi, count in rows:
            if hi - lo + 1 != count:
                broken.append(book_id)
                continue
            ranges[book_id] = (lo, hi + 1)
        if broken:
            # Not fatal — those books fall back to the masked catalog-wide path,
            # which is correct, just not free.
            logger.warning(
                f"{len(broken)} books have non-contiguous chunk ids; "
                f"their in-book search will not use the fast slice"
            )

        self.matrix = matrix
        self.book_ranges = ranges
        logger.info(
            f"Passage index loaded: {len(matrix)} chunks over {len(rows)} books "
            f"({matrix.nbytes / 1024 / 1024:.0f} MB resident)"
        )

    @property
    def available(self) -> bool:
        return self.matrix is not None and len(self.matrix) > 0

    # ── Dense search ───────────────────────────────────────────────────────

    def _allowed_mask(self, allowed_books: Optional[Iterable[str]]) -> Optional[np.ndarray]:
        """A row mask for a book-id filter, built from the contiguous ranges."""
        if allowed_books is None:
            return None
        mask = np.zeros(len(self.matrix), dtype=bool)
        for book_id in allowed_books:
            span = self.book_ranges.get(book_id)
            if span:
                mask[span[0]:span[1]] = True
        return mask

    def dense_search(
        self,
        query_vec: np.ndarray,
        limit: int = 20,
        book_id: Optional[str] = None,
        exclude_book: Optional[str] = None,
        allowed_books: Optional[Iterable[str]] = None,
        min_score: float = 0.0,
        relative_floor: float = 0.0,
    ) -> list[tuple[int, float]]:
        """
        Top-`limit` chunk ids by cosine, best first.

        Scoping to one book slices the matrix before the matmul — that is the
        0.003 ms row in the table above, and it is why "elsewhere in this book"
        is the cheapest query in the system rather than the most expensive.
        """
        if not self.available or query_vec is None:
            return []

        offset = 0
        matrix = self.matrix
        if book_id is not None:
            span = self.book_ranges.get(book_id)
            if span is None:
                return []
            offset, matrix = span[0], self.matrix[span[0]:span[1]]

        scores = matrix @ query_vec.astype(np.float32)

        if book_id is None:
            mask = self._allowed_mask(allowed_books)
            if mask is not None:
                scores = np.where(mask, scores, -1.0)
            if exclude_book:
                span = self.book_ranges.get(exclude_book)
                if span:
                    scores[span[0]:span[1]] = -1.0

        if not len(scores):
            return []

        take = min(limit * 4, len(scores))
        top = np.argpartition(scores, -take)[-take:]
        top = top[np.argsort(scores[top])[::-1]]

        best = float(scores[top[0]])
        cutoff = max(min_score, best * relative_floor)

        out: list[tuple[int, float]] = []
        for i in top:
            score = float(scores[i])
            if score <= 0 or score < cutoff:
                break
            out.append((int(i) + offset, score))
            if len(out) >= limit:
                break
        return out

    # ── Lexical search ─────────────────────────────────────────────────────

    def lexical_search(
        self,
        text: str,
        limit: int = 20,
        book_id: Optional[str] = None,
        exclude_book: Optional[str] = None,
        allowed_books: Optional[Iterable[str]] = None,
    ) -> list[tuple[int, float]]:
        """
        BM25 over `chunks_fts`. Free to build and unbeatable for exact
        terminology and proper nouns, blind to paraphrase — the complement.
        """
        query = fts_query(text)
        if not query:
            return []

        sql = [
            "SELECT c.id, bm25(chunks_fts) AS rank FROM chunks_fts",
            "JOIN chunks c ON c.id = chunks_fts.rowid",
            "WHERE chunks_fts MATCH ?",
        ]
        params: list = [query]
        if book_id is not None:
            sql.append("AND c.book_id = ?")
            params.append(book_id)
        if exclude_book:
            sql.append("AND c.book_id != ?")
            params.append(exclude_book)
        if allowed_books is not None:
            allowed = list(allowed_books)
            if not allowed:
                return []
            sql.append(f"AND c.book_id IN ({','.join('?' * len(allowed))})")
            params.extend(allowed)
        sql.append("ORDER BY rank LIMIT ?")
        params.append(limit)

        try:
            rows = self.db.query(" ".join(sql), params)
        except Exception as e:
            logger.warning(f"Chunk FTS query failed: {e}")
            return []
        # bm25() is negative and more-negative is better; flip it so every
        # score in this module reads the same way round.
        return [(int(r[0]), -float(r[1])) for r in rows]

    # ── Fusion ─────────────────────────────────────────────────────────────

    @staticmethod
    def fuse(
        dense: list[tuple[int, float]],
        lexical: list[tuple[int, float]],
        k: int = RRF_K,
    ) -> list[tuple[int, float, Optional[int], Optional[int]]]:
        """
        Reciprocal Rank Fusion of two rankings.

        Returns `(chunk_id, fused_score, dense_rank, lexical_rank)`. The ranks
        are carried through because "this came from the lexical side" is the
        difference between a hit a reader trusts and one they cannot explain.
        """
        dense_rank = {cid: i for i, (cid, _) in enumerate(dense)}
        lexical_rank = {cid: i for i, (cid, _) in enumerate(lexical)}
        fused: dict[int, float] = {}
        for cid, rank in dense_rank.items():
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank + 1)
        for cid, rank in lexical_rank.items():
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank + 1)
        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
        return [
            (cid, score, dense_rank.get(cid), lexical_rank.get(cid))
            for cid, score in ordered
        ]

    # ── Reranking (§1.11 phase 2) ──────────────────────────────────────────

    def _get_reranker(self):
        """
        The cross-encoder, loaded on first use.

        Off unless `PASSAGE_RERANK` is set, because the model is an ~80 MB
        download and a surprise download on someone's first search is not a
        feature. A failure to load is recorded once and never retried — a
        reranker that cannot load must cost one warning, not one per query.
        """
        if not PASSAGE_RERANK or self._reranker_tried:
            return self._reranker
        self._reranker_tried = True
        try:
            from sentence_transformers import CrossEncoder
            logger.info(f"Loading cross-encoder {PASSAGE_RERANK_MODEL}")
            self._reranker = CrossEncoder(PASSAGE_RERANK_MODEL)
        except Exception as e:
            logger.warning(
                f"Cross-encoder unavailable ({e}); falling back to fused ranking"
            )
            self._reranker = None
        return self._reranker

    def rerank(self, query: str, hits: list[PassageHit]) -> list[PassageHit]:
        """Reorder hits by cross-encoder relevance, or return them untouched."""
        model = self._get_reranker()
        if model is None or len(hits) < 2:
            return hits
        try:
            scores = model.predict([(query, hit.text) for hit in hits])
        except Exception as e:
            logger.warning(f"Reranking failed, keeping fused order: {e}")
            return hits
        order = np.argsort(np.asarray(scores))[::-1]
        return [hits[int(i)] for i in order]

    # ── Row access ─────────────────────────────────────────────────────────

    def get_chunks(self, chunk_ids: Iterable[int]) -> dict[int, dict]:
        ids = list(chunk_ids)
        if not ids:
            return {}
        rows = self.db.query(
            "SELECT id, book_id, chunk_idx, text, char_start, char_end, page_start, "
            "       page_end, spine_index, anchor_text, section "
            f"FROM chunks WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        )
        return {
            int(r[0]): {
                "chunk_id": int(r[0]), "book_id": r[1], "chunk_idx": int(r[2]),
                "text": r[3], "char_start": r[4], "char_end": r[5],
                "page_start": r[6], "page_end": r[7], "spine_index": r[8],
                "anchor_text": r[9] or "", "section": r[10] or "",
            }
            for r in rows
        }

    def neighbours(self, chunk_id: int, span: int = 1) -> list[dict]:
        """The chunks either side of one, for reading a hit in context."""
        row = self.db.query_one(
            "SELECT book_id, chunk_idx FROM chunks WHERE id = ?", (chunk_id,)
        )
        if not row:
            return []
        rows = self.db.query(
            "SELECT id, book_id, chunk_idx, text, page_start, page_end, spine_index, section "
            "FROM chunks WHERE book_id = ? AND chunk_idx BETWEEN ? AND ? "
            "ORDER BY chunk_idx",
            (row[0], row[1] - span, row[1] + span),
        )
        return [
            {
                "chunk_id": int(r[0]), "book_id": r[1], "chunk_idx": int(r[2]),
                "text": r[3], "page_start": r[4], "page_end": r[5],
                "spine_index": r[6], "section": r[7] or "",
                "is_match": int(r[0]) == chunk_id,
            }
            for r in rows
        ]

    def cosines(self, chunk_ids: list[int], query_vec: np.ndarray) -> dict[int, float]:
        """
        Cosine of each chunk against the query, read straight from the matrix.

        This is what lets a lexical-only hit be held to the same floor as a
        dense one: BM25 proposed it, but whether it is *relevant* is still a
        cosine question, and answering it costs one gather and one dot product.
        """
        if not chunk_ids or query_vec is None or not self.available:
            return {}
        valid = [c for c in chunk_ids if 0 <= c < len(self.matrix)]
        if not valid:
            return {}
        scores = self.matrix[valid] @ query_vec.astype(np.float32)
        return {cid: float(score) for cid, score in zip(valid, scores)}

    def to_hits(
        self,
        fused: list[tuple[int, float, Optional[int], Optional[int]]],
        limit: int,
        cosines: Optional[dict[int, float]] = None,
    ) -> list[PassageHit]:
        ids = [cid for cid, _, _, _ in fused[:limit]]
        rows = self.get_chunks(ids)
        cosines = cosines or {}
        hits: list[PassageHit] = []
        for cid, rrf, d_rank, l_rank in fused[:limit]:
            row = rows.get(cid)
            if not row:
                continue
            hits.append(PassageHit(
                chunk_id=cid, book_id=row["book_id"], chunk_idx=row["chunk_idx"],
                text=row["text"], score=cosines.get(cid, 0.0), rrf=rrf,
                page_start=row["page_start"], page_end=row["page_end"],
                spine_index=row["spine_index"], anchor_text=row["anchor_text"],
                section=row["section"], dense_rank=d_rank, lexical_rank=l_rank,
            ))
        return hits

    # ── The one entry point routes use ─────────────────────────────────────

    def search(
        self,
        text: str,
        query_vec: Optional[np.ndarray],
        limit: int = 10,
        book_id: Optional[str] = None,
        exclude_book: Optional[str] = None,
        allowed_books: Optional[Iterable[str]] = None,
        mode: str = "hybrid",
        rerank: bool = True,
        min_score: float = MIN_PASSAGE_SCORE,
        relative_floor: float = PASSAGE_RELATIVE_FLOOR,
    ) -> list[PassageHit]:
        """
        Passage search. `mode` is `hybrid`, `semantic` or `keyword`.

        **The floor is applied after fusion, not inside the dense search.**
        Applying it only to the dense side let every BM25 hit in unfiltered,
        which is not a subtle leak: "zebra husbandry in antarctica" came back
        with five results, because three rare words each matched *something*
        and RRF happily ranked them. A lexical hit is a proposal, and whether
        it is relevant is still a cosine question.

        `keyword` mode is the exception, and deliberately: §1.9.5 is "every
        mention of X across all 618 books", where an exact term match *is* the
        answer and a semantic floor would suppress the rare-word hits that are
        the entire point.

        `limit` is the number of results; the candidate pool is wider, because
        RRF can only reorder what both systems proposed and a reranker can only
        improve a pool it was given.
        """
        if not self.available:
            return []

        pool = max(limit * 3, PASSAGE_RERANK_CANDIDATES if rerank else limit * 3)
        scope = dict(book_id=book_id, exclude_book=exclude_book, allowed_books=allowed_books)

        dense: list[tuple[int, float]] = []
        if mode in ("hybrid", "semantic") and query_vec is not None:
            dense = self.dense_search(
                query_vec, limit=pool, min_score=min_score,
                relative_floor=relative_floor, **scope,
            )
        lexical: list[tuple[int, float]] = []
        if mode in ("hybrid", "keyword"):
            lexical = self.lexical_search(text, limit=pool, **scope)

        if not dense and not lexical:
            return []

        fused = self.fuse(dense, lexical)

        if mode == "keyword":
            # No semantic floor — but `score` still means cosine, so the BM25
            # value does not go in it. BM25 is unbounded (it reached 11.04 on
            # this index, which the UI dutifully rendered as "1104%"), and
            # putting it in a field documented as a cosine is the same mistake
            # the `rrf` field exists to stop.
            #
            # The cosine is still worth computing and showing here: it is not
            # used to filter anything in this mode, but it tells the reader
            # whether an exact-term hit is also about what they meant.
            cosines = self.cosines([cid for cid, _, _, _ in fused], query_vec)
            hits = self.to_hits(fused, pool if rerank else limit, cosines=cosines)
        else:
            cosines = dict(dense)
            missing = [cid for cid, _, _, _ in fused if cid not in cosines]
            cosines.update(self.cosines(missing, query_vec))
            best = max(cosines.values(), default=0.0)
            cutoff = max(min_score, best * relative_floor)
            fused = [f for f in fused if cosines.get(f[0], 0.0) >= cutoff]
            if not fused:
                return []
            hits = self.to_hits(fused, pool if rerank else limit, cosines=cosines)

        if rerank:
            hits = self.rerank(text, hits)
        return hits[:limit]
