"""
Data models for the book catalog.
"""
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime
import json


@dataclass
class BookRecord:
    """Complete book record matching the catalog schema."""

    # ─── Schema ─────────────────────────────────────────────────────────────
    _schema_version: str = "1.0"

    # ─── File Identity ──────────────────────────────────────────────────────
    id: str = ""                                    # SHA1 of file content
    file_path: str = ""                             # Relative path from project root
    file_name: str = ""                             # File name with extension
    file_type: str = ""                             # pdf | epub | mobi | other
    size: int = 0                                   # File size in bytes

    # ─── Bibliographic ──────────────────────────────────────────────────────
    title: str = ""                                 # Cleaned display title
    original_title_meta: str = ""                   # Raw title from metadata or API
    authors: list = field(default_factory=list)      # List of authors
    publisher: str = ""                             # Publisher name
    publication_year: Optional[int] = None          # Year
    language: str = ""                              # ISO 639-1 code
    page_count: Optional[int] = None                # Total pages
    isbn_10: str = ""                               # ISBN-10
    isbn_13: str = ""                               # ISBN-13

    # ─── Content & Discovery ────────────────────────────────────────────────
    description: str = ""                           # Human-readable description
    summary: str = ""                               # Auto-generated short summary
    themes: list = field(default_factory=list)       # High-level concepts
    categories: list = field(default_factory=list)   # Broad classification labels
    keywords: list = field(default_factory=list)     # Searchable terms

    # ─── Assets & Text ──────────────────────────────────────────────────────
    cover_path: str = ""                            # Path to cover image
    text_excerpt: str = ""                          # First ~2 pages of clean text

    # ─── Embeddings ─────────────────────────────────────────────────────────
    embedding: list = field(default_factory=list)           # Content embedding
    metadata_embedding: list = field(default_factory=list)  # Metadata embedding

    # ─── Processing Flags ───────────────────────────────────────────────────
    has_text: bool = True                           # text-based or image-only
    ocr_required: bool = False                      # OCR needed
    api_sources: list = field(default_factory=list)  # APIs used to enrich

    # ─── Library / User ─────────────────────────────────────────────────────
    date_added: str = ""                            # ISO 8601
    last_opened: Optional[str] = None               # ISO 8601
    reading_status: str = "not_started"             # not_started|in_progress|finished|abandoned
    progress_percent: float = 0.0                   # 0–100
    user_rating: Optional[float] = None             # 0–5
    user_tags: list = field(default_factory=list)    # Personal tags
    favorite: bool = False                          # Quick-access bookmark

    # ─── Housekeeping ───────────────────────────────────────────────────────
    duplicate_of: Optional[str] = None              # ID of canonical copy
    processing_errors: list = field(default_factory=list)  # Any errors during processing
    last_processed: str = ""                        # When this record was last updated

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "BookRecord":
        """Create a BookRecord from a dictionary."""
        # Filter out keys that don't exist in the dataclass
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def set_defaults(self):
        """Set default values for empty fields."""
        if not self.date_added:
            self.date_added = datetime.now().isoformat()
        if not self.last_processed:
            self.last_processed = datetime.now().isoformat()
