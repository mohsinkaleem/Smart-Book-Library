"""
Incremental folder watcher using watchdog.

Monitors book directories for new/modified/deleted files and
automatically triggers cataloging for changes.

Usage:
    python -m catalog.watcher          # Watch and auto-catalog
    python -m catalog.watcher --once   # Single scan for changes, then exit

Requirements:
    pip install watchdog
"""
import logging
import sys
import time
from pathlib import Path
from typing import Optional

from .config import BOOKS_DIRS, SUPPORTED_EXTENSIONS, PROJECT_ROOT
from .models import BookRecord
from .scanner import create_basic_record, compute_sha1
from .database import CatalogDatabase, ProcessingLog

logger = logging.getLogger(__name__)

# Debounce: wait this many seconds after last change before processing
DEBOUNCE_SECONDS = 5.0


def is_available() -> bool:
    """Check if watchdog is installed."""
    try:
        import watchdog  # noqa: F401
        return True
    except ImportError:
        return False


class BookFileHandler:
    """
    Handles file system events for book files.
    Queues changes and processes them after a debounce period.
    """

    def __init__(self, db: CatalogDatabase, process_callback=None):
        self.db = db
        self.process_callback = process_callback
        self._pending_adds: dict[str, Path] = {}
        self._pending_deletes: set[str] = set()
        self._last_event_time = 0.0

    def on_created(self, src_path: str):
        """Handle new file creation."""
        path = Path(src_path)
        if self._is_book_file(path):
            logger.info(f"📥 New book detected: {path.name}")
            self._pending_adds[str(path)] = path
            self._last_event_time = time.time()

    def on_modified(self, src_path: str):
        """Handle file modification."""
        path = Path(src_path)
        if self._is_book_file(path):
            logger.debug(f"📝 Book modified: {path.name}")
            self._pending_adds[str(path)] = path
            self._last_event_time = time.time()

    def on_deleted(self, src_path: str):
        """Handle file deletion."""
        path = Path(src_path)
        if self._is_book_file(path):
            logger.info(f"🗑️  Book removed: {path.name}")
            self._pending_deletes.add(str(path))
            self._last_event_time = time.time()

    def on_moved(self, src_path: str, dest_path: str):
        """Handle file move/rename."""
        src = Path(src_path)
        dest = Path(dest_path)
        if self._is_book_file(src) or self._is_book_file(dest):
            logger.info(f"📦 Book moved: {src.name} → {dest.name}")
            self._pending_deletes.add(str(src))
            if self._is_book_file(dest):
                self._pending_adds[str(dest)] = dest
            self._last_event_time = time.time()

    def process_pending(self) -> int:
        """
        Process any pending changes if the debounce period has elapsed.
        Returns the number of changes processed.
        """
        if not self._pending_adds and not self._pending_deletes:
            return 0

        if time.time() - self._last_event_time < DEBOUNCE_SECONDS:
            return 0  # Still within debounce window

        changes = 0

        # Handle deletions
        for path_str in self._pending_deletes:
            try:
                rel_path = str(Path(path_str).relative_to(PROJECT_ROOT))
                record = self.db.get_by_path(rel_path)
                if record:
                    self.db.remove(record.id)
                    logger.info(f"   ✅ Removed from catalog: {Path(path_str).name}")
                    changes += 1
            except Exception as e:
                logger.error(f"Failed to remove {path_str}: {e}")
        self._pending_deletes.clear()

        # Handle additions/modifications
        for path_str, file_path in self._pending_adds.items():
            if not file_path.exists():
                continue
            try:
                if self.process_callback:
                    self.process_callback(file_path)
                    changes += 1
                else:
                    # Basic cataloging without full pipeline
                    record = create_basic_record(file_path, PROJECT_ROOT)
                    self.db.upsert(record)
                    logger.info(f"   ✅ Added to catalog: {file_path.name}")
                    changes += 1
            except Exception as e:
                logger.error(f"Failed to process {file_path.name}: {e}")
        self._pending_adds.clear()

        if changes > 0:
            self.db.save()
            logger.info(f"💾 Catalog saved ({changes} changes)")

        return changes

    @staticmethod
    def _is_book_file(path: Path) -> bool:
        """Check if a path is a supported book file."""
        return (
            path.is_file() or not path.exists()  # Allow deleted files
        ) and path.suffix.lower() in SUPPORTED_EXTENSIONS


