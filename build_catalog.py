#!/usr/bin/env python3
"""
Book Catalog Builder - Main entry point.

Usage:
    # Full pipeline (all books, with API enrichment)
    python build_catalog.py

    # Quick test with 5 books, no API calls
    python build_catalog.py --test

    # Process only EPUBs
    python build_catalog.py --type epub

    # Force reprocess everything
    python build_catalog.py --force

    # With embeddings (requires sentence-transformers)
    python build_catalog.py --embed

    # Process specific number of books
    python build_catalog.py --max 50

    # Skip API enrichment (file metadata only)
    python build_catalog.py --no-api

    # Run OCR on image-based PDFs
    python build_catalog.py --ocr

    # LLM-powered summaries (requires running Ollama)
    python build_catalog.py --llm

    # Scrape missing covers with Playwright
    python build_catalog.py --covers

    # Watch for new books (incremental)
    python build_catalog.py --watch

    # Check for filesystem changes (one-shot)
    python build_catalog.py --changes

    # Show catalog stats
    python build_catalog.py --stats

    # Show reading progress
    python build_catalog.py --reading

    # Search catalog
    python build_catalog.py --search "machine learning"
"""
import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog.config import LOG_LEVEL, LOG_FORMAT, CATALOG_FILE
from catalog.pipeline import run_pipeline, PipelineConfig, Pipeline
from catalog.database import CatalogDatabase


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else getattr(logging, LOG_LEVEL)
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    # Suppress noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("ebooklib").setLevel(logging.WARNING)


def show_stats():
    """Display catalog statistics."""
    db = CatalogDatabase()
    records = db.all_records()

    if not records:
        print("No catalog found. Run the pipeline first: python build_catalog.py")
        return

    stats = db._compute_stats()
    print("\n" + "=" * 60)
    print("📚 BOOK CATALOG STATISTICS")
    print("=" * 60)
    print(f"  Total books:        {stats['total_books']}")
    print(f"  PDFs:               {stats['by_type'].get('pdf', 0)}")
    print(f"  EPUBs:              {stats['by_type'].get('epub', 0)}")
    print(f"  With text:          {stats['with_text']}")
    print(f"  OCR required:       {stats['ocr_required']}")
    print(f"  With cover:         {stats['with_cover']}")
    print(f"  With description:   {stats['with_description']}")
    print(f"  With ISBN:          {stats['with_isbn']}")
    print(f"  With embeddings:    {stats['with_embeddings']}")
    print(f"  API enriched:       {stats['api_enriched']}")
    print(f"  Duplicates:         {stats['duplicates']}")
    print(f"  Total size:         {stats['total_size_mb']} MB")
    print()

    # Quality metrics
    total = stats['total_books']
    if total > 0:
        print("📊 Data Quality:")
        print(f"    Description coverage: {stats['with_description']}/{total} ({stats['with_description']*100//total}%)")
        print(f"    ISBN coverage:        {stats['with_isbn']}/{total} ({stats['with_isbn']*100//total}%)")
        print(f"    Cover coverage:       {stats['with_cover']}/{total} ({stats['with_cover']*100//total}%)")
        print(f"    Text extraction:      {stats['with_text']}/{total} ({stats['with_text']*100//total}%)")
        print(f"    Still needs OCR:      {stats['ocr_required']}")
        print()

    if stats.get("categories"):
        print("📂 Top Categories:")
        for cat, count in list(stats["categories"].items())[:15]:
            print(f"    {cat}: {count}")

    print("=" * 60)


def show_reading_progress():
    """Display reading progress statistics."""
    from catalog.reading_tracker import get_reading_stats

    db = CatalogDatabase()
    records = db.all_records()

    if not records:
        print("No catalog found.")
        return

    stats = get_reading_stats(records)
    print("\n" + "=" * 60)
    print("📖 READING PROGRESS")
    print("=" * 60)
    print(f"  Total books:    {stats['total_books']}")
    print(f"  Not started:    {stats['not_started']}")
    print(f"  In progress:    {stats['in_progress']}")
    print(f"  Finished:       {stats['finished']}")
    print(f"  Abandoned:      {stats['abandoned']}")
    print(f"  Percent read:   {stats['percent_read']}%")
    print()

    recently = stats.get("recently_opened", [])
    if recently:
        print("🕐 Recently Opened:")
        for item in recently[:10]:
            dt = item["last_opened"][:16].replace("T", " ") if item["last_opened"] else "N/A"
            print(f"    {dt}  {item['title'][:60]}")

    print("=" * 60)


def search_catalog(query: str):
    """Search the catalog and display results."""
    db = CatalogDatabase()
    results = db.search(query)

    if not results:
        print(f"No results found for: '{query}'")
        return

    print(f"\n🔍 Found {len(results)} results for '{query}':\n")
    for i, record in enumerate(results[:20], 1):
        authors = ", ".join(record.authors) if record.authors else "Unknown"
        year = record.publication_year or "N/A"
        cats = ", ".join(record.categories[:3]) if record.categories else "N/A"
        dup = " [DUPLICATE]" if record.duplicate_of else ""
        print(f"  {i}. {record.title}{dup}")
        print(f"     Authors: {authors} | Year: {year}")
        print(f"     Categories: {cats}")
        print(f"     File: {record.file_name}")
        if record.description:
            print(f"     Description: {record.description[:120]}...")
        print()


