"""
Duplicate detection - finds duplicate books by title similarity, SHA1, and content.

Uses multiple strategies:
1. Exact SHA1 match (identical files)
2. Fuzzy title matching (different editions/formats of same book)
3. ISBN match (same book, different file)
"""
import logging
from collections import defaultdict
from typing import Optional

from .config import DUPLICATE_TITLE_THRESHOLD, DUPLICATE_SHA_CHECK
from .models import BookRecord

logger = logging.getLogger(__name__)


def detect_duplicates(records: list[BookRecord]) -> list[BookRecord]:
    """
    Detect duplicates across all records. 
    Marks duplicates by setting `duplicate_of` to the ID of the canonical copy.
    
    The canonical copy is chosen by:
    1. Prefer text-based over image-based
    2. Prefer more complete metadata
    3. Prefer larger file (likely higher quality)

    Returns the updated list of records.
    """
    if not records:
        return records

    # Group potential duplicates
    duplicate_groups = _find_duplicate_groups(records)

    # For each group, pick canonical and mark others
    for group in duplicate_groups:
        if len(group) < 2:
            continue

        # Sort to find canonical: most metadata > has_text > larger file
        group.sort(key=lambda r: (
            _metadata_completeness(r),
            r.has_text,
            r.size,
        ), reverse=True)

        canonical = group[0]
        for dup in group[1:]:
            if dup.id != canonical.id:
                dup.duplicate_of = canonical.id
                logger.info(
                    f"Duplicate found: '{dup.file_name}' -> canonical: '{canonical.file_name}'"
                )

    return records


def _find_duplicate_groups(records: list[BookRecord]) -> list[list[BookRecord]]:
    """Find groups of potentially duplicate books."""
    try:
        from rapidfuzz import fuzz
        has_rapidfuzz = True
    except ImportError:
        logger.warning("rapidfuzz not installed. Using basic duplicate detection.")
        has_rapidfuzz = False

    groups = []
    assigned = set()  # Track which record IDs are already in a group

    # Phase 1: Exact SHA1 matches
    if DUPLICATE_SHA_CHECK:
        sha_groups = defaultdict(list)
        for r in records:
            if r.id:
                sha_groups[r.id].append(r)
        for sha, group in sha_groups.items():
            if len(group) > 1:
                groups.append(group)
                for r in group:
                    assigned.add(id(r))

    # Phase 2: ISBN matches
    isbn_groups = defaultdict(list)
    for r in records:
        if id(r) in assigned:
            continue
        if r.isbn_13:
            isbn_groups[r.isbn_13].append(r)
        elif r.isbn_10:
            isbn_groups[r.isbn_10].append(r)
    for isbn, group in isbn_groups.items():
        if len(group) > 1:
            groups.append(group)
            for r in group:
                assigned.add(id(r))

    # Phase 3: Fuzzy title matching
    unassigned = [r for r in records if id(r) not in assigned and r.title]

    if has_rapidfuzz and unassigned:
        # Compare all pairs (O(n²) but fine for hundreds of books)
        title_groups = defaultdict(list)
        processed = set()

        for i, r1 in enumerate(unassigned):
            if id(r1) in processed:
                continue

            group = [r1]
            processed.add(id(r1))

            for j in range(i + 1, len(unassigned)):
                r2 = unassigned[j]
                if id(r2) in processed:
                    continue

                # Fuzzy match on cleaned title
                score = fuzz.token_sort_ratio(
                    _normalize_title(r1.title),
                    _normalize_title(r2.title),
                )
                if score >= DUPLICATE_TITLE_THRESHOLD:
                    group.append(r2)
                    processed.add(id(r2))

            if len(group) > 1:
                groups.append(group)
    elif not has_rapidfuzz and unassigned:
        # Basic string comparison fallback
        title_map = defaultdict(list)
        for r in unassigned:
            normalized = _normalize_title(r.title).lower()
            title_map[normalized].append(r)
        for title, group in title_map.items():
            if len(group) > 1:
                groups.append(group)

    logger.info(f"Found {len(groups)} duplicate groups across {len(records)} books")
    return groups


def _normalize_title(title: str) -> str:
    """Normalize a title for comparison."""
    import re
    # Remove common noise words and punctuation
    t = title.lower().strip()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t)
    # Remove edition markers
    t = re.sub(r"\b\d+(?:st|nd|rd|th)\s+edition\b", "", t)
    t = re.sub(r"\bedition\b", "", t)
    return t.strip()


def _metadata_completeness(record: BookRecord) -> int:
    """Score how complete a record's metadata is (higher = more complete)."""
    score = 0
    if record.title:
        score += 2
    if record.authors:
        score += 2
    if record.description:
        score += 3
    if record.isbn_13 or record.isbn_10:
        score += 2
    if record.categories:
        score += 1
    if record.themes:
        score += 1
    if record.cover_path:
        score += 2
    if record.text_excerpt:
        score += 2
    if record.publication_year:
        score += 1
    if record.publisher:
        score += 1
    if record.page_count:
        score += 1
    return score
