"""
Reading progress tracker.

Detects last-opened timestamps and reading progress by:
1. Checking macOS file extended attributes (kMDItemLastUsedDate)
2. Reading macOS Spotlight metadata
3. Checking file access time (atime)
4. Integrating with common PDF viewer bookmarks (if available)

Also provides a manual progress update interface.
"""
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import PROJECT_ROOT
from .models import BookRecord

logger = logging.getLogger(__name__)


def update_reading_progress(record: BookRecord, file_path: Path = None) -> BookRecord:
    """
    Update reading progress metadata from filesystem hints.

    Checks:
    - macOS Spotlight kMDItemLastUsedDate
    - File access time (atime)
    - macOS "com.apple.metadata:kMDItemWhereFroms" (download source)
    """
    if file_path is None:
        file_path = PROJECT_ROOT / record.file_path

    if not file_path.exists():
        return record

    # ── Last opened timestamp ────────────────────────────────────────────
    last_opened = _get_last_opened_macos(file_path)
    if last_opened:
        record.last_opened = last_opened

    # ── Infer reading status from access patterns ────────────────────────
    if record.last_opened and record.reading_status == "not_started":
        record.reading_status = "in_progress"

    return record


def _get_last_opened_macos(file_path: Path) -> Optional[str]:
    """
    Get the last-opened date from macOS Spotlight metadata.
    Uses mdls which queries the Spotlight index.
    """
    try:
        result = subprocess.run(
            ["mdls", "-name", "kMDItemLastUsedDate", str(file_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            # Parse: kMDItemLastUsedDate = 2024-01-15 10:30:00 +0000
            if "= " in output and "(null)" not in output:
                date_str = output.split("= ", 1)[1].strip()
                # Parse the date
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")
                    return dt.isoformat()
                except ValueError:
                    # Try without timezone
                    try:
                        dt = datetime.strptime(date_str.split(" +")[0], "%Y-%m-%d %H:%M:%S")
                        return dt.isoformat()
                    except ValueError:
                        pass
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Fallback: use file access time
    try:
        atime = file_path.stat().st_atime
        mtime = file_path.stat().st_mtime
        # Only use atime if it's meaningfully different from mtime
        # (some filesystems don't track atime properly)
        if abs(atime - mtime) > 60:
            dt = datetime.fromtimestamp(atime)
            return dt.isoformat()
    except OSError:
        pass

    return None


def _get_download_source_macos(file_path: Path) -> Optional[str]:
    """Get the download source URL from macOS extended attributes."""
    try:
        result = subprocess.run(
            ["mdls", "-name", "kMDItemWhereFroms", str(file_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and "(null)" not in result.stdout:
            output = result.stdout.strip()
            if "= (" in output:
                # Parse the array
                urls = output.split("= (")[1].rstrip(")").strip()
                url_list = [u.strip().strip('"') for u in urls.split(",")]
                return url_list[0] if url_list else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def set_reading_status(record: BookRecord, status: str, progress: float = None):
    """
    Manually set reading status and progress.

    Args:
        record: BookRecord to update
        status: One of 'not_started', 'in_progress', 'finished', 'abandoned'
        progress: Optional progress percentage (0-100)
    """
    valid_statuses = {"not_started", "in_progress", "finished", "abandoned"}
    if status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {valid_statuses}")

    record.reading_status = status

    if progress is not None:
        record.progress_percent = max(0.0, min(100.0, float(progress)))

    if status == "finished":
        record.progress_percent = 100.0

    logger.info(
        f"Updated reading status for '{record.title}': "
        f"{status} ({record.progress_percent}%)"
    )


def get_reading_stats(records: list[BookRecord]) -> dict:
    """Compute reading statistics across all books."""
    total = len(records)
    if not total:
        return {}

    by_status = {}
    for r in records:
        status = r.reading_status or "not_started"
        by_status[status] = by_status.get(status, 0) + 1

    recently_opened = sorted(
        [r for r in records if r.last_opened],
        key=lambda r: r.last_opened,
        reverse=True,
    )[:10]

    return {
        "total_books": total,
        "by_status": by_status,
        "not_started": by_status.get("not_started", 0),
        "in_progress": by_status.get("in_progress", 0),
        "finished": by_status.get("finished", 0),
        "abandoned": by_status.get("abandoned", 0),
        "percent_read": round(by_status.get("finished", 0) / total * 100, 1),
        "recently_opened": [
            {"title": r.title, "last_opened": r.last_opened}
            for r in recently_opened
        ],
    }
