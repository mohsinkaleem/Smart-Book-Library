"""
API enrichment: evidence → candidates → verification → provenance-aware merge.

The old flow took `docs[0]` / `items[0]` and applied it unconditionally, so a
bad query was *guaranteed* to produce a confidently wrong record, and the wrong
ISBN it wrote then "confirmed" the wrong book on the next run
(see the verification gate in `evidence.py`).

Now:

* both providers are always consulted — no short-circuit on the first one that
  answers — and every result is scored against local evidence;
* ≥0.75 (or ≥0.85 when the title is our only evidence) applies everything;
  0.45–0.75 applies descriptive fields only and flags the record for review;
  below that, nothing is applied and the rejection is recorded;
* an identifier is written only when it was *verified*, never merely returned.
"""
import logging
from pathlib import Path
from typing import Callable, Optional

import requests

from .config import API_REQUEST_TIMEOUT, COVERS_DIR
from .evidence import (
    ACCEPT,
    PARTIAL,
    REJECT,
    Candidate,
    Evidence,
    _ratio,
    best_candidate,
    collect_evidence,
)
from .languages import UNKNOWN, normalise_language
from .models import BookRecord
from .names import clean_authors
from .providers import (
    failed_lookups,
    get_metrics,
    google_books_by_isbn,
    google_books_search,
    openlibrary_by_isbn,
    openlibrary_search,
    openlibrary_work_details,
    probe_sources,
    reset_failed_lookups,
    save_cache,
)

logger = logging.getLogger(__name__)


def gather_candidates(evidence: Evidence, max_isbns: int = 2) -> list[Candidate]:
    """Query both providers: ISBN lookups first, then field-scoped searches."""
    candidates: list[Candidate] = []

    for isbn in evidence.ordered_isbns()[:max_isbns]:
        candidates.extend(openlibrary_by_isbn(isbn))
        candidates.extend(google_books_by_isbn(isbn))

    author = evidence.authors[0] if evidence.authors else ""
    for title in evidence.query_titles():
        found = [*openlibrary_search(title, author), *google_books_search(title, author)]
        # Retry without the author only when *this* title found nothing with it;
        # testing the accumulated list made the fallback fire for the first
        # title only, whatever the later ones returned.
        if author and not any(c.strategy == "title_author" for c in found):
            found += [*openlibrary_search(title), *google_books_search(title)]
        candidates.extend(found)

    return [c for c in candidates if c.title]


def enrich_from_apis(
    record: BookRecord,
    adjudicator: Optional[Callable[[BookRecord, Candidate, Evidence], Optional[bool]]] = None,
) -> dict:
    """
    Enrich one record. Returns a result dict describing what happened, which
    the pipeline folds into its run report.
    """
    evidence = collect_evidence(record)
    reset_failed_lookups()
    result = {
        "verdict": REJECT,
        "score": 0.0,
        "provider": "",
        "reason": "",
        "candidates": 0,
        "evidence": evidence.summary(),
    }

    if not evidence.has_isbn() and not evidence.title_is_searchable():
        record.flag_review("insufficient evidence to identify this file")
        result["reason"] = "insufficient evidence — no ISBN and no usable title"
        return result

    candidates = gather_candidates(evidence)
    # A throttled or failed provider call means the answer below may be missing
    # the right candidate; the pipeline then retries on the next run.
    result["incomplete"] = failed_lookups() > 0
    result["candidates"] = len(candidates)
    if not candidates:
        if result["incomplete"]:
            record.flag_review("metadata lookup incomplete (provider errors) — will retry")
            result["reason"] = "no candidates (provider errors)"
        else:
            record.flag_review("no provider returned a match")
            result["reason"] = "no candidates returned"
        return result

    best, verdict, rejections = best_candidate(candidates, evidence)
    record.rejected_candidates = rejections
    result.update({"verdict": verdict["verdict"], "score": verdict["score"],
                   "reason": verdict["reason"]})

    if best is None:
        record.match_score = verdict["score"]
        record.flag_review(f"no candidate passed verification ({verdict['reason']})")
        logger.info(
            f"   ⛔ rejected all {len(candidates)} candidates for {record.file_name}: "
            f"{verdict['reason']}"
        )
        return result

    # Borderline matches may be adjudicated by the local LLM (§20).
    if verdict["verdict"] == PARTIAL and adjudicator is not None:
        decision = adjudicator(record, best, evidence)
        if decision is True:
            verdict = {**verdict, "verdict": ACCEPT,
                       "reason": verdict["reason"] + " (llm-adjudicated match)"}
            result.update({"verdict": ACCEPT, "reason": verdict["reason"]})
        elif decision is False:
            record.match_score = verdict["score"]
            record.flag_review("llm rejected the borderline match")
            result["verdict"] = REJECT
            result["reason"] = verdict["reason"] + " (llm-adjudicated mismatch)"
            return result

    is_isbn_match = verdict["reason"].startswith("isbn match")
    source = "isbn_match" if is_isbn_match else "api_verified"
    confidence = float(verdict["score"])

    if verdict["verdict"] == ACCEPT:
        _apply_candidate(record, best, source, confidence, identity=True)
        record.match_score = confidence
        result["provider"] = best.provider
        if best.provider not in record.api_sources:
            record.api_sources.append(best.provider)
        logger.info(
            f"   ✅ {best.provider} match ({confidence:.2f}) for {record.file_name}: "
            f"{best.full_title[:70]}"
        )
    else:  # PARTIAL
        _apply_candidate(record, best, "api_partial", confidence, identity=False)
        record.match_score = confidence
        record.flag_review(
            f"borderline match ({confidence:.2f}) with "
            f"'{best.full_title[:60]}' — identity fields left untouched"
        )
        result["provider"] = best.provider
        if best.provider not in record.api_sources:
            record.api_sources.append(best.provider)
        logger.info(
            f"   ⚠️  borderline {best.provider} match ({confidence:.2f}) for "
            f"{record.file_name}: {best.full_title[:70]}"
        )

    return result


