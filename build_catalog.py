#!/usr/bin/env python3
"""
Book Catalog Builder — main entry point.

Usage:
    python build_catalog.py                       # full pipeline
    python build_catalog.py --test                # 5 books, no API calls
    python build_catalog.py --only "Aisha.pdf"    # run one file (or a substring)
    python build_catalog.py --max 20              # first 20 books
    python build_catalog.py --type epub           # EPUBs only
    python build_catalog.py --no-api              # skip API enrichment
    python build_catalog.py --llm                 # Ollama summaries + adjudication
    python build_catalog.py --embed               # vector embeddings
    python build_catalog.py --no-ocr              # skip OCR on image-based PDFs
    python build_catalog.py --force               # ignore stage versions, redo everything
    python build_catalog.py --plan                # show what a run would do, write nothing
    python build_catalog.py --verify-sources      # probe providers, then run
    python build_catalog.py --report              # catalog quality report
    python build_catalog.py --review              # list records needing review
    python build_catalog.py --stats               # catalog statistics
    python build_catalog.py --export-json         # write data/catalog.json export
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog.config import CATALOG_DB_FILE, CATALOG_FILE, LOG_FORMAT, LOG_LEVEL, MAX_WORKERS
from catalog.pipeline import Pipeline, PipelineConfig
from catalog.reporting import build_report, print_report, save_report
from catalog.store import CatalogStore


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else getattr(logging, LOG_LEVEL)
    logging.basicConfig(level=level, format=LOG_FORMAT, handlers=[logging.StreamHandler(sys.stdout)])
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("ebooklib").setLevel(logging.WARNING)


def show_stats():
    store = CatalogStore()
    stats = store.compute_stats()
    if not stats:
        print("No catalog found. Run the pipeline first: python build_catalog.py")
        return

    total = stats["total_books"]
    print("\n" + "=" * 60)
    print("📚 BOOK CATALOG STATISTICS")
    print("=" * 60)
    print(f"  Total books:        {total}")
    print(f"  PDFs:               {stats['by_type'].get('pdf', 0)}")
    print(f"  EPUBs:              {stats['by_type'].get('epub', 0)}")
    print(f"  With text:          {stats['with_text']}")
    print(f"  OCR required:       {stats['ocr_required']}")
    print(f"  With cover:         {stats['with_cover']}")
    print(f"  With description:   {stats['with_description']}")
    print(f"  With ISBN:          {stats['with_isbn']}")
    print(f"  With embeddings:    {stats['with_embeddings']}")
    print(f"  API enriched:       {stats['api_enriched']}")
    print(f"  Verified titles:    {stats['verified_titles']}")
    print(f"  Needs a decision:   {stats['needs_review']}")
    print(f"  Unidentified:       {stats.get('unidentified', 0)}")
    print(f"  Duplicates:         {stats['duplicates']}")
    print(f"  Total size:         {stats['total_size_mb']} MB")
    if stats.get("categories"):
        print("\n📂 Categories:")
        for cat, count in list(stats["categories"].items())[:20]:
            print(f"    {cat}: {count}")
    print("=" * 60)


def show_review_queue(limit: int = 40):
    store = CatalogStore()
    records = store.needs_review()
    if not records:
        print("✅ Nothing waiting on a decision.")
        print("   Records no provider could name are a separate list: "
              "python build_catalog.py --unidentified")
        return
    print(f"\n🔎 {len(records)} records need a decision\n")
    for record in records[:limit]:
        score = "—" if record.match_score is None else f"{record.match_score:.2f}"
        print(f"  [{score:>4}] {record.file_name[:60]}")
        print(f"         title: {record.title[:70] or '(none)'} "
              f"(source: {record.field_source('title') or 'none'})")
        for reason in record.review_reasons[:2]:
            print(f"         ↳ {reason[:96]}")
        print()


def show_unidentified(limit: int = 40):
    """
    Records no provider could name.

    Separate from `--review` because there is nothing here to confirm: these
    books are simply not in OpenLibrary or Google Books, which is a fact about
    those catalogues. Their titles come from the filename or the title page,
    and a better one typed by hand is pinned and never overwritten.
    """
    from catalog.models import identity_confidence

    store = CatalogStore()
    records = store.unidentified()
    if not records:
        print("✅ Every book was found in a metadata provider.")
        return
    records.sort(key=identity_confidence)
    print(f"\n❓ {len(records)} records no provider could name "
          f"(least certain identity first)\n")
    for record in records[:limit]:
        print(f"  [id {identity_confidence(record):.2f}] {record.file_name[:60]}")
        print(f"         title: {record.title[:70] or '(none)'} "
              f"(source: {record.field_source('title') or 'none'}, "
              f"{record.enrichment_status})")
        print()


def show_reading_progress():
    from catalog.reading_tracker import get_reading_stats

    store = CatalogStore()
    records = store.all_records()
    if not records:
        print("No catalog found.")
        return
    stats = get_reading_stats(records)
    print("\n" + "=" * 60)
    print("📖 READING PROGRESS")
    print("=" * 60)
    for key in ("total_books", "not_started", "in_progress", "finished", "abandoned"):
        print(f"  {key.replace('_', ' ').title():<16} {stats[key]}")
    print(f"  Percent read:    {stats['percent_read']}%")
    print("=" * 60)


def search_catalog(query: str):
    store = CatalogStore()
    results = store.search(query)
    if not results:
        print(f"No results found for: '{query}'")
        return
    print(f"\n🔍 Found {len(results)} results for '{query}':\n")
    for i, record in enumerate(results[:20], 1):
        authors = ", ".join(record.authors) if record.authors else "Unknown"
        dup = " [DUPLICATE]" if record.duplicate_of else ""
        review = " [NEEDS REVIEW]" if record.needs_review else ""
        print(f"  {i}. {record.title}{dup}{review}")
        print(f"     {authors} | {record.publication_year or 'n.d.'} | "
              f"{', '.join(record.categories[:3]) or 'uncategorised'}")
        print(f"     {record.file_name}")
        print()


def export_csv():
    import csv

    store = CatalogStore()
    records = store.all_records()
    if not records:
        print("No catalog found.")
        return
    csv_path = CATALOG_FILE.with_suffix(".csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Title", "Subtitle", "Authors", "Publisher", "Year", "ISBN",
            "Categories", "Themes", "Language", "Pages", "Title source",
            "Match score", "Needs review", "File",
        ])
        for r in records:
            writer.writerow([
                r.title, r.subtitle, "; ".join(r.authors), r.publisher,
                r.publication_year or "", r.isbn_13 or r.isbn_10 or "",
                "; ".join(r.categories), "; ".join(r.themes), r.language,
                r.page_count or "", r.field_source("title"),
                r.match_score if r.match_score is not None else "",
                "yes" if r.needs_review else "", r.file_name,
            ])
    print(f"Exported {len(records)} books to {csv_path}")


def main():
    parser = argparse.ArgumentParser(
        description="📚 Book Catalog Builder — enrich your local book library",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--test", action="store_true", help="Quick test run (5 books, no API calls)")
    parser.add_argument("--max", type=int, default=None, help="Maximum number of books to process")
    parser.add_argument("--only", type=str, action="append", default=None,
                        help="Only process files whose path contains this substring "
                             "(repeatable: --only Aisha.pdf --only 757.pdf)")
    parser.add_argument("--type", choices=["pdf", "epub"], help="Process only this file type")
    parser.add_argument("--no-api", action="store_true", help="Skip API enrichment")
    parser.add_argument("--embed", action="store_true", help="Generate vector embeddings")
    parser.add_argument("--no-ocr", action="store_true", help="Disable OCR for image-based PDFs")
    parser.add_argument("--llm", action="store_true",
                        help="LLM summaries + borderline-match adjudication (requires Ollama)")
    parser.add_argument("--covers", action="store_true", help="Scrape missing covers via Playwright")
    parser.add_argument("--reading-progress", action="store_true",
                        help="Refresh last-opened times from Spotlight (one subprocess per book)")
    parser.add_argument("--force", action="store_true", help="Reprocess everything, ignoring stage versions")
    parser.add_argument("--plan", action="store_true",
                        help="Show which stages would run for how many books, then exit")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help="Parallel workers")
    parser.add_argument("--verify-sources", action="store_true", help="Probe each provider before running")
    parser.add_argument("--export-json", action="store_true", help="Also write the JSON export")
    parser.add_argument("--watch", action="store_true", help="Watch book folders for changes")
    parser.add_argument("--changes", action="store_true", help="Check for filesystem changes (one-shot)")
    parser.add_argument("--stats", action="store_true", help="Show catalog statistics")
    parser.add_argument("--report", action="store_true", help="Show the catalog quality report")
    parser.add_argument("--review", action="store_true",
                        help="List records waiting on a human decision")
    parser.add_argument("--unidentified", action="store_true",
                        help="List records no metadata provider could name")
    parser.add_argument("--reading", action="store_true", help="Show reading progress")
    parser.add_argument("--search", type=str, help="Search the catalog")
    parser.add_argument("--export-csv", action="store_true", help="Export catalog to CSV")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.stats:
        return show_stats()
    if args.report:
        store = CatalogStore()
        report = build_report(store)
        print_report(report)
        print(f"\nSaved: {save_report(report)}")
        return
    if args.review:
        return show_review_queue()
    if args.unidentified:
        return show_unidentified()
    if args.search:
        return search_catalog(args.search)
    if args.export_csv:
        return export_csv()
    if args.reading:
        return show_reading_progress()

    if args.changes:
        from catalog.watcher import scan_for_changes
        changes = scan_for_changes()
        print(f"\nNew:      {changes['new_count']}")
        print(f"Modified: {changes['modified_count']}")
        print(f"Deleted:  {changes['deleted_count']}")
        for f in changes["new"][:20]:
            print(f"  + {Path(f).name}")
        for f in changes["deleted"][:20]:
            print(f"  - {Path(f).name}")
        return

    if args.watch:
        from catalog.watcher import is_available as watch_available, watch_directories
        if not watch_available():
            print("❌ watchdog not installed. Run: pip install watchdog")
            return
        print("👁️  Starting file watcher... Press Ctrl+C to stop.")

        def _process_new_book(file_path):
            config = PipelineConfig(
                enrich_api=not args.no_api, embed=args.embed,
                ocr=not args.no_ocr, llm_enrich=args.llm, workers=1,
            )
            p = Pipeline(config)
            record = p._process_single_book(file_path)
            if record:
                p.store.upsert(record)
                print(f"  ✅ Cataloged: {record.title}")

        watch_directories(process_callback=_process_new_book)
        return

    if args.test:
        print("🧪 Running in TEST mode (5 books, no API calls)")
        config = PipelineConfig(max_books=5, enrich_api=False, embed=False, workers=args.workers)
    else:
        config = PipelineConfig(
            max_books=args.max,
            only=args.only,
            file_types={args.type} if args.type else None,
            enrich_api=not args.no_api,
            embed=args.embed,
            ocr=not args.no_ocr,
            llm_enrich=args.llm,
            cover_scrape=args.covers,
            reading_progress=args.reading_progress,
            force_reprocess=args.force,
            workers=args.workers,
            verify_sources=args.verify_sources,
            export_json=args.export_json,
        )

    pipeline = Pipeline(config)

    if args.plan:
        plan = pipeline.plan()
        print("\n" + "=" * 60)
        print("PLAN — nothing will be written")
        print("=" * 60)
        print(f"  Files found:    {plan['files_found']}")
        print(f"  New:            {plan['new_files']}")
        print(f"  Stale:          {plan['stale_records']}")
        print(f"  Up to date:     {plan['up_to_date']}")
        if plan["per_unit"]:
            print("\n  Work that would run:")
            for unit, count in plan["per_unit"].items():
                print(f"    {unit:<10} {count} books")
        print("=" * 60)
        return

    stats = pipeline.run()
    report = build_report(CatalogStore(), stats)
    save_report(report)

    if stats.get("interrupted"):
        print("\n⚠️  Interrupted — the catalog is consistent; re-run to finish the remaining books.")
    print(f"\n✅ Catalog: {CATALOG_DB_FILE}")
    print(f"   {stats['needs_review']} records need a decision — "
          "see 'python build_catalog.py --review'")
    print(f"   {stats.get('unidentified', 0)} records no provider could name — "
          "see 'python build_catalog.py --unidentified'")
    print("   Quality report:  python build_catalog.py --report")


if __name__ == "__main__":
    main()
