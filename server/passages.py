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

**Relevance is not the last word on ordering.** Ranking by score alone gives
one book the whole page and shows the same paragraph three times, because
consecutive chunks overlap by `CHUNK_OVERLAP_CHARS` and a book that discusses
a topic discusses it in several adjacent chunks. `PassageIndex.diversify` is
the stage after fusion and reranking: it demotes a chunk adjacent to one
already kept, the fourth hit from one book, and apparatus (`is_apparatus` —
bibliographies retrieve well and answer nothing). It demotes rather than
drops, so the page keeps its length and changes its order.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from catalog.chunking import make_anchor_text
from catalog.config import (
    PASSAGE_MAX_PER_BOOK,
    PASSAGE_NEIGHBOUR_GAP,
    PASSAGE_RERANK,
    PASSAGE_RERANK_CANDIDATES,
    PASSAGE_RERANK_MODEL,
    RRF_K,
)
from catalog.full_text import read_span
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
#
# **Re-measured 2026-10-17, at 251,110 chunks over 557 books.** The index has
# grown 10.5x since the calibration above, and a floor is a property of the
# score distribution, so it had to be re-run: same protocol, 12 real queries
# against 10 nonsense ones.
#
#     real queries    top score 0.723 - 0.857
#     nonsense        top score 0.608 - 0.724
#
# **The measured gap has closed to nothing.** At 23,920 chunks the two bands
# were 0.05 apart; at 251,110 they touch at ~0.72, because a larger index
# means more chances that *something* in it resembles any input at all. No
# absolute floor can reject every nonsense query any more, so the floor's job
# is now the cheap half of them:
#
#     0.66 (was)   5 of 10 nonsense queries still returned something
#     0.68 (now)   3 of 10, and not one real query lost a single hit
#     0.74         0 of 10, but 2 real queries returned nothing at all
#
# 0.68 is where nonsense halves for free. Above 0.71 it starts costing the
# abstract humanities queries this library is mostly for — "how does the
# author define modernity" tops out at 0.723 — so the floor stops here and
# `is_apparatus` and `PassageIndex.diversify` pick up the rest of the work.
MIN_PASSAGE_SCORE = 0.68
PASSAGE_RELATIVE_FLOOR = 0.80

# Passage-to-passage comparison is a third distribution. The query is a real
# 1,500-character passage rather than a short phrase, so everything scores
# higher: measured over six passages drawn from the index, the second-best
# match (the first that is not the passage itself) scores 0.867-0.923 and the
# 200th scores 0.689-0.716. A floor calibrated for short queries would return
# most of the book, so this one is separate and higher.
#
# Re-measured 2026-10-17 over 8 passages drawn at random from the 251,110-chunk
# index: second-best 0.795-0.931, 200th 0.715-0.769, and 50-518 chunks above
# 0.75 per passage. This band barely moved as the index grew — unlike the
# short-query one above — so the number is unchanged.
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


# Function words, kept out of the OR'd half of a hybrid query.
#
# They are not *wrong* — BM25 discounts a term that appears everywhere — but
# they are expensive in the only currency this query has: `max_terms` is 24,
# and "what does the author say about the collapse of the abbasid caliphate"
# spends nine of them on words that match all 251,110 chunks. Measured on this
# index, dropping them is what let `abbasid` and `caliphate` into a query that
# had been truncated before it reached them.
#
# Words of two characters or fewer are already dropped, so this list only
# needs the longer ones. Anything with a subject-matter sense in this library
# is deliberately absent: `being` and `will` are philosophy, `state` and
# `order` are politics, `may` is a month and a jurisprudential term.
STOPWORDS = frozenset("""
the and for are but not you all any can had her was one our out has him his
how its now see two who did get say she use that this with have from they
will what when your said them then than were into more some such only over
also very does where which their there these those would could should about
after again because been before both each just like make many most much must
other same than them they this those through under upon while whose why yes
""".split())

_PHRASE = re.compile(r'"([^"]{2,})"')


def split_phrases(text: str) -> tuple[list[str], str]:
    """
    Quoted spans, and whatever was left outside them.

    A reader who types quotes is asking for those words in that order. The
    sanitiser used to delete the quotes before anything looked at them, so
    `"the right of the wayfarer"` became eight OR'd words, four of them
    function words, and the phrase itself ranked no higher than a chunk that
    happened to mention a wayfarer.
    """
    text = text or ""
    phrases = [" ".join(m.group(1).split()) for m in _PHRASE.finditer(text)]
    rest = _PHRASE.sub(" ", text)
    return [p for p in phrases if p], rest


