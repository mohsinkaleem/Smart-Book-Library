"""
Evidence collection and candidate verification.

This is the module the whole redesign turns on.
§7). Nothing from an external provider is applied because it was *returned*;
it is applied because it *scored* against what we already know locally:

    filename + embedded metadata + title page  →  Evidence
    Evidence                                    →  queries
    provider results                            →  Candidates
    score(Candidate, Evidence)                  →  accept / partial / reject

An ISBN hit is identity and scores 1.0. Otherwise the score is a weighted blend
of title, author and year similarity, renormalised over the dimensions we
actually have evidence for, so a record with no author evidence is not capped
below the acceptance threshold.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from .config import (
    MATCH_ACCEPT_THRESHOLD,
    MATCH_PARTIAL_THRESHOLD,
    MATCH_TITLE_ONLY_ACCEPT,
    MATCH_TITLE_ONLY_PARTIAL,
    MIN_TITLE_EVIDENCE_CHARS,
    MIN_TITLE_EVIDENCE_TOKENS,
)
from .isbn_extractor import all_local_isbns, isbn10_to_isbn13
from .models import BookRecord
from .names import clean_authors
from .text_utils import parse_front_matter

logger = logging.getLogger(__name__)

try:
    from rapidfuzz import fuzz
    _HAS_FUZZ = True
except ImportError:  # pragma: no cover - rapidfuzz is a declared dependency
    _HAS_FUZZ = False

_STOP_TOKENS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "with",
    "edition", "revised", "updated", "vol", "volume", "part",
}

ACCEPT = "accept"
PARTIAL = "partial"
REJECT = "reject"


# ── Candidate ───────────────────────────────────────────────────────────────────

@dataclass
class Candidate:
    """One normalised result from one provider."""
    provider: str = ""
    strategy: str = ""              # isbn | title_author | title
    title: str = ""
    subtitle: str = ""
    authors: list = field(default_factory=list)
    publisher: str = ""
    year: Optional[int] = None
    isbn_10: str = ""
    isbn_13: str = ""
    page_count: Optional[int] = None
    language: str = ""
    description: str = ""
    subjects: list = field(default_factory=list)
    cover_url: str = ""
    work_key: str = ""
    alt_isbns: set = field(default_factory=set)   # other editions' ISBNs: match on, never write
    raw: dict = field(default_factory=dict)

    @property
    def full_title(self) -> str:
        return f"{self.title}: {self.subtitle}".strip(": ") if self.subtitle else self.title

    def isbns(self) -> set[str]:
        return {i for i in (self.isbn_13, self.isbn_10) if i} | set(self.alt_isbns)


# ── Evidence ────────────────────────────────────────────────────────────────────

@dataclass
class TitleClue:
    text: str
    source: str          # filename | file_meta | front_matter


@dataclass
class Evidence:
    isbns: set = field(default_factory=set)
    primary_isbns: list = field(default_factory=list)  # the record's own; queried first
    titles: list = field(default_factory=list)     # list[TitleClue]
    authors: list = field(default_factory=list)
    year: Optional[int] = None
    publishers: list = field(default_factory=list)
    language: str = ""

    # ── queries ──────────────────────────────────────────────────────────────

    def ordered_isbns(self) -> list[str]:
        """
        ISBNs in query order, one per book: the record's own first, then the
        rest sorted. Iterating the bare set made *which* two of several ISBNs
        got looked up depend on the interpreter's hash seed.
        """
        out: list[str] = []
        seen: set[str] = set()
        for isbn in [*self.primary_isbns, *sorted(self.isbns, key=lambda i: (-len(i), i))]:
            canonical = isbn if len(isbn) == 13 else isbn10_to_isbn13(isbn)
            if isbn in self.isbns and canonical not in seen:
                seen.add(canonical)
                out.append(isbn)
        return out

    def best_title(self) -> str:
        """Strongest title clue: title page > embedded metadata > filename."""
        ordered = self._ranked_titles()
        return ordered[0].text if ordered else ""

    def _ranked_titles(self) -> list:
        rank = {"front_matter": 3, "file_meta": 2, "filename": 1}
        return sorted(
            self.titles, key=lambda c: (rank.get(c.source, 0), len(c.text)), reverse=True
        )

    def query_titles(self, limit: int = 2) -> list[str]:
        """
        Title clues worth searching on — at most one per source class.

        Searching only the strongest clue is fragile: a title page that yields
        "Muhammad Asad MECCA" would bury a filename that says "The Road To
        Mecca" outright.
        """
        out: list[str] = []
        seen: set[str] = set()
        used_sources: set[str] = set()
        for clue in self._ranked_titles():
            # One clue per source class: two variants of a mangled title page
            # must not crowd out the embedded metadata title.
            if clue.source in used_sources:
                continue
            text = clue.text
            if self.authors:
                # Paired with an author the main title is specific enough, and a
                # subtitle or "(Early Release)" note makes phrase searches miss.
                main = _main_title(text)
                if _searchable(main):
                    text = main
            key = _normalise(text)
            if not key or key in seen or not _searchable(text):
                continue
            seen.add(key)
            used_sources.add(clue.source)
            out.append(text)
            if len(out) >= limit:
                break
        return out

    def has_isbn(self) -> bool:
        return bool(self.isbns)

    def title_is_searchable(self) -> bool:
        """
        Whether there is enough title evidence to risk a title search at all.

        `Aisha.pdf`, `757.pdf` and `1658134075976.pdf` fail this test — and the
        correct behaviour for them is to stay unenriched rather than to accept
        whatever a search engine returns for a one-word query (§A1).
        """
        return any(_searchable(clue.text) for clue in self.titles)

    def dimensions(self) -> set[str]:
        dims = set()
        if self.titles:
            dims.add("title")
        if self.authors:
            dims.add("author")
        if self.year:
            dims.add("year")
        return dims

    def summary(self) -> dict:
        return {
            "isbns": sorted(self.isbns),
            "titles": [{"text": c.text, "source": c.source} for c in self.titles],
            "authors": list(self.authors),
            "year": self.year,
        }


def collect_evidence(record: BookRecord) -> Evidence:
    """Gather every local signal about what this file actually is."""
    ev = Evidence()
    ev.isbns = all_local_isbns(record)
    ev.primary_isbns = [i for i in (record.isbn_13, record.isbn_10) if i]

    seen: set[str] = set()

    def _add_title(text: str, source: str):
        text = re.sub(r"\s+", " ", (text or "")).strip()
        if not text or len(text) < 3:
            return
        key = _normalise(text)
        if not key or key in seen:
            return
        seen.add(key)
        ev.titles.append(TitleClue(text=text, source=source))

    # Filename-derived title (record.title before enrichment) and embedded meta.
    if record.field_source("title") in ("filename", ""):
        _add_title(record.title, "filename")
    else:
        _add_title(record.title, record.field_source("title") or "file_meta")
    _add_title(record.original_title_meta, "file_meta")

    # The record's authors (embedded metadata, filename) lead: `authors[0]` is
    # the one searched on, and a title-page guess is the least reliable source.
    ev.authors = clean_authors(record.authors)

    front = (
        parse_front_matter(record.front_matter, hint=record.title)
        if record.front_matter else {}
    )
    if front:
        _add_title(front.get("title", ""), "front_matter")
        if front.get("subtitle"):
            _add_title(f"{front.get('title','')} {front['subtitle']}".strip(), "front_matter")
        for author in front.get("authors", []) or []:
            if author not in ev.authors:
                ev.authors.append(author)
        if front.get("publisher"):
            ev.publishers.append(front["publisher"])

    ev.year = record.publication_year
    if record.publisher:
        ev.publishers.append(record.publisher)
    ev.language = record.language
    return ev


# ── Scoring ─────────────────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    tokens = [t for t in text.split() if t not in _STOP_TOKENS]
    return " ".join(tokens)


def _searchable(text: str) -> bool:
    tokens = [t for t in re.findall(r"[^\W\d_]+", text or "", re.UNICODE)
              if t.lower() not in _STOP_TOKENS]
    return len(tokens) >= MIN_TITLE_EVIDENCE_TOKENS and len(text) >= MIN_TITLE_EVIDENCE_CHARS


def _main_title(title: str) -> str:
    """The title without its subtitle or bracketed notes."""
    main = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", " ", title or "")
    return re.split(r"\s*:\s*", main, maxsplit=1)[0].strip()


def _ratio(a: str, b: str) -> float:
    a, b = _normalise(a), _normalise(b)
    if not a or not b:
        return 0.0
    if not _HAS_FUZZ:
        a_tokens, b_tokens = set(a.split()), set(b.split())
        if not a_tokens or not b_tokens:
            return 0.0
        return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
    # token_set rewards subset matches (subtitles), token_sort punishes noise.
    return 0.6 * (fuzz.token_set_ratio(a, b) / 100.0) + 0.4 * (fuzz.token_sort_ratio(a, b) / 100.0)


def title_similarity(candidate: Candidate, evidence: Evidence) -> float:
    scores = [0.0]
    for clue in evidence.titles:
        scores.append(_ratio(candidate.title, clue.text))
        if candidate.subtitle:
            scores.append(_ratio(candidate.full_title, clue.text))
    return max(scores)


def author_similarity(candidate: Candidate, evidence: Evidence) -> float:
    if not candidate.authors or not evidence.authors:
        return 0.0
    scores = [0.0]
    for cand_author in candidate.authors:
        for known in evidence.authors:
            scores.append(_ratio(cand_author, known))
    return max(scores)


def year_similarity(candidate: Candidate, evidence: Evidence) -> float:
    if not candidate.year or not evidence.year:
        return 0.0
    delta = abs(candidate.year - evidence.year)
    if delta == 0:
        return 1.0
    if delta <= 2:
        return 0.6
    return 0.0


def strong_title_clue(evidence: Evidence) -> str:
    """A title-page clue substantial enough to contradict an identifier."""
    for clue in evidence.titles:
        if clue.source != "front_matter":
            continue
        tokens = [t for t in re.findall(r"[^\W\d_]+", clue.text, re.UNICODE)
                  if t.lower() not in _STOP_TOKENS and len(t) > 2]
        if len(tokens) >= 3:
            return clue.text
    return ""


def score_candidate(candidate: Candidate, evidence: Evidence) -> dict:
    """
    Score one candidate against the evidence.

    Returns {score, verdict, reason, parts}. An ISBN match is identity and
    short-circuits to 1.0 — unless the title page says something else
    entirely, which happens when the ISBN printed in the front matter belongs
    to another book advertised there rather than to this one.
    """
    shared_isbns = candidate.isbns() & evidence.isbns
    if shared_isbns:
        clue = strong_title_clue(evidence)
        if clue and _ratio(candidate.full_title, clue) < 0.35:
            return {
                "score": 0.5,
                "verdict": PARTIAL,
                "reason": (
                    f"isbn {sorted(shared_isbns)[0]} matched but the title page reads "
                    f"'{clue[:60]}' — the identifier may belong to another book "
                    "listed in the front matter"
                ),
                "parts": {"isbn": 1.0, "title": round(_ratio(candidate.full_title, clue), 3)},
            }
        return {
            "score": 1.0,
            "verdict": ACCEPT,
            "reason": f"isbn match {sorted(shared_isbns)[0]}",
            "parts": {"isbn": 1.0},
        }

    title = title_similarity(candidate, evidence)
    author = author_similarity(candidate, evidence)
    year = year_similarity(candidate, evidence)

    weights = {"title": 0.6, "author": 0.3, "year": 0.1}
    available = {"title": bool(evidence.titles),
                 "author": bool(evidence.authors and candidate.authors),
                 "year": bool(evidence.year and candidate.year)}
    total_weight = sum(w for k, w in weights.items() if available[k])
    if total_weight <= 0:
        return {
            "score": 0.0,
            "verdict": REJECT,
            "reason": "no comparable evidence",
            "parts": {},
        }

    score = (
        (weights["title"] * title if available["title"] else 0.0)
        + (weights["author"] * author if available["author"] else 0.0)
        + (weights["year"] * year if available["year"] else 0.0)
    ) / total_weight

    # With title evidence alone both bars rise: a partial overlap of common
    # words ("Perspectives on …") must not be enough to claim any relationship.
    title_only = available["title"] and not available["author"] and not available["year"]
    accept_threshold = MATCH_TITLE_ONLY_ACCEPT if title_only else MATCH_ACCEPT_THRESHOLD
    partial_threshold = MATCH_TITLE_ONLY_PARTIAL if title_only else MATCH_PARTIAL_THRESHOLD

    if score >= accept_threshold:
        verdict, reason = ACCEPT, f"title={title:.2f} author={author:.2f} year={year:.2f}"
    elif score >= partial_threshold:
        verdict, reason = PARTIAL, f"borderline: title={title:.2f} author={author:.2f} year={year:.2f}"
    else:
        verdict, reason = REJECT, f"below gate: title={title:.2f} author={author:.2f} year={year:.2f}"

    return {
        "score": round(score, 3),
        "verdict": verdict,
        "reason": reason,
        "parts": {"title": round(title, 3), "author": round(author, 3), "year": round(year, 3)},
    }


def best_candidate(candidates: list[Candidate], evidence: Evidence) -> tuple[Optional[Candidate], dict, list[dict]]:
    """
    Score every candidate from every provider and return the best one.

    Returns (candidate, verdict_dict, rejections). Providers are never
    short-circuited: a weak first answer from OpenLibrary must not prevent a
    strong answer from Google Books being considered.
    """
    scored: list[tuple[Candidate, dict]] = []
    for cand in candidates:
        result = score_candidate(cand, evidence)
        scored.append((cand, result))

    if not scored:
        return None, {"score": 0.0, "verdict": REJECT, "reason": "no candidates"}, []

    # Equal scores are common (every ISBN hit is 1.0 — including one for a
    # book advertised in the front matter), so the title breaks the tie.
    scored.sort(
        key=lambda pair: (pair[1]["score"], title_similarity(pair[0], evidence)),
        reverse=True,
    )
    best, verdict = scored[0]
    rejections = [
        {
            "provider": cand.provider,
            "strategy": cand.strategy,
            "title": cand.full_title[:120],
            "authors": cand.authors[:3],
            "score": res["score"],
            "reason": res["reason"],
        }
        for cand, res in scored
        if res["verdict"] == REJECT
    ][:5]

    if verdict["verdict"] == REJECT:
        return None, verdict, rejections
    return best, verdict, rejections
