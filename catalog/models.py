"""
Data models for the book catalog.

The central rule of the schema: a field may only
be written together with its source and confidence. `BookRecord.set_field` is
the only sanctioned way to write a bibliographic field, and it refuses to let a
weaker source overwrite a stronger one — which is what makes "a bad API match
silently replaces good local metadata" structurally impossible rather than
individually patched.
"""
from dataclasses import MISSING, dataclass, field, asdict
from datetime import datetime
from typing import Any, Iterable, Optional
import json


# ─── Source ranking ─────────────────────────────────────────────────────────────
# Higher rank wins regardless of confidence; ties are broken by confidence.
SOURCE_RANK: dict[str, int] = {
    "user": 100,          # a human confirmed it — never overwrite
    "isbn_match": 90,     # API record reached via a verified ISBN
    "api_verified": 80,   # API record that passed the verification gate
    "file_meta": 60,      # embedded PDF/EPUB metadata (non-junk)
    "front_matter": 50,   # parsed from the title page
    "filename": 40,       # parsed from the file name
    "api_partial": 30,    # borderline API match: descriptive fields only
    "llm": 25,            # local LLM — reads the text, so it beats keyword counting
    "analyzer": 20,       # local keyword/theme analysis
    "derived": 10,        # computed from other fields (e.g. ISBN-10 ↔ ISBN-13)
    "unknown": 0,
}

# Fields that establish identity. A borderline (partial) match may never write
# these — a wrong identifier corrupts dedupe and every later lookup.
IDENTITY_FIELDS = {"title", "authors", "isbn_10", "isbn_13", "publication_year", "publisher"}


def source_rank(source: str) -> int:
    return SOURCE_RANK.get(source, 0)


# How much each identity-bearing field contributes to `identity_confidence`.
# Renormalised over the fields actually present, so a record with no author is
# not silently capped — the same trick `evidence.score_candidate` uses.
IDENTITY_WEIGHTS = {"title": 0.5, "authors": 0.25, "isbn": 0.25}


def _field(record, name):
    """Read `name` off a BookRecord or off a plain row dict (the server's)."""
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


def identity_confidence(record) -> float:
    """
    How sure we are about *which book this is* — from provenance alone.

    `match_score` cannot answer this. It is the score of an *API candidate*, so
    it is `None` for a record identified perfectly from its own embedded
    metadata or from a validated ISBN in the file. Wherever "lowest confidence
    first" was wanted, treating a missing score as -1 sorted exactly those
    records below a 0.20 rubbish match.

    Nothing is stored: this is computed from `field_sources`, which already
    holds a per-field `{source, confidence}`. A rollup column would only drift
    from it the moment a human pins a correction.

    Accepts a `BookRecord` or a row dict; both expose the same field names.
    """
    if not _field(record, "title"):
        return 0.0                     # "unknown" is a valid state, and it scores 0

    sources = _field(record, "field_sources") or {}

    def conf(name: str) -> float:
        return float((sources.get(name) or {}).get("confidence") or 0.0)

    parts = [(IDENTITY_WEIGHTS["title"], conf("title"))]
    if _field(record, "authors"):
        parts.append((IDENTITY_WEIGHTS["authors"], conf("authors")))
    isbn = max(
        conf("isbn_13") if _field(record, "isbn_13") else 0.0,
        conf("isbn_10") if _field(record, "isbn_10") else 0.0,
    )
    if isbn:
        parts.append((IDENTITY_WEIGHTS["isbn"], isbn))

    total = sum(weight for weight, _ in parts)
    if total <= 0:
        return 0.0
    return round(sum(weight * value for weight, value in parts) / total, 3)


