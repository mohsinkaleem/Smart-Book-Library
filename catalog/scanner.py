"""
File scanner — discovers books, computes SHA1, captures basic file metadata.
"""
import hashlib
import logging
from pathlib import Path
from typing import Generator

from .config import BOOKS_DIRS, SUPPORTED_EXTENSIONS
from .models import BookRecord

logger = logging.getLogger(__name__)


def compute_sha1(file_path: Path, chunk_size: int = 1 << 20) -> str:
    """SHA1 of a file's contents."""
    sha1 = hashlib.sha1()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha1.update(chunk)
    return sha1.hexdigest()


def scan_directory(directory: Path) -> Generator[Path, None, None]:
    """Yield all supported book files in a directory (recursively)."""
    if not directory.exists():
        logger.warning(f"Directory does not exist: {directory}")
        return
    for file_path in sorted(directory.rglob("*")):
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield file_path


def scan_all_directories(directories: list[Path] = None) -> list[Path]:
    """Scan all configured book directories and return the list of files."""
    dirs = directories or BOOKS_DIRS
    all_files: list[Path] = []
    for d in dirs:
        all_files.extend(scan_directory(d))
    logger.info(f"Found {len(all_files)} book files across {len(dirs)} directories")
    return all_files


def create_basic_record(file_path: Path, project_root: Path, content_sha1: str = "") -> BookRecord:
    """
    Create a BookRecord with file-level metadata.

    Callers that already hashed the file pass `content_sha1` in; hashing it
    again here meant every rebuilt record read the whole file twice.
    """
    record = BookRecord()
    record.file_path = str(file_path.relative_to(project_root))
    record.file_name = file_path.name
    record.file_type = file_path.suffix.lower().lstrip(".")
    stat = file_path.stat()
    record.size = stat.st_size
    record.mtime = stat.st_mtime

    try:
        record.content_sha1 = content_sha1 or compute_sha1(file_path)
        record.id = record.content_sha1
    except Exception as e:
        logger.error(f"Failed to compute SHA1 for {file_path}: {e}")
        record.processing_errors.append(f"SHA1 computation failed: {e}")

    record.set_defaults()
    return record
