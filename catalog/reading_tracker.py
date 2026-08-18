"""
Reading progress tracker.

Derives a last-opened timestamp from filesystem hints (macOS Spotlight
`kMDItemLastUsedDate`, falling back to atime). It deliberately does *not* infer
a reading status: opening a file in Preview to check the cover is not the same
as starting to read it, and guessing here used to overwrite what the user had
set in the UI.

`last_opened` is user-owned — the reader writes it every time a book is opened
in the app. Spotlight only knows when the *file* was last opened on disk, which
is usually older, so the hint may only ever move the timestamp **forward**.
Writing it unconditionally silently walked real reading history backwards.
"""
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import PROJECT_ROOT
from .models import BookRecord

logger = logging.getLogger(__name__)


def update_reading_progress(
    record: BookRecord,
    file_path: Path = None,
    known_last_opened: Optional[str] = None,
) -> BookRecord:
    """
    Advance `last_opened` if the filesystem knows of a *newer* open.

    `known_last_opened` is the authoritative stored value, when the caller has
    it; otherwise whatever the record carries is used as the baseline.
    """
    if file_path is None:
        file_path = PROJECT_ROOT / record.file_path

    if not file_path.exists():
        return record

    current = known_last_opened if known_last_opened is not None else record.last_opened
    hint = _get_last_opened_macos(file_path)
    if hint and is_newer(hint, current):
        record.last_opened = hint

    return record


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """
    Parse a stored timestamp into an aware datetime.

    Three writers, three shapes: the web reader sends `...Z` from
    `Date.toISOString()`, Spotlight yields `+00:00`, and the atime fallback is
    naive local time. Comparing those as strings gets the ordering wrong, which
    is the whole point of the comparison.
    """
    if not value:
        return None
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone() if parsed.tzinfo is None else parsed


def is_newer(candidate: Optional[str], current: Optional[str]) -> bool:
    """True when `candidate` is a strictly later timestamp than `current`."""
    if not candidate:
        return False
    existing = _parse_timestamp(current)
    if existing is None:
        return True                      # nothing recorded yet: anything is news
    incoming = _parse_timestamp(candidate)
    if incoming is None:
        return False                     # unparseable hint never displaces a real value
    return incoming > existing


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
