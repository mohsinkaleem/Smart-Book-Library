"""
OCR the books that have no text layer (Part 5 / §1.10).

    python scripts/ocr_books.py --list              # which books need it
    python scripts/ocr_books.py --book <id>         # one book
    python scripts/ocr_books.py --all               # all of them

19 books in this library are image-only. They are invisible to search,
similarity and the passage index, and — since Part 2 — every text affordance in
the reader is inert in them too: nothing to select, nothing to highlight,
nothing to search within. The UI now says so rather than letting that read as a
broken reader; this script is the other half, for when you want to fix it.

**This is slow and deliberately opt-in.** Rendering a page at 300 DPI and
running tesseract over it costs seconds per page, so a full pass over 19
scanned books is hours, not minutes. `OCR_MAX_PAGES` caps how much of each book
is read; raise it (or pass `--max-pages 0`) to do the whole thing.

Requires the `ocr` extra and two system packages:

    pip install 'books[ocr]'
    brew install tesseract poppler
"""
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from catalog.config import OCR_MAX_PAGES
from catalog.store import CatalogStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ocr")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", action="append", dest="books", help="book id; repeatable")
    parser.add_argument("--all", action="store_true", help="OCR every book that needs it")
    parser.add_argument("--list", action="store_true", help="list the books that need OCR")
    parser.add_argument("--max-pages", type=int, default=OCR_MAX_PAGES,
                        help=f"pages per book (default {OCR_MAX_PAGES}); 0 for the whole book")
    parser.add_argument("--reindex", action="store_true",
                        help="rebuild the passage index for the books that gained text")
    args = parser.parse_args()

    # `ocr_pdf` reads the page cap from config rather than taking it as an
    # argument, so the flag is applied there — one setting, one reader of it.
    if args.max_pages != OCR_MAX_PAGES:
        import catalog.ocr_extractor as ocr_module
        ocr_module.OCR_MAX_PAGES = args.max_pages or 10_000

    store = CatalogStore()
    try:
        pending = [
            r for r in store.all_records()
            if r.status != "missing" and (r.ocr_required or not r.has_text)
        ]
        if args.books:
            wanted = set(args.books)
            pending = [r for r in pending if r.id in wanted]

        if args.list or not (args.books or args.all):
            print(f"{len(pending)} books have no text layer:\n")
            for record in pending:
                print(f"  {record.id}  {(record.title or record.file_name)[:64]}")
            if not (args.books or args.all):
                print("\nPass --all to OCR them, or --book <id> for one.")
            return 0

        from catalog.ocr_extractor import is_available, ocr_pdf

        if not is_available():
            log.error("tesseract is not reachable. Run: "
                      "pip install 'books[ocr]' && brew install tesseract poppler")
            return 1

        succeeded: list[str] = []
        for i, record in enumerate(pending, start=1):
            title = (record.title or record.file_name)[:60]
            log.info(f"[{i}/{len(pending)}] {title}")
            started = time.monotonic()
            try:
                ocr_pdf(Path(record.file_path), record)
            except Exception as e:
                log.warning(f"  failed: {e}")
                continue
            if record.has_text:
                store.upsert(record)
                succeeded.append(record.id)
                log.info(f"  {len(record.text_excerpt)} chars in "
                         f"{time.monotonic() - started:.0f}s")
            else:
                log.warning("  no text recovered")

        log.info(f"OCR recovered text for {len(succeeded)} of {len(pending)} books")

        if args.reindex and succeeded:
            import sqlite3
            from catalog.config import CATALOG_DB_FILE
            from catalog.passage_index import build_index

            conn = sqlite3.connect(str(CATALOG_DB_FILE))
            try:
                result = build_index(conn, book_ids=succeeded, force=True)
                log.info(f"Passage index: {result.chunks_written} chunks")
            finally:
                conn.close()
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
