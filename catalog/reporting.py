"""
Catalog quality reporting.

"You cannot improve accuracy you cannot measure — the fact that OpenLibrary
contributed zero records for months is the proof." The old summary printed ten
counters, all of them success counts. This adds per-field provenance, fill
rates, the confidence distribution and the least certain identities.
"""
import json
from collections import Counter
from datetime import datetime
from typing import Optional

from .config import REPORT_FILE
from .enrichment_status import UNIDENTIFIED
from .models import identity_confidence
from .store import CatalogStore

_TRACKED_FIELDS = [
    "title", "authors", "publisher", "publication_year", "isbn_13",
    "description", "categories", "summary", "cover_path", "language",
]


def build_report(store: CatalogStore, stats: Optional[dict] = None) -> dict:
    records = store.all_records(include_missing=True)
    total = len(records)
    if not total:
        return {"total_books": 0}

    field_sources: dict[str, Counter] = {f: Counter() for f in _TRACKED_FIELDS}
    fill: dict[str, int] = {f: 0 for f in _TRACKED_FIELDS}
    for record in records:
        for name in _TRACKED_FIELDS:
            value = getattr(record, name, None)
            if value:
                fill[name] += 1
                field_sources[name][record.field_source(name) or "unsourced"] += 1

    buckets = Counter()
    for record in records:
        score = record.match_score
        if score is None:
            buckets["unmatched"] += 1
        elif score >= 0.95:
            buckets["0.95–1.00"] += 1
        elif score >= 0.75:
            buckets["0.75–0.95"] += 1
        elif score >= 0.45:
            buckets["0.45–0.75"] += 1
        else:
            buckets["<0.45"] += 1

    enrichment = Counter(r.enrichment_status or "none" for r in records)
    review = [r for r in records if r.needs_review]
    # Disjoint from `review`, the same way the store and the API define it.
    unidentified = [
        r for r in records
        if r.enrichment_status in UNIDENTIFIED and not r.needs_review
    ]
    # Ranked by identity confidence, not `match_score`. A record with no API
    # match has `match_score is None`, and sorting that as -1 put an EPUB
    # identified perfectly from its own `dc:` metadata at the very top of the
    # "worst" list, below a 0.20 rubbish match.
    # Both buckets, worst first: a record nobody could identify is still the
    # most useful thing to put in front of a person, even though there is
    # nothing about it to "confirm".
    worst = sorted(review + unidentified, key=identity_confidence)[:25]

    categories = Counter()
    for record in records:
        categories.update(record.categories)

    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "total_books": total,
        "active": sum(1 for r in records if r.status == "active"),
        "missing": sum(1 for r in records if r.status == "missing"),
        "fill_rates": {
            name: {"count": count, "pct": round(100 * count / total, 1)}
            for name, count in fill.items()
        },
        "field_sources": {name: dict(counter) for name, counter in field_sources.items()},
        "match_score_distribution": dict(buckets),
        "needs_review": len(review),
        "unidentified": len(unidentified),
        "enrichment_status": dict(enrichment.most_common()),
        "duplicates": sum(1 for r in records if r.duplicate_of),
        "categories": dict(categories.most_common(25)),
        "distinct_categories": len(categories),
        "categories_used_once": sum(1 for c in categories.values() if c == 1),
        "worst_records": [
            {
                "file_name": r.file_name,
                "title": r.title,
                "identity_confidence": identity_confidence(r),
                "match_score": r.match_score,
                "reasons": r.review_reasons,
                "title_source": r.field_source("title"),
            }
            for r in worst
        ],
        "run_stats": stats or {},
    }


def save_report(report: dict, path=REPORT_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return path


def print_report(report: dict):
    if not report.get("total_books"):
        print("No catalog found. Run the pipeline first.")
        return

    total = report["total_books"]
    print("\n" + "=" * 68)
    print("📊 CATALOG QUALITY REPORT")
    print("=" * 68)
    print(f"  Books: {total}  (active {report['active']}, missing {report['missing']})")
    print(f"  Needs a decision: {report['needs_review']}   "
          f"Unidentified: {report.get('unidentified', 0)}   "
          f"Duplicates: {report['duplicates']}")
    if report.get("enrichment_status"):
        rendered = "  ".join(
            f"{name}={count}" for name, count in report["enrichment_status"].items()
        )
        print(f"  Enrichment: {rendered}")
    print(f"  Categories: {report['distinct_categories']} distinct, "
          f"{report['categories_used_once']} used once")

    print("\n  Field coverage and where the value came from:")
    for name, info in report["fill_rates"].items():
        sources = report["field_sources"].get(name, {})
        rendered = ", ".join(
            f"{src}={count}" for src, count in sorted(sources.items(), key=lambda kv: -kv[1])
        )
        print(f"    {name:<18} {info['count']:>4}/{total} ({info['pct']:>5.1f}%)  {rendered}")

    print("\n  Match score distribution:")
    for bucket, count in report["match_score_distribution"].items():
        print(f"    {bucket:<12} {count}")

    if report["worst_records"]:
        print("\n  Least certain identities (review these first):")
        print("    identity = how sure we are which book this is; "
              "match = the API candidate's score")
        for item in report["worst_records"][:15]:
            identity = item.get("identity_confidence") or 0.0
            match = "—" if item["match_score"] is None else f"{item['match_score']:.2f}"
            reason = (item["reasons"] or [""])[0][:52]
            print(f"    [id {identity:.2f} | match {match:>4}] "
                  f"{item['file_name'][:38]:<38} {reason}")

    metrics = (report.get("run_stats") or {}).get("provider_metrics") or {}
    if metrics:
        print("\n  Provider health (last run):")
        for source, counts in metrics.items():
            print(f"    {source:<14} {counts}")
    print("=" * 68)