def _contains_phrases(haystack: str, phrases: Iterable[str]) -> bool:
    """Every phrase present, ignoring case and how the line wrapped."""
    flat = " ".join((haystack or "").lower().split())
    return all(" ".join(p.lower().split()) in flat for p in phrases)


def fts_query(text: str, max_terms: int = 24) -> str:
    """
    A safe fts5 query from arbitrary user text.

    Loose terms are OR'd rather than AND'd: this is the lexical half of a
    hybrid search, and its job is recall on exact terminology and proper
    nouns. RRF handles precision by only rewarding terms that also rank well
    densely.

    A quoted phrase is the exception. It is an instruction, not a hint, so it
    is AND'd: `"wayfarer" AND (zakat OR traveller)` asks for the phrase and
    lets the loose terms order what is left. `search` enforces the same thing
    on the dense side, which cannot read quotes at all.
    """
    phrases, rest = split_phrases(text)

    cleaned = _FTS_UNSAFE.sub(" ", rest)
    words = [t for t in cleaned.split() if len(t) > 2]
    terms = [t for t in words if t.lower() not in STOPWORDS]
    # A query that is *all* function words still has to search for something:
    # "what is the good life" is a real question about the good life.
    if not terms and not phrases:
        terms = words
    terms = terms[:max_terms]

    parts = [f'"{_FTS_UNSAFE.sub(" ", p).strip()}"' for p in phrases]
    parts = [p for p in parts if p != '""']
    loose = " OR ".join(f'"{t}"' for t in terms)
    if loose:
        parts.append(f"({loose})" if parts else loose)
    return " AND ".join(parts)


# ── Apparatus, not argument ─────────────────────────────────────────────────
#
# A bibliography retrieves beautifully and answers nothing.
#
# The §1.9.4 thread code met this first: its first run over a conference
# proceedings returned four "recurring concepts" at strength 0.935, and every
# one was a reference list — each paper ends in one, and reference lists
# resemble each other more than any two arguments do. Search had the same leak
# and nobody had looked: measured 2026-10-17 over ten queries on the 251k
# index, 4 of 200 dense top-20 hits were reference lists, endnote runs or
# tables of contents, including an ISBN block that outranked real prose on the
# query's own subject.
#
# Every signal here is a *pair*: the vocabulary or number density of an
# apparatus **and** less prose than an argument would have. One signal alone
# does not survive this library. Tried and rejected, against 500 random
# chunks:
#
#   digit density alone        flagged latency tables, equations, option
#                              prices — a CS and finance shelf is full of
#                              legitimate numbers
#   3 citation markers         flagged any footnoted page: `vol.`, `p.` and
#                              `no.` reach three in one page of real argument
#                              about Islamic law (this was the thread code's
#                              rule, and it was demoting prose)
#   few long "sentences"       flagged code listings and verse
#   `\.\s?\.\s?\.`              flagged ellipses in quoted dialogue, so a dot
#                              leader has to be five dots, not three
#
# What is left runs at 6 flags in 500 random chunks, 5 of them genuine.
# Densities are per 1,000 characters so a long chunk is not condemned for
# being long.
_REFERENCE_MARKERS = re.compile(
    r"\b(?:pp?\.|vol\.|no\.|ed(?:s)?\.|ibid|op\.\s*cit|doi:|isbn|"
    r"retrieved\s+from|available\s+at|proceedings\s+of|j\.\s|int\.\s)",
    re.IGNORECASE,
)
# `[97]`-style numbered references.
_NUMBERED_CITATION = re.compile(r"\[\d{1,4}\]")
# A dot leader in a table of contents or an index. Five dots, because three is
# an ellipsis and this library has novels in it.
_DOT_LEADER = re.compile(r"(?:\.\s?){5,}")

MAX_DIGIT_RATIO = 0.08
# Below this many 60-character-plus segments per 1,000 characters, a passage
# is not making an argument. Measured over 500 random chunks: the median is
# 6.2 and the 5th percentile is 3.3.
MIN_PROSE_DENSITY = 2.0
# Too short to judge. A 250-character search hit can be real prose with no
# room for three sentences; the apparatus this catches comes in slabs.
MIN_JUDGEABLE_CHARS = 600


