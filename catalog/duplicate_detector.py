"""
Duplicate detection.

Three defects made this dead code:

* Phase 1 grouped by `r.id`, which *was* the SHA1, so inside every group
  `dup.id == canonical.id` and the marking branch could never execute;
* records were keyed by id in the store, so two byte-identical files silently
  overwrote each other and the collision became invisible;
* ISBN grouping was ungated, so the false ISBNs written by unverified API
  matches would have merged unrelated books.

Now: identity is `file_path`, `content_sha1` is an attribute, and ISBN grouping
requires a confident, verified ISBN.
"""
import logging
import re
from collections import defaultdict

from .config import DUPLICATE_MIN_ISBN_CONFIDENCE, DUPLICATE_TITLE_THRESHOLD
from .models import BookRecord

logger = logging.getLogger(__name__)


def detect_duplicates(records: list[BookRecord]) -> list[BookRecord]:
    """
    Mark duplicates by setting `duplicate_of` to the canonical record's id.

    Canonical choice: most complete metadata, then text-based over image-only,
    then larger file.
    """
    if not records:
        return records

    # A fresh pass must be able to *clear* stale marks.
    for record in records:
        record.duplicate_of = None

    groups = _find_duplicate_groups(records)
    for group in groups:
        if len(group) < 2:
            continue
        group.sort(
            key=lambda r: (_metadata_completeness(r), r.has_text, r.size), reverse=True
        )
        canonical = group[0]
        for dup in group[1:]:
            if dup.file_path == canonical.file_path:
                continue
            dup.duplicate_of = canonical.id
            logger.info(
                f"Duplicate: '{dup.file_name}' → canonical '{canonical.file_name}'"
            )
    return records


def _trusted_isbn(record: BookRecord) -> str:
    """An ISBN is only identity-grade if it was verified and is confident."""
    for field in ("isbn_13", "isbn_10"):
        value = getattr(record, field, "")
        if not value:
            continue
        source = record.field_source(field)
        confidence = record.field_confidence(field)
        if source in ("user", "isbn_match", "file_meta", "filename", "front_matter"):
            return value
        if source == "api_verified" and confidence >= DUPLICATE_MIN_ISBN_CONFIDENCE:
            return value
    return ""


def _find_duplicate_groups(records: list[BookRecord]) -> list[list[BookRecord]]:
    try:
        from rapidfuzz import fuzz
        has_rapidfuzz = True
    except ImportError:
        logger.warning("rapidfuzz not installed. Using exact title matching.")
        has_rapidfuzz = False

    groups: list[list[BookRecord]] = []
    assigned: set[str] = set()

    # Phase 1 — byte-identical files (same content hash, different paths).
    sha_groups: dict[str, list[BookRecord]] = defaultdict(list)
    for r in records:
        if r.content_sha1:
            sha_groups[r.content_sha1].append(r)
    for group in sha_groups.values():
        if len({r.file_path for r in group}) > 1:
            groups.append(group)
            assigned.update(r.file_path for r in group)

    # Phase 2 — same trusted ISBN.
    isbn_groups: dict[str, list[BookRecord]] = defaultdict(list)
    for r in records:
        if r.file_path in assigned:
            continue
        isbn = _trusted_isbn(r)
        if isbn:
            isbn_groups[isbn].append(r)
    for group in isbn_groups.values():
        if len(group) > 1:
            groups.append(group)
            assigned.update(r.file_path for r in group)

    # Phase 3 — fuzzy title, corroborated by author, year or page count.
    # Blocked on shared title tokens: comparing every pair is quadratic, and
    # two titles scoring >= 90 on token_sort_ratio always share a long token.
    unassigned = [r for r in records if r.file_path not in assigned and r.title]
    blocks: dict[str, list[BookRecord]] = defaultdict(list)
    for r in unassigned:
        for key in _blocking_keys(r.title):
            blocks[key].append(r)

    processed: set[str] = set()
    for block in blocks.values():
        for i, r1 in enumerate(block):
            if r1.file_path in processed:
                continue
            group = [r1]
            processed.add(r1.file_path)
            for r2 in block[i + 1:]:
                if r2.file_path in processed:
                    continue
                if has_rapidfuzz:
                    score = fuzz.token_sort_ratio(
                        _normalize_title(r1.title), _normalize_title(r2.title)
                    )
                else:
                    score = 100 if _normalize_title(r1.title) == _normalize_title(r2.title) else 0
                if score >= DUPLICATE_TITLE_THRESHOLD and _corroborated(r1, r2):
                    group.append(r2)
                    processed.add(r2.file_path)
            if len(group) > 1:
                groups.append(group)

    logger.info(f"Found {len(groups)} duplicate groups across {len(records)} books")
    return groups


def _blocking_keys(title: str) -> set[str]:
    """
    Candidate keys a near-duplicate title is guaranteed to share.

    The three longest tokens plus the first token: a pair only needs one key in
    common to be compared, and dropping below 90% similarity while sharing none
    of them is not reachable for real titles.
    """
    tokens = [t for t in _normalize_title(title).split() if len(t) > 3]
    if not tokens:
        return {_normalize_title(title)[:12]}
    keys = set(sorted(tokens, key=len, reverse=True)[:3])
    keys.add(tokens[0])
    return keys


def _corroborated(a: BookRecord, b: BookRecord) -> bool:
    """A matching title alone is not enough to merge two books."""
    if a.authors and b.authors:
        first_a = re.sub(r"[^a-z]", "", a.authors[0].lower())
        first_b = re.sub(r"[^a-z]", "", b.authors[0].lower())
        if first_a and first_b and (first_a in first_b or first_b in first_a):
            return True
    if a.publication_year and b.publication_year:
        if abs(a.publication_year - b.publication_year) <= 1:
            return True
    if a.page_count and b.page_count:
        larger = max(a.page_count, b.page_count)
        if larger and abs(a.page_count - b.page_count) / larger <= 0.05:
            return True
    # Same title and neither carries corroborating metadata at all.
    return not (a.authors or b.authors or a.publication_year or b.publication_year)


def _normalize_title(title: str) -> str:
    t = (title or "").lower().strip()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\b\d+(?:st|nd|rd|th)\s+edition\b", " ", t)
    t = re.sub(r"\bedition\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _metadata_completeness(record: BookRecord) -> int:
    score = 0
    score += 2 if record.title else 0
    score += 2 if record.authors else 0
    score += 3 if record.description else 0
    score += 2 if (record.isbn_13 or record.isbn_10) else 0
    score += 1 if record.categories else 0
    score += 1 if record.themes else 0
    score += 2 if record.cover_path else 0
    score += 2 if record.text_excerpt else 0
    score += 1 if record.publication_year else 0
    score += 1 if record.publisher else 0
    score += 1 if record.page_count else 0
    score += 3 if record.field_source("title") in ("user", "isbn_match", "api_verified") else 0
    return score