def _is_truncation_of(candidate_title: str, current_title: str) -> bool:
    """
    True when the provider's title is just a shortened form of ours.

    OpenLibrary's ISBN record for "Understanding Salafism" is titled
    "Salafism"; accepting it would replace a correct, fuller title with a
    poorer one purely because the match was verified.
    """
    import re as _re

    def norm(text: str) -> str:
        return _re.sub(r"[^\w\s]", " ", (text or "").lower()).strip()

    cand, current = norm(candidate_title), norm(current_title)
    if not cand or not current:
        return False
    return len(cand) < len(current) and cand in current


def _apply_candidate(
    record: BookRecord,
    cand: Candidate,
    source: str,
    confidence: float,
    identity: bool,
):
    """Merge a candidate into the record, field by field, with provenance."""
    if identity:
        # "OneWorld" / "Misquoting Muhammad: …" matched on its subtitle; its bare
        # title is an imprint, and writing it would replace a correct title.
        subtitle_borne = bool(cand.subtitle) and (
            _ratio(cand.full_title, record.title) - _ratio(cand.title, record.title) > 0.4
        )
        if cand.title and not subtitle_borne and not _is_truncation_of(cand.title, record.title):
            record.set_field("title", cand.title.strip(), source, confidence)
        if (cand.subtitle and not subtitle_borne
                and cand.subtitle.strip().lower() not in (record.title or "").lower()):
            record.set_field("subtitle", cand.subtitle.strip(), source, confidence)
        authors = clean_authors(cand.authors)
        if authors:
            record.set_field("authors", authors, source, confidence)
        if cand.publisher:
            record.set_field("publisher", cand.publisher.strip(), source, confidence)
        if cand.year:
            record.set_field("publication_year", cand.year, source, confidence)
        # A title match names the *work*, not this file's edition: its ISBN may
        # fill a gap but must not replace one printed in the file itself.
        if source == "isbn_match" or not (record.isbn_13 or record.isbn_10):
            if cand.isbn_13:
                record.set_field("isbn_13", cand.isbn_13, source, confidence)
            if cand.isbn_10:
                record.set_field("isbn_10", cand.isbn_10, source, confidence)

    # A PDF's own page count is exact; the provider's is some print edition's.
    if cand.page_count and not (record.file_type == "pdf" and record.page_count):
        record.set_field("page_count", cand.page_count, source, confidence * 0.9)
    # Likewise the file's language is this file's; the provider's only fills a gap.
    language = normalise_language(cand.language)
    if language != UNKNOWN and not record.language:
        record.set_field("language", language, source, confidence * 0.9)

    description = cand.description
    subjects = list(cand.subjects or [])
    if cand.provider == "openlibrary" and cand.work_key and (not description or not subjects):
        details = openlibrary_work_details(cand.work_key)
        description = description or details.get("description", "")
        subjects = subjects or details.get("subjects", [])
        if cand.work_key and f"ol:{cand.work_key}" not in record.source_ids:
            record.source_ids.append(f"ol:{cand.work_key}")

    if description:
        record.set_field("description", description[:2000], source, confidence * 0.95)

    if subjects:
        # External subjects are kept raw and searchable; they never become
        # facet categories directly (§A6 — that is the analyzer's job).
        merged = list(dict.fromkeys([*record.subjects_raw, *[s.strip() for s in subjects if s]]))
        record.subjects_raw = merged[:25]

    # A cover is the most visible field in the UI, so a borderline match never
    # gets to supply one — a children's book jacket on a da'wah pamphlet reads
    # as fact long before anyone opens the review queue.
    if identity and cand.cover_url and not record.cover_path:
        _download_cover(record, cand.cover_url, source, confidence)


def _download_cover(record: BookRecord, url: str, source: str, confidence: float):
    """Download a cover image."""
    if record.cover_path:
        return
    try:
        from .providers import _get_session  # pooled session, retries, UA
        resp = _get_session().get(url, timeout=API_REQUEST_TIMEOUT, stream=True)
        resp.raise_for_status()
        content = resp.content
        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type or len(content) < 1000:
            return

        ext = "png" if "png" in content_type else "jpg"
        # Keyed on the record id: `pdfs/x.pdf` and `epubs/x.epub` share a stem
        # and used to overwrite each other's cover.
        cover_path = COVERS_DIR / f"{record.id or Path(record.file_name).stem}_cover.{ext}"
        with open(cover_path, "wb") as f:
            f.write(content)

        try:
            from PIL import Image
            img = Image.open(cover_path)
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            if img.width > 800 or img.height > 1200:
                img.thumbnail((800, 1200), Image.LANCZOS)
            jpg_path = cover_path.with_suffix(".jpg")
            img.save(str(jpg_path), "JPEG", quality=85)
            if jpg_path != cover_path:
                cover_path.unlink(missing_ok=True)
                cover_path = jpg_path
        except Exception:
            pass

        record.set_field(
            "cover_path", str(cover_path.relative_to(COVERS_DIR.parent.parent)),
            source, confidence,
        )
    except requests.RequestException as e:
        logger.debug(f"Failed to download cover from {url}: {e}")
    except Exception as e:  # pragma: no cover - defensive
        logger.debug(f"Cover handling failed for {record.file_name}: {e}")


__all__ = [
    "enrich_from_apis",
    "gather_candidates",
    "get_metrics",
    "probe_sources",
    "save_cache",
]
