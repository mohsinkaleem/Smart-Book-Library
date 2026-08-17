"""
Reading progress tracker.

Derives a last-opened timestamp from filesystem hints (macOS Spotlight
`kMDItemLastUsedDate`, falling back to atime). It deliberately does *not* infer
a reading status: opening a file in Preview to check the cover is not the same
as starting to read it, and guessing here used to overwrite what the user had
set in the UI.
"""
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import PROJECT_ROOT
from .models import BookRecord

logger = logging.getLogger(__name__)


def update_reading_progress(record: BookRecord, file_path: Path = None) -> BookRecord:
    """Record when the file was last opened, if the filesystem knows."""
    if file_path is None:
        file_path = PROJECT_ROOT / record.file_path

    if not file_path.exists():
        return record

    last_opened = _get_last_opened_macos(file_path)
    if last_opened:
        record.last_opened = last_opened

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
