"""
Local content analysis: categories, themes, keywords, fallback summary.

Two defects are fixed here:

* scoring summed **raw occurrence counts** over corpora whose length varies by
  two orders of magnitude, so a long excerpt that merely mentions "statistics"
  outranked a short one that is actually about it — and a file with an empty
  title and no metadata was still confidently assigned two categories. Matches
  are now density-normalised, title/subject matches weigh far more than body
  text, and a minimum score is required before any category is assigned;
* keywords were collected by iterating a `set`, so the same input produced a
  different 15 keywords on every run and FTS results changed between builds.
  Iteration is now over a sorted list, ranked before truncation.
"""
import logging
import re
from collections import Counter

from .models import BookRecord
from .taxonomy import (
    CATEGORY_KEYWORDS,
    THEME_PATTERNS,
    categories_from_subjects,
    clean_subjects,
    constrain_categories,
)
from .text_utils import is_mostly_boilerplate

logger = logging.getLogger(__name__)

MIN_CATEGORY_SCORE = 3.0
MIN_THEME_SCORE = 2.0
MIN_BODY_ONLY_KEYWORDS = 3   # distinct keywords required when body text is all we have
MAX_CATEGORIES = 4
MAX_THEMES = 5
MAX_KEYWORDS = 15

# Weight per evidence field. Short, high-signal fields dominate body text.
_FIELD_WEIGHTS = {
    "title": 6.0,
    "subtitle": 4.0,
    "subjects": 4.0,
    "description": 2.5,
    "publisher": 0.5,
}
_BODY_WEIGHT = 3.0
_BODY_NORMALISER = 2000      # characters per "page" of density
_MAX_BODY_HITS = 5           # cap so one repeated word cannot dominate

_LATIN_SCRIPTS = {"", "latin"}


def _specificity(keyword: str) -> float:
    """Multi-word keywords are far more discriminating than single words."""
    return 1.0 + 0.75 * (len(keyword.split()) - 1)