def export_csv():
    """Export catalog to CSV."""
    import csv

    db = CatalogDatabase()
    records = db.all_records()
    if not records:
        print("No catalog found.")
        return

    csv_path = CATALOG_FILE.with_suffix(".csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Title", "Authors", "Publisher", "Year", "ISBN",
            "Categories", "Themes", "Language", "Pages",
            "Has Text", "File Type", "File Name", "Description",
        ])
        for r in records:
            writer.writerow([
                r.title,
                "; ".join(r.authors),
                r.publisher,
                r.publication_year or "",
                r.isbn_13 or r.isbn_10 or "",
                "; ".join(r.categories[:5]),
                "; ".join(r.themes[:5]),
                r.language,
                r.page_count or "",
                r.has_text,
                r.file_type,
                r.file_name,
                r.description[:200] if r.description else "",
            ])

    print(f"Exported {len(records)} books to {csv_path}")


def main():
    parser = argparse.ArgumentParser(
        description="📚 Book Catalog Builder - Enrich your local book library",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python build_catalog.py                    # Full pipeline
  python build_catalog.py --test             # Quick test (5 books, no API)
  python build_catalog.py --max 20           # Process first 20 books
  python build_catalog.py --type epub        # EPUBs only
  python build_catalog.py --no-api           # Skip API enrichment
  python build_catalog.py --embed            # Include embeddings
  python build_catalog.py --ocr              # OCR image-based PDFs
  python build_catalog.py --llm              # LLM summaries (requires Ollama)
  python build_catalog.py --covers           # Scrape missing covers
  python build_catalog.py --force            # Reprocess everything
  python build_catalog.py --watch            # Watch folders for new books
  python build_catalog.py --changes          # Check for filesystem changes
  python build_catalog.py --stats            # Show catalog stats
  python build_catalog.py --reading          # Show reading progress
  python build_catalog.py --search "python"  # Search catalog
  python build_catalog.py --export-csv       # Export to CSV
        """,
    )
    parser.add_argument("--test", action="store_true",
                        help="Quick test run (5 books, no API calls)")
    parser.add_argument("--max", type=int, default=None,
                        help="Maximum number of books to process")
    parser.add_argument("--type", choices=["pdf", "epub"],
                        help="Process only this file type")
    parser.add_argument("--no-api", action="store_true",
                        help="Skip API enrichment")
    parser.add_argument("--embed", action="store_true",
                        help="Generate vector embeddings (requires sentence-transformers)")
    parser.add_argument("--ocr", action="store_true",
                        help="Enable OCR for image-based PDFs (requires tesseract + poppler)")
    parser.add_argument("--llm", action="store_true",
                        help="Enable LLM-powered summaries/themes (requires running Ollama)")
    parser.add_argument("--covers", action="store_true",
                        help="Scrape missing covers via Playwright")
    parser.add_argument("--force", action="store_true",
                        help="Force reprocess all books")
    parser.add_argument("--watch", action="store_true",
                        help="Watch book folders for changes (requires watchdog)")
    parser.add_argument("--changes", action="store_true",
                        help="Check for filesystem changes vs catalog (one-shot)")
    parser.add_argument("--stats", action="store_true",
                        help="Show catalog statistics")
    parser.add_argument("--reading", action="store_true",
                        help="Show reading progress")
    parser.add_argument("--search", type=str,
                        help="Search the catalog")
    parser.add_argument("--export-csv", action="store_true",
                        help="Export catalog to CSV")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging")

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Info-only commands
    if args.stats:
        show_stats()
        return

    if args.search:
        search_catalog(args.search)
        return

    if args.export_csv:
        export_csv()
        return

    if args.reading:
        show_reading_progress()
        return

    if args.changes:
        from catalog.watcher import scan_for_changes
        changes = scan_for_changes()
        print(f"\nNew:      {changes['new_count']}")
        print(f"Modified: {changes['modified_count']}")
        print(f"Deleted:  {changes['deleted_count']}")
        if changes['new']:
            print("\nNew files:")
            for f in changes['new'][:20]:
                print(f"  + {Path(f).name}")
        if changes['deleted']:
            print("\nDeleted from catalog:")
            for f in changes['deleted'][:20]:
                print(f"  - {Path(f).name}")
        return

    if args.watch:
        from catalog.watcher import watch_directories, is_available as watch_available
        if not watch_available():
            print("❌ watchdog not installed. Run: pip install watchdog")
            return
        print("👁️  Starting file watcher... Press Ctrl+C to stop.")

        def _process_new_book(file_path):
            """Process a single new book through the pipeline."""
            config = PipelineConfig(
                enrich_api=not args.no_api,
                embed=args.embed,
                ocr=args.ocr,
                llm_enrich=args.llm,
            )
            p = Pipeline(config)
            record = p._process_single_book(file_path)
            if record:
                p.db.upsert(record)
                p.db.save()
                print(f"  ✅ Cataloged: {record.title}")

        watch_directories(process_callback=_process_new_book)
        return

    # Pipeline commands
    if args.test:
        print("🧪 Running in TEST mode (5 books, no API calls)")
        stats = run_pipeline(max_books=5, enrich_api=False, embed=False)
    else:
        file_types = {args.type} if args.type else None
        stats = run_pipeline(
            max_books=args.max,
            enrich_api=not args.no_api,
            embed=args.embed,
            force=args.force,
            file_types=file_types,
            ocr=args.ocr,
            llm=args.llm,
            cover_scrape=args.covers,
        )

    print(f"\n✅ Catalog saved to: {CATALOG_FILE}")
    print(f"   Run 'python build_catalog.py --stats' to see statistics")


if __name__ == "__main__":
    main()
