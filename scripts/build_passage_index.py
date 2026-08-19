"""
Build the passage index (Part 1).

    python scripts/build_passage_index.py --limit 30     # phase 0 vertical slice
    python scripts/build_passage_index.py                # everything not yet indexed
    python scripts/build_passage_index.py --force        # re-chunk and re-embed all
    python scripts/build_passage_index.py --status       # what is in there now

Measured cost for the full library: extraction ~3 min with PyMuPDF, embedding
~23 min for ~272k chunks at 199 chunks/s, ~900 MB on disk (text 340 MB, FTS
~150 MB, vectors ~210 MB at float16). It is resumable — a second run indexes
only the books the first one did not reach, and carries the existing vectors
over rather than recomputing them.
"""
import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from catalog.config import CATALOG_DB_FILE
from catalog.passage_index import build_index, drop_index, index_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("build-index")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="index at most N books (phase 0 slice)")
    parser.add_argument("--book", action="append", dest="books",
                        help="index this book id; repeatable")
    parser.add_argument("--force", action="store_true",
                        help="re-chunk and re-embed books that are already indexed")
    parser.add_argument("--force-text", action="store_true",
                        help="also discard the cached extracted text and read the files again")
    parser.add_argument("--status", action="store_true", help="print index status and exit")
    parser.add_argument("--drop", action="store_true", help="delete the index and exit")
    parser.add_argument("--db", type=Path, default=CATALOG_DB_FILE)
    args = parser.parse_args()

    conn = sqlite3.connect(str(args.db))
    try:
        if args.status:
            print(json.dumps(index_status(conn), indent=2))
            return 0
        if args.drop:
            drop_index(conn)
            log.info("Passage index dropped")
            return 0

        def progress(done: int, total: int, title: str):
            log.info(f"[{done}/{total}] {title[:70]}")

        result = build_index(
            conn,
            book_ids=args.books,
            force=args.force,
            force_text=args.force_text,
            limit=args.limit,
            progress=progress,
        )
        print(json.dumps(result.as_dict(), indent=2))
        return 1 if result.books_failed and not result.chunks_written else 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