def _count(keyword: str, text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\b" + re.escape(keyword) + r"\b", text))


def _fields(record: BookRecord) -> dict[str, str]:
    return {
        "title": (record.title or "").lower(),
        "subtitle": (record.subtitle or "").lower(),
        "subjects": " ".join(record.subjects_raw or []).lower(),
        "description": (record.description or "").lower(),
        "publisher": (record.publisher or "").lower(),
    }


def _body(record: BookRecord) -> str:
    body = record.content_sample or record.text_excerpt or ""
    return body.lower()


def _score_group(record: BookRecord, groups: dict[str, list[str]]) -> dict[str, dict]:
    """
    Score each label. Returns {label: {score, field_hits, distinct}}.

    `field_hits` and `distinct` are what stop a body-only coincidence from
    becoming a category: one repeated word in the text is not a subject.
    """
    fields = _fields(record)
    body = _body(record)
    body_pages = max(len(body) / _BODY_NORMALISER, 1.0)

    scores: dict[str, dict] = {}
    for label, keywords in groups.items():
        score = 0.0
        field_hits = 0
        distinct = 0
        for keyword in keywords:
            specificity = _specificity(keyword)
            matched = False
            for field_name, text in fields.items():
                if text and _count(keyword, text):
                    score += _FIELD_WEIGHTS[field_name] * specificity
                    field_hits += 1
                    matched = True
            hits = min(_count(keyword, body), _MAX_BODY_HITS)
            if hits:
                score += _BODY_WEIGHT * specificity * hits / body_pages
                matched = True
            if matched:
                distinct += 1
        if score > 0:
            scores[label] = {
                "score": round(score, 3),
                "field_hits": field_hits,
                "distinct": distinct,
            }
    return scores


def detect_categories(record: BookRecord) -> list[str]:
    """Canonical categories, or an empty list when the evidence is too thin."""
    scores = _score_group(record, CATEGORY_KEYWORDS)

    # An external subject that maps into the vocabulary is strong evidence.
    for canonical in categories_from_subjects(record.subjects_raw):
        entry = scores.setdefault(canonical, {"score": 0.0, "field_hits": 0, "distinct": 0})
        entry["score"] += 5.0
        entry["field_hits"] += 1

    qualified = []
    for label, entry in scores.items():
        if entry["score"] < MIN_CATEGORY_SCORE:
            continue
        # Body text alone must show several distinct concepts, not one word
        # repeated — that is how a file with no metadata at all was confidently
        # assigned both "Computer Science" and "Islam & Islamic Studies".
        if entry["field_hits"] == 0 and entry["distinct"] < MIN_BODY_ONLY_KEYWORDS:
            continue
        qualified.append((label, entry["score"]))

    qualified.sort(key=lambda kv: (-kv[1], kv[0]))
    return [label for label, _ in qualified[:MAX_CATEGORIES]]


def detect_themes(record: BookRecord) -> list[str]:
    scores = _score_group(record, THEME_PATTERNS)
    qualified = [
        (label, entry["score"])
        for label, entry in scores.items()
        if entry["score"] >= MIN_THEME_SCORE
        and (entry["field_hits"] > 0 or entry["distinct"] >= MIN_BODY_ONLY_KEYWORDS)
    ]
    qualified.sort(key=lambda kv: (-kv[1], kv[0]))
    return [label for label, _ in qualified[:MAX_THEMES]]


def extract_keywords(record: BookRecord) -> list[str]:
    """Deterministic keyword extraction — same input, same output, every run."""
    if (record.script or "latin") not in _LATIN_SCRIPTS:
        return []          # English keyword matching on Arabic text is noise (§M5)

    corpus = " ".join([
        (record.title or ""),
        (record.subtitle or ""),
        (record.description or ""),
        " ".join(record.subjects_raw or []),
        record.content_sample or record.text_excerpt or "",
    ])
    corpus_lower = corpus.lower()

    vocabulary = sorted({kw for kws in CATEGORY_KEYWORDS.values() for kw in kws})
    scored: list[tuple[float, str]] = []
    for keyword in vocabulary:
        hits = _count(keyword, corpus_lower)
        if hits:
            scored.append((hits * _specificity(keyword), keyword))

    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    keywords = [kw for _, kw in scored[:MAX_KEYWORDS]]

    if len(keywords) < MAX_KEYWORDS:
        proper = re.findall(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+\b", corpus[:4000])
        counts = Counter(proper)
        extra = sorted(
            ((c, term) for term, c in counts.items() if c > 1),
            key=lambda pair: (-pair[0], pair[1]),
        )
        existing = {kw.lower() for kw in keywords}
        for _, term in extra:
            if term.lower() not in existing:
                keywords.append(term)
                existing.add(term.lower())
            if len(keywords) >= MAX_KEYWORDS:
                break

    return keywords[:MAX_KEYWORDS]


def generate_simple_summary(record: BookRecord) -> str:
    """Fallback summary — from prose, never from the copyright page (§A8)."""
    if record.description:
        sentences = re.split(r"(?<=[.!?])\s+", record.description.strip())
        return " ".join(sentences[:3])[:500]

    body = record.content_sample or ""
    if not body or is_mostly_boilerplate(body):
        return ""
    for paragraph in body.split("\n\n"):
        paragraph = paragraph.strip()
        if len(paragraph) > 120 and not is_mostly_boilerplate(paragraph):
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            return " ".join(sentences[:3])[:500]
    return ""


def analyze_themes(record: BookRecord) -> BookRecord:
    """Populate categories, themes, keywords and a fallback summary."""
    record.subjects_raw = clean_subjects(record.subjects_raw)

    categories = detect_categories(record)
    if categories:
        record.set_field("categories", constrain_categories(categories), "analyzer", 0.5)
    elif record.categories:
        # Anything left over from an older run must still obey the vocabulary.
        record.categories = constrain_categories(record.categories)

    themes = detect_themes(record)
    if themes:
        record.set_field("themes", themes, "analyzer", 0.5)

    keywords = extract_keywords(record)
    if keywords:
        record.set_field("keywords", keywords, "analyzer", 0.5)

    if not record.summary:
        summary = generate_simple_summary(record)
        if summary:
            record.set_field("summary", summary, "analyzer", 0.4)

    return record