@dataclass
class BookRecord:
    """Complete book record matching the catalog schema."""

    # ─── Schema ─────────────────────────────────────────────────────────────
    _schema_version: str = "2.0"

    # ─── File Identity ──────────────────────────────────────────────────────
    id: str = ""                                    # stable record id
    content_sha1: str = ""                          # SHA1 of file bytes
    file_path: str = ""                             # Relative path from project root
    file_name: str = ""                             # File name with extension
    file_type: str = ""                             # pdf | epub | mobi | other
    size: int = 0                                   # File size in bytes
    mtime: float = 0.0                              # File modification time
    status: str = "active"                          # active | missing

    # ─── Bibliographic ──────────────────────────────────────────────────────
    title: str = ""                                 # Cleaned display title
    subtitle: str = ""
    original_title_meta: str = ""                   # Raw title embedded in the file
    authors: list = field(default_factory=list)
    publisher: str = ""
    publication_year: Optional[int] = None
    language: str = ""                              # ISO 639-1 code
    script: str = ""                                # latin | arabic | ... (detected)
    page_count: Optional[int] = None
    isbn_10: str = ""
    isbn_13: str = ""
    source_ids: list = field(default_factory=list)  # e.g. ["ia:2015.168284", "ol:/works/OL1W"]

    # ─── Content & Discovery ────────────────────────────────────────────────
    description: str = ""
    summary: str = ""
    themes: list = field(default_factory=list)
    categories: list = field(default_factory=list)   # controlled vocabulary only
    subjects_raw: list = field(default_factory=list)  # external subjects, searchable
    keywords: list = field(default_factory=list)

    # ─── Assets & Text ──────────────────────────────────────────────────────
    cover_path: str = ""
    text_excerpt: str = ""                          # reader preview (first pages)
    front_matter: str = ""                          # title/copyright pages — evidence
    content_sample: str = ""                        # prose past the TOC — embed this

    # ─── Embeddings ─────────────────────────────────────────────────────────
    embedding: list = field(default_factory=list)
    metadata_embedding: list = field(default_factory=list)

    # ─── Provenance & Review ────────────────────────────────────────────────
    field_sources: dict = field(default_factory=dict)  # field -> {source, confidence, at}
    needs_review: bool = False
    review_reasons: list = field(default_factory=list)
    match_score: Optional[float] = None             # best accepted candidate score
    rejected_candidates: list = field(default_factory=list)

    # ─── Processing Flags ───────────────────────────────────────────────────
    has_text: bool = True
    ocr_required: bool = False
    api_sources: list = field(default_factory=list)
    stage_versions: dict = field(default_factory=dict)

    # ─── Library / User ─────────────────────────────────────────────────────
    date_added: str = ""
    last_opened: Optional[str] = None
    reading_status: str = "not_started"
    progress_percent: float = 0.0
    # Opaque resume token written by whichever reader opened the book: an EPUB
    # CFI, or a PDF page number as a string.
    reader_position: str = ""
    user_rating: Optional[float] = None
    user_tags: list = field(default_factory=list)
    favorite: bool = False

    # ─── Housekeeping ───────────────────────────────────────────────────────
    duplicate_of: Optional[str] = None
    processing_errors: list = field(default_factory=list)
    last_processed: str = ""

    # ── Provenance-aware writes ─────────────────────────────────────────────

    def set_field(
        self,
        name: str,
        value: Any,
        source: str,
        confidence: Optional[float] = None,
        allow_equal: bool = False,
    ) -> bool:
        """
        Write `name` only if `source` outranks whatever wrote it last.

        Returns True if the value was written. Empty values are ignored, and a
        field previously written by the user is never overwritten.
        """
        if value is None or value == "" or value == [] or value == {}:
            return False

        if confidence is None:
            confidence = source_rank(source) / 100.0

        prev = self.field_sources.get(name)
        if prev:
            prev_rank = source_rank(prev.get("source", "unknown"))
            prev_conf = float(prev.get("confidence") or 0.0)
            new_rank = source_rank(source)
            if prev.get("source") == "user":
                return False
            if new_rank < prev_rank:
                return False
            if new_rank == prev_rank:
                # Same source class: only replace an empty value, a strictly
                # more confident one, or when the caller explicitly allows it.
                current = getattr(self, name, None)
                if current and confidence <= prev_conf and not allow_equal:
                    return False
        setattr(self, name, value)
        self.field_sources[name] = {
            "source": source,
            "confidence": round(float(confidence), 3),
            "at": datetime.now().isoformat(timespec="seconds"),
        }
        return True

    def field_source(self, name: str) -> str:
        return (self.field_sources.get(name) or {}).get("source", "")

    def field_confidence(self, name: str) -> float:
        return float((self.field_sources.get(name) or {}).get("confidence") or 0.0)

    def identity_confidence(self) -> float:
        """Confidence in *which book this is*, as opposed to how well described."""
        return identity_confidence(self)

    def reset_field(self, name: str) -> bool:
        """
        Return `name` to its schema default and forget its provenance.

        A user-pinned field is never reset. This is how a re-running stage
        withdraws its previous output: leaving the old value in place would let
        it outrank the fresh one through `SOURCE_RANK` and never be replaced.
        """
        if self.field_source(name) == "user":
            return False
        spec = self.__dataclass_fields__.get(name)
        if spec is None:
            return False
        if spec.default_factory is not MISSING:
            setattr(self, name, spec.default_factory())
        elif spec.default is not MISSING:
            setattr(self, name, spec.default)
        else:
            return False
        self.field_sources.pop(name, None)
        return True

    def reset_fields_from(self, sources: Iterable[str]) -> list[str]:
        """Reset every field whose current value came from one of `sources`."""
        wanted = set(sources)
        names = [
            name for name, entry in self.field_sources.items()
            if (entry or {}).get("source") in wanted
        ]
        return [name for name in names if self.reset_field(name)]

    def flag_review(self, reason: str):
        self.needs_review = True
        if reason not in self.review_reasons:
            self.review_reasons.append(reason)

    def clear_review(self):
        self.needs_review = False
        self.review_reasons = []

    def stage_is_current(self, stage: str, expected_version: int) -> bool:
        return int(self.stage_versions.get(stage, 0)) >= expected_version

    def mark_stage(self, stage: str, version: int):
        self.stage_versions[stage] = version

    # ── (de)serialisation ───────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BookRecord":
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        # Tolerate older catalogs that stored these as JSON strings.
        for key in ("field_sources", "stage_versions"):
            if isinstance(filtered.get(key), str):
                try:
                    filtered[key] = json.loads(filtered[key])
                except (json.JSONDecodeError, TypeError):
                    filtered[key] = {}
        return cls(**filtered)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def set_defaults(self):
        now = datetime.now().isoformat()
        if not self.date_added:
            self.date_added = now
        if not self.last_processed:
            self.last_processed = now
