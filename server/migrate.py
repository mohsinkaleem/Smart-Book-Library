"""
One-time import of a legacy `catalog.json` into SQLite.

SQLite is now the store of record, so this is a migration tool, not part of any
run loop. It is also non-destructive: the old version `unlink()`d the database
first, which threw away everything the user had done in the web app
run or a full rebuild.

Usage: python -m server.migrate [--force]
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from catalog.config import CATALOG_FILE  # noqa: E402
from catalog.store import CatalogStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def migrate(force: bool = False):
    store = CatalogStore()
    existing = store.count(include_missing=True)

    if not CATALOG_FILE.exists():
        logger.info(f"No {CATALOG_FILE} to import. Catalog holds {existing} books.")
        return

    if existing and not force:
        logger.warning(
            f"SQLite already holds {existing} books — nothing to do. "
            "Re-run with --force to import catalog.json over it."
        )
        return

    logger.info(f"Importing {CATALOG_FILE}...")
    count = store.import_json(CATALOG_FILE)
    logger.info(f"Imported {count} records. Catalog now holds {store.count(include_missing=True)}.")
    logger.info("Run 'python build_catalog.py' to re-enrich them through the verification gate.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import a legacy catalog.json into SQLite")
    parser.add_argument("--force", action="store_true",
                        help="Import even when SQLite already has records")
    migrate(parser.parse_args().force)