def watch_directories(
    directories: list[Path] = None,
    process_callback=None,
    stop_after_seconds: Optional[float] = None,
):
    """
    Watch book directories for changes and auto-catalog new files.

    Args:
        directories: List of directories to watch (defaults to BOOKS_DIRS)
        process_callback: Optional callback(file_path) for full processing
        stop_after_seconds: Optional timeout for testing (None = run forever)
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        logger.error(
            "watchdog not installed. Install with:\n"
            "  pip install watchdog"
        )
        return

    dirs = directories or BOOKS_DIRS
    db = CatalogDatabase()
    handler = BookFileHandler(db, process_callback)

    class _WatchdogAdapter(FileSystemEventHandler):
        """Adapter between watchdog events and our handler."""
        def on_created(self, event):
            if not event.is_directory:
                handler.on_created(event.src_path)

        def on_modified(self, event):
            if not event.is_directory:
                handler.on_modified(event.src_path)

        def on_deleted(self, event):
            if not event.is_directory:
                handler.on_deleted(event.src_path)

        def on_moved(self, event):
            if not event.is_directory:
                handler.on_moved(event.src_path, event.dest_path)

    observer = Observer()
    adapter = _WatchdogAdapter()

    for d in dirs:
        if d.exists():
            observer.schedule(adapter, str(d), recursive=True)
            logger.info(f"👁️  Watching: {d}")
        else:
            logger.warning(f"Directory not found, skipping: {d}")

    observer.start()
    logger.info("📡 File watcher started. Press Ctrl+C to stop.")

    start_time = time.time()
    try:
        while True:
            time.sleep(1.0)
            handler.process_pending()

            if stop_after_seconds and (time.time() - start_time) > stop_after_seconds:
                logger.info("Watcher timeout reached, stopping.")
                break
    except KeyboardInterrupt:
        logger.info("\n🛑 Watcher stopped by user.")
    finally:
        observer.stop()
        observer.join()
        db.save()


def scan_for_changes() -> dict:
    """
    Single-pass scan: compare filesystem to catalog and report changes.
    Returns dict with 'new', 'modified', 'deleted' lists.
    """
    from .scanner import scan_all_directories

    db = CatalogDatabase()
    current_files = scan_all_directories()

    # Build sets for comparison
    catalog_paths = {r.file_path for r in db.all_records()}
    fs_paths = set()
    new_files = []
    modified_files = []

    for fp in current_files:
        rel = str(fp.relative_to(PROJECT_ROOT))
        fs_paths.add(rel)

        existing = db.get_by_path(rel)
        if not existing:
            new_files.append(fp)
        else:
            # Check if file was modified (size changed)
            if fp.stat().st_size != existing.size:
                modified_files.append(fp)

    # Deleted files
    deleted_paths = catalog_paths - fs_paths

    result = {
        "new": [str(f) for f in new_files],
        "modified": [str(f) for f in modified_files],
        "deleted": list(deleted_paths),
        "new_count": len(new_files),
        "modified_count": len(modified_files),
        "deleted_count": len(deleted_paths),
    }

    if any(result[k] for k in ("new", "modified", "deleted")):
        logger.info(
            f"Changes detected: {len(new_files)} new, "
            f"{len(modified_files)} modified, {len(deleted_paths)} deleted"
        )
    else:
        logger.info("No changes detected — catalog is up to date")

    return result


# ─── CLI entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if "--once" in sys.argv:
        changes = scan_for_changes()
        print(f"\nNew: {changes['new_count']}")
        print(f"Modified: {changes['modified_count']}")
        print(f"Deleted: {changes['deleted_count']}")
    else:
        watch_directories()