def is_apparatus(text: str) -> bool:
    """
    Whether a passage is a book's apparatus rather than its argument.

    Reference lists, endnote runs, index tails, tables of contents. Used to
    demote search results (`PassageIndex.diversify`) and to reject concept
    threads (`_is_conceptual`), which adds its own length rule on top.
    """
    body = (text or "").strip()
    if len(body) < MIN_JUDGEABLE_CHARS:
        return False

    per_1k = len(body) / 1000
    digits = sum(1 for c in body if c.isdigit()) / len(body)
    citations = len(_REFERENCE_MARKERS.findall(body)) / per_1k
    numbered = len(_NUMBERED_CITATION.findall(body)) / per_1k
    leaders = len(_DOT_LEADER.findall(body)) / per_1k
    prose = sum(1 for part in body.split(".") if len(part.strip()) > 60) / per_1k

    # A dot leader is a table of contents or an index and nothing else.
    if leaders >= 1.0:
        return True
    # A numbered bibliography: `[97] Author: "Title," venue, year.`
    if numbered >= 3.0 and citations >= 1.5:
        return True
    # Citation vocabulary or number runs, with no prose around them.
    if prose < MIN_PROSE_DENSITY and (citations >= 1.5 or digits > MAX_DIGIT_RATIO):
        return True
    # Dense citations with thin prose: an author-date bibliography, whose
    # entries are long enough to pass for sentences.
    if citations >= 2.5 and prose < MIN_PROSE_DENSITY * 2:
        return True
    return False


# Two copies of one book produce byte-identical chunks, so a prefix is enough
# to recognise them, and a prefix is all that can be compared cheaply: the
# whole text of 30 candidates against each other is quadratic in the length of
# a passage, for a case where the first line already settles it.
_FINGERPRINT_CHARS = 300


def _text_fingerprint(text: str) -> str:
    """A normalised prefix, for spotting the same passage under two book ids."""
    return " ".join((text or "").split())[:_FINGERPRINT_CHARS].lower()


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
        exclude_books: Optional[Iterable[str]] = None,
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
            # Copies of a book the library already shows under another id.
            # Without this the same paragraph came back twice from what the
            # reader sees as one book — see `BookDatabase.duplicate_book_ids`.
            for dupe_id in exclude_books or ():
                span = self.book_ranges.get(dupe_id)
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
        exclude_books: Optional[Iterable[str]] = None,
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
        excluded = list(exclude_books or ())
        if excluded:
            sql.append(f"AND c.book_id NOT IN ({','.join('?' * len(excluded))})")
            params.extend(excluded)
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

    # ── Diversity ──────────────────────────────────────────────────────────

    @staticmethod
    def diversify(
        hits: list["PassageHit"],
        limit: int,
        max_per_book: int = PASSAGE_MAX_PER_BOOK,
        neighbour_gap: int = PASSAGE_NEIGHBOUR_GAP,
        demote_apparatus: bool = True,
    ) -> list["PassageHit"]:
        """
        Reorder a ranked page so it is not three views of the same paragraph.

        Relevance ranking alone concentrates: measured on the 251k index,
        "quantum tunnelling" took 8 of the dense top 20 from one book, 5 of
        them consecutive chunks — and consecutive chunks share
        `CHUNK_OVERLAP_CHARS` of text, so the reader is being shown the same
        prose two or three times while nine other books that discuss it sit
        below the fold.

        Four demotions, in one pass down the ranking: a chunk within
        `neighbour_gap` of one already kept from the same book, text already
        shown from a *different* book, the `max_per_book + 1`-th hit from a
        book, and apparatus rather than argument. Demoted, not dropped — they
        go behind everything that is none of those things. The candidate pool
        is three times the page, so in practice this changes the order of the
        page and not its length, and when the pool is thin the demoted hits
        come back rather than leaving the reader short.

        The cross-book text check is not redundant with `exclude_books`. That
        drops the copies the catalog has *linked* (`books.duplicate_of`), and
        the measurement that prompted this found three unlinked ones: "the
        migratory patterns of ceiling fans" returned the same paragraph of
        Henrich at 0.691 three times, from `The WEIRDest People in the World`,
        `The Weirdest People in the World` and `Henrich the Weirdest People in
        the World`, of which only the third is registered as a duplicate.
        Retrieval cannot wait for the duplicates page to catch up.

        `max_per_book` is 0 for an in-book search, where every hit is from one
        book by definition and a cap would just truncate the page.
        """
        keep: list[PassageHit] = []
        deferred: list[PassageHit] = []
        kept_per_book: dict[str, int] = {}
        kept_idx: dict[str, list[int]] = {}
        kept_text: set[str] = set()

        for hit in hits:
            seen = kept_idx.setdefault(hit.book_id, [])
            overlapping = any(abs(hit.chunk_idx - idx) <= neighbour_gap for idx in seen)
            crowded = max_per_book > 0 and kept_per_book.get(hit.book_id, 0) >= max_per_book
            fingerprint = _text_fingerprint(hit.text)
            if (
                overlapping
                or crowded
                or (fingerprint and fingerprint in kept_text)
                or (demote_apparatus and is_apparatus(hit.text))
            ):
                deferred.append(hit)
                continue
            keep.append(hit)
            kept_per_book[hit.book_id] = kept_per_book.get(hit.book_id, 0) + 1
            seen.append(hit.chunk_idx)
            if fingerprint:
                kept_text.add(fingerprint)

        ordered = keep + deferred
        return ordered[:limit] if limit else ordered

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

    def _hydrate(self, rows: Iterable) -> list[dict]:
        """
        Turn chunk rows into dicts, reading each passage's words off disk.

        A chunk row stores the span it occupies in `data/text/{book_id}.txt`,
        not the text itself — the database used to hold a second copy of
        every passage. `read_span` memoises whole books, so a page of hits
        from one book costs one file read, and `anchor_text` is derived here
        rather than stored a third time.
        """
        out: list[dict] = []
        for r in rows:
            text = read_span(r["book_id"], r["char_start"], r["char_end"],
                             Path(r["file_path"]) if r["file_path"] else None,
                             r["file_type"] or "")
            out.append({
                "chunk_id": int(r["id"]), "book_id": r["book_id"],
                "chunk_idx": int(r["chunk_idx"]), "text": text,
                "char_start": r["char_start"], "char_end": r["char_end"],
                "page_start": r["page_start"], "page_end": r["page_end"],
                "spine_index": r["spine_index"],
                "anchor_text": make_anchor_text(text),
                "section": r["section"] or "",
            })
        return out

    _CHUNK_SELECT = """
        SELECT c.id, c.book_id, c.chunk_idx, c.char_start, c.char_end,
               c.page_start, c.page_end, c.spine_index, c.section,
               b.file_path, b.file_type
        FROM chunks c LEFT JOIN books b ON b.id = c.book_id
    """

    def get_chunks(self, chunk_ids: Iterable[int]) -> dict[int, dict]:
        ids = list(chunk_ids)
        if not ids:
            return {}
        rows = self.db.query(
            f"{self._CHUNK_SELECT} WHERE c.id IN ({','.join('?' * len(ids))})", ids
        )
        return {row["chunk_id"]: row for row in self._hydrate(rows)}

    def neighbours(self, chunk_id: int, span: int = 1) -> list[dict]:
        """The chunks either side of one, for reading a hit in context."""
        row = self.db.query_one(
            "SELECT book_id, chunk_idx FROM chunks WHERE id = ?", (chunk_id,)
        )
        if not row:
            return []
        rows = self.db.query(
            f"{self._CHUNK_SELECT} WHERE c.book_id = ? "
            "AND c.chunk_idx BETWEEN ? AND ? ORDER BY c.chunk_idx",
            (row[0], row[1] - span, row[1] + span),
        )
        hydrated = self._hydrate(rows)
        for item in hydrated:
            item["is_match"] = item["chunk_id"] == chunk_id
        return hydrated

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
        exclude_books: Optional[Iterable[str]] = None,
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

        # The pool only needs to be reranker-sized when a reranker will
        # actually run. `rerank=True` with `PASSAGE_RERANK` off used to hydrate
        # 50 passages — 50 span reads — and then reorder none of them.
        will_rerank = rerank and PASSAGE_RERANK
        pool = max(limit * 3, PASSAGE_RERANK_CANDIDATES if will_rerank else 0)
        scope = dict(
            book_id=book_id, exclude_book=exclude_book,
            allowed_books=allowed_books, exclude_books=exclude_books,
        )

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
            hits = self.to_hits(fused, pool, cosines=cosines)
        else:
            cosines = dict(dense)
            missing = [cid for cid, _, _, _ in fused if cid not in cosines]
            cosines.update(self.cosines(missing, query_vec))
            best = max(cosines.values(), default=0.0)
            cutoff = max(min_score, best * relative_floor)
            fused = [f for f in fused if cosines.get(f[0], 0.0) >= cutoff]
            if not fused:
                return []
            hits = self.to_hits(fused, pool, cosines=cosines)

        # A quoted phrase binds the dense half too. It cannot read quotes —
        # an embedding of `"the right of the wayfarer"` is an embedding of the
        # words — so a chunk that is *about* wayfarers would otherwise be fused
        # in alongside the ones that actually contain the phrase, and the quote
        # would mean nothing except in `keyword` mode.
        required, _ = split_phrases(text)
        if required:
            hits = [h for h in hits if _contains_phrases(h.text, required)]
            if not hits:
                return []

        if will_rerank:
            hits = self.rerank(text, hits)
        # Apparatus is left alone in `keyword` mode: §1.9.5 is "every mention
        # of X", and a reader hunting a citation across 618 books is one of
        # the people a bibliography is the right answer for.
        return self.diversify(
            hits, limit,
            max_per_book=0 if book_id else PASSAGE_MAX_PER_BOOK,
            demote_apparatus=mode != "keyword",
        )
