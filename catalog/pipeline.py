"""
Pipeline orchestrator.

Stage order is unchanged from the original design; what flows between the
stages is not. Instead of mutating one flat record, each stage contributes
*sourced* values, and API results must pass a verification gate before they are
allowed anywhere near the record.

    scan → parse → extract → ocr → identify → enrich → analyze → llm → embed
                                                                       │
                              covers → reading progress → dedupe → reconcile → save

Resumability: every stage carries a version. A stage runs when its version is
newer than the version stored on the record, or when the file's content hash
changed, or when `--force` is given. Everything else is skipped, which makes
re-running cheap and makes "re-run just the LLM stage" a one-line config change
instead of `--force`.

Invalidation is the delicate half of that. Two rules keep a partial re-run from
silently destroying data:

* a stale stage drags its *dependents* along (`STAGE_DEPENDS_ON`), so `analyze`
  cannot keep categories derived from a description `enrich` has replaced;
* a re-running stage first withdraws the values it previously wrote
  (`STAGE_SOURCES` / `STAGE_FIELDS`), so a stale value cannot outrank the fresh
  one through `SOURCE_RANK`. Output written by a stage that is *not* re-running
  is left alone — which is why `--no-api` no longer erases verified metadata.
"""
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .api_enricher import enrich_from_apis
from .config import (
    BATCH_SIZE,
    MAX_WORKERS,
    PROJECT_ROOT,
    STAGE_VERSIONS,
)
from .duplicate_detector import detect_duplicates
from .embeddings import embed_records
from .isbn_extractor import harvest_identifiers
from .models import BookRecord
from .providers import get_metrics, reset_metrics, save_cache, unhealthy_sources
from .scanner import compute_sha1, create_basic_record, scan_all_directories
from .store import CatalogStore, ProcessingLog
from .theme_analyzer import analyze_themes
from .title_parser import parse_filename

logger = logging.getLogger(__name__)

PER_BOOK_STAGES = ("parse", "extract", "ocr", "identify", "enrich", "analyze", "llm", "embed")

# These five all write the same bibliographic fields and settle conflicts by
# SOURCE_RANK, so they are invalidated as a cohort: re-running `enrich` while
# skipping `parse` would drop the filename title with nothing to restore it.
METADATA_COHORT = ("parse", "extract", "ocr", "identify", "enrich")

# stage -> stages whose output it consumes. A stale producer makes every
# consumer stale, transitively.
STAGE_DEPENDS_ON = {
    "analyze": ("extract", "ocr", "enrich"),
    "llm": ("analyze",),
    "embed": ("extract", "ocr", "enrich", "analyze"),
}

# stage -> provenance labels it writes. Re-running the stage resets every field
# currently carrying one of these labels (user-pinned fields excepted).
STAGE_SOURCES = {
    "parse": ("filename",),
    "extract": ("file_meta",),
    "ocr": ("file_meta",),
    "identify": ("front_matter", "derived"),
    "enrich": ("api_verified", "api_partial", "isbn_match"),
    "analyze": ("analyzer",),
    "llm": ("llm",),
}

# stage -> fields it owns outright, written without provenance.
STAGE_FIELDS = {
    "extract": ("text_excerpt", "front_matter", "content_sample", "has_text",
                "ocr_required", "page_count"),
    "enrich": ("api_sources", "match_score", "rejected_candidates"),
    "embed": ("embedding", "metadata_embedding"),
}

_STAGE_FLAGS = {
    "parse": "parse",
    "extract": "extract",
    "ocr": "ocr",
    "identify": "identify",
    "enrich": "enrich_api",
    "analyze": "analyze",
    "llm": "llm_enrich",
    "embed": "embed",
}


@dataclass
class PipelineConfig:
    """Single source of truth for which stages run (S3)."""

    scan: bool = True
    parse: bool = True
    extract: bool = True
    ocr: bool = True
    identify: bool = True
    enrich_api: bool = True
    analyze: bool = True
    llm_enrich: bool = False
    llm_adjudicate: bool = True        # only used when llm_enrich is on
    embed: bool = False
    cover_scrape: bool = False
    reading_progress: bool = False     # one `mdls` subprocess per book; opt in
    dedupe: bool = True
    reconcile_deletions: bool = True

    force_reprocess: bool = False
    max_books: Optional[int] = None
    file_types: Optional[set] = None
    only: Optional[list] = None         # path substring(s); a file matching any is processed
    workers: int = MAX_WORKERS
    export_json: bool = False
    verify_sources: bool = False
    progress_callback: Optional[Callable[[int, int, str], None]] = field(
        default=None, repr=False
    )

    def stage_enabled(self, name: str) -> bool:
        flag = _STAGE_FLAGS.get(name)
        return bool(flag and getattr(self, flag))


class Pipeline:
    """Main catalog enrichment pipeline."""

    def __init__(self, config: PipelineConfig = None, store: CatalogStore = None):
        self.config = config or PipelineConfig()
        self.store = store or CatalogStore()
        self.log = ProcessingLog()
        self._lock = threading.Lock()
        self._llm_ready: Optional[bool] = None
        self._touched: list[BookRecord] = []      # records this run wrote
        self._pending_embed: list[BookRecord] = []
        self.stats = {
            "started": datetime.now().isoformat(),
            "files_found": 0,
            "files_processed": 0,
            "files_skipped": 0,
            "api_enriched": 0,
            "api_accepted": 0,
            "api_partial": 0,
            "api_rejected": 0,
            "api_no_evidence": 0,
            "ocr_processed": 0,
            "isbn_extracted": 0,
            "llm_enriched": 0,
            "covers_scraped": 0,
            "duplicates_found": 0,
            "needs_review": 0,
            "missing_files": 0,
            "errors": 0,
            "stages_completed": [],
        }

    # ── Run ──────────────────────────────────────────────────────────────────

    def plan(self) -> dict:
        """
        What a run would do, without writing anything.

        Answers "I bumped a stage version — what is that about to change?"
        before it changes it. Uses size+mtime rather than hashing, so it is
        cheap enough to run on the whole library.
        """
        files = self._stage_scan() if self.config.scan else []
        per_stage: dict[str, int] = {s: 0 for s in PER_BOOK_STAGES}
        new_files = 0
        stale_records = 0

        for file_path in files:
            existing = self.store.get_by_path(str(file_path.relative_to(PROJECT_ROOT)))
            stat = file_path.stat()
            unchanged = bool(
                existing and existing.content_sha1
                and existing.size == stat.st_size
                and abs((existing.mtime or 0) - stat.st_mtime) < 1.0
            )
            outdated = self._outdated_stages(existing, unchanged)
            if existing is None:
                new_files += 1
            elif outdated:
                stale_records += 1
            for stage in outdated:
                per_stage[stage] += 1

        return {
            "files_found": len(files),
            "new_files": new_files,
            "stale_records": stale_records,
            "up_to_date": len(files) - new_files - stale_records,
            "per_stage": {s: n for s, n in per_stage.items() if n},
        }

    def run(self, max_books: Optional[int] = None, **overrides) -> dict:
        """
        Run the pipeline. Returns a stats dict.

        `max_books` is accepted here as well as on the config because the web
        UI calls `pipeline.run(max_books=…)` — which used to raise TypeError on
        every invocation and be swallowed by a bare `except`.
        """
        if max_books is not None:
            self.config.max_books = max_books
        for key, value in overrides.items():
            if hasattr(self.config, key) and value is not None:
                setattr(self.config, key, value)

        logger.info("=" * 60)
        logger.info("BOOK CATALOG ENRICHMENT PIPELINE")
        logger.info("=" * 60)
        start_time = time.time()
        reset_metrics()
        interrupted = False

        if self.config.verify_sources:
            self._verify_sources()

        try:
            files = self._stage_scan() if self.config.scan else []
            self._process_books(files)
        except KeyboardInterrupt:
            interrupted = True
            logger.warning("\nInterrupted — finishing the closing stages so the catalog stays consistent...")
        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            self.stats["errors"] += 1
        finally:
            # Dedupe, reconciliation and save always run: an interrupted run
            # used to leave the catalog un-deduplicated and the app stale.
            try:
                self._stage_embed_batch()
                if self.config.cover_scrape:
                    self._stage_cover_scrape()
                if self.config.reading_progress:
                    self._stage_reading_progress()
                if self.config.dedupe:
                    self._stage_dedupe()
                if self.config.reconcile_deletions and self.config.scan and not self.config.only:
                    self._stage_reconcile()
                self._stage_save()
            except Exception as e:
                logger.error(f"Closing stages failed: {e}", exc_info=True)
                self.stats["errors"] += 1

        self.stats["elapsed_seconds"] = round(time.time() - start_time, 1)
        self.stats["total_in_catalog"] = self.store.count()
        self.stats["needs_review"] = len(self.store.needs_review())
        self.stats["provider_metrics"] = get_metrics()
        self.stats["unhealthy_sources"] = unhealthy_sources()
        self.stats["interrupted"] = interrupted

        self.log.log("pipeline_interrupted" if interrupted else "pipeline_complete", self.stats)
        self.log.save()
        self._print_summary()
        return self.stats

    # ── Stage 1: scan ────────────────────────────────────────────────────────

    def _stage_scan(self) -> list[Path]:
        logger.info("\n📂 Stage 1: SCANNING for book files...")
        files = scan_all_directories()

        if self.config.file_types:
            wanted = {t.lower().lstrip(".") for t in self.config.file_types}
            files = [f for f in files if f.suffix.lower().lstrip(".") in wanted]
        if self.config.only:
            needles = self.config.only
            if isinstance(needles, str):
                needles = [needles]
            needles = [n.lower() for n in needles]
            files = [f for f in files if any(n in str(f).lower() for n in needles)]
        if self.config.max_books:
            files = files[: self.config.max_books]

        self.stats["files_found"] = len(files)
        self.stats["stages_completed"].append("scan")
        logger.info(f"   Found {len(files)} book files")
        return files

    # ── Stages 2–6: per book ─────────────────────────────────────────────────

    def _process_books(self, files: list[Path]):
        total = len(files)
        if not total:
            return

        workers = max(1, int(self.config.workers or 1))
        done = 0
        logger.info(f"\n📖 Processing {total} books with {workers} worker(s)...")

        def _handle(file_path: Path):
            return file_path, self._process_single_book(file_path)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_handle, f): f for f in files}
            try:
                for future in as_completed(futures):
                    file_path = futures[future]
                    try:
                        _, record = future.result()
                        if record is not None:
                            self.store.upsert(record)
                            with self._lock:
                                self._touched.append(record)
                                self.stats["files_processed"] += 1
                    except Exception as e:
                        logger.error(f"   ❌ Failed to process {file_path.name}: {e}")
                        with self._lock:
                            self.stats["errors"] += 1
                    finally:
                        done += 1
                        self._report_progress(done, total, file_path.name)
            except KeyboardInterrupt:
                for future in futures:
                    future.cancel()
                raise

        save_cache()

    def _report_progress(self, done: int, total: int, name: str):
        if self.config.progress_callback:
            try:
                self.config.progress_callback(done, total, name)
            except Exception:
                pass
        if done % BATCH_SIZE == 0 or done == total:
            logger.info(f"   … {done}/{total} books processed")

    def _outdated_stages(self, record: Optional[BookRecord], content_unchanged: bool) -> set[str]:
        """
        Stages that must run for this record.

        A stage is stale when its version moved on. Staleness then spreads two
        ways: across the metadata cohort (they share fields) and down the
        dependency graph (a consumer cannot keep output derived from a producer
        that is about to change).
        """
        enabled = {s for s in PER_BOOK_STAGES if self.config.stage_enabled(s)}
        if record is None or not content_unchanged or self.config.force_reprocess:
            return enabled

        outdated = {
            s for s in enabled
            if not record.stage_is_current(s, STAGE_VERSIONS[s])
        }
        if not outdated:
            return outdated

        if outdated & set(METADATA_COHORT):
            outdated |= enabled & set(METADATA_COHORT)

        # Fixed point: PER_BOOK_STAGES is topologically ordered, but iterate
        # anyway so the graph can be edited without ordering assumptions.
        while True:
            grown = outdated | {
                stage for stage in enabled
                if outdated & set(STAGE_DEPENDS_ON.get(stage, ()))
            }
            if grown == outdated:
                return outdated
            outdated = grown

    def _process_single_book(self, file_path: Path) -> Optional[BookRecord]:
        rel_path = str(file_path.relative_to(PROJECT_ROOT))
        existing = self.store.get_by_path(rel_path)
        stat = file_path.stat()

        # Cheap change detection: size + mtime, hash only when they differ.
        if (existing and existing.content_sha1
                and existing.size == stat.st_size
                and abs((existing.mtime or 0) - stat.st_mtime) < 1.0):
            content_sha1 = existing.content_sha1
        else:
            content_sha1 = compute_sha1(file_path)
        content_unchanged = bool(existing and existing.content_sha1 == content_sha1)

        outdated = self._outdated_stages(existing, content_unchanged)
        if existing and not outdated:
            with self._lock:
                self.stats["files_skipped"] += 1
            if existing.status != "active":
                existing.status = "active"
                return existing
            return None

        record = self._prepare_record(file_path, existing, content_sha1, content_unchanged)
        self._invalidate(record, outdated)
        self._run_book_stages(record, file_path, outdated)
        return record

    def _prepare_record(
        self,
        file_path: Path,
        existing: Optional[BookRecord],
        content_sha1: str,
        content_unchanged: bool,
    ) -> BookRecord:
        """
        Build the record a run will work on.

        The record is only rebuilt from the file when it is new or when the
        bytes changed (the id moves with them). Otherwise the stored record is
        carried forward and `_invalidate` withdraws just the stale stages'
        output — rebuilding wholesale used to delete categories, themes and LLM
        summaries on any local stage-version bump, and `--force` without
        `--llm` used to delete every generated summary in the catalog.
        """
        if existing is not None and content_unchanged:
            existing.status = "active"
            existing.size = file_path.stat().st_size
            existing.mtime = file_path.stat().st_mtime
            return existing

        record = create_basic_record(file_path, PROJECT_ROOT, content_sha1=content_sha1)
        if existing is None:
            return record

        # New bytes: everything derived from the old content is void, but the
        # library-level facts and an already-downloaded cover still hold.
        record.date_added = existing.date_added or record.date_added
        if existing.cover_path and (PROJECT_ROOT / existing.cover_path).exists():
            record.cover_path = existing.cover_path
            entry = existing.field_sources.get("cover_path")
            if entry:
                record.field_sources["cover_path"] = entry
        return record

    def _invalidate(self, record: BookRecord, outdated: set[str]):
        """Withdraw the output of every stage that is about to re-run."""
        if not outdated:
            return
        record.processing_errors = []
        for stage in outdated:
            record.reset_fields_from(STAGE_SOURCES.get(stage, ()))
            for name in STAGE_FIELDS.get(stage, ()):
                record.reset_field(name)
        # `enrich` owns the review queue; clearing it there meant a --no-api run
        # could never retire a stale flag.
        if outdated & set(METADATA_COHORT):
            record.clear_review()

    def _run_book_stages(self, record: BookRecord, file_path: Path, outdated: set[str]):
        for name in PER_BOOK_STAGES:
            if name not in outdated:
                continue
            handler = getattr(self, f"_stage_{name}")
            try:
                handler(record, file_path)
                if name != "embed":      # marked by the deferred batch instead
                    record.mark_stage(name, STAGE_VERSIONS[name])
            except Exception as e:
                logger.debug(f"   stage '{name}' failed for {file_path.name}: {e}")
                record.processing_errors.append(f"{name} failed: {e}")
                with self._lock:
                    self.stats["errors"] += 1

    # ── Per-book stages ──────────────────────────────────────────────────────

    def _stage_parse(self, record: BookRecord, file_path: Path):
        parsed = parse_filename(file_path.name)
        record.set_field("title", parsed["title"], "filename", 0.4)
        if parsed["authors"]:
            record.set_field("authors", parsed["authors"], "filename", 0.4)
        if parsed["publisher"]:
            record.set_field("publisher", parsed["publisher"], "filename", 0.4)
        if parsed["publication_year"]:
            record.set_field("publication_year", parsed["publication_year"], "filename", 0.4)
        if parsed["isbn_13"]:
            record.set_field("isbn_13", parsed["isbn_13"], "filename", 0.9)
        if parsed["isbn_10"]:
            record.set_field("isbn_10", parsed["isbn_10"], "filename", 0.9)
        for sid in parsed["source_ids"]:
            if sid not in record.source_ids:
                record.source_ids.append(sid)

    def _stage_extract(self, record: BookRecord, file_path: Path):
        if record.file_type == "pdf":
            from .pdf_extractor import extract_pdf_metadata
            extract_pdf_metadata(file_path, record)
        elif record.file_type == "epub":
            from .epub_extractor import extract_epub_metadata
            extract_epub_metadata(file_path, record)

    def _stage_ocr(self, record: BookRecord, file_path: Path):
        if not record.ocr_required or record.file_type != "pdf":
            return
        from .ocr_extractor import is_available as ocr_available, ocr_pdf
        if not ocr_available():
            logger.debug("OCR not available (tesseract/poppler not installed)")
            return
        ocr_pdf(file_path, record)
        with self._lock:
            self.stats["ocr_processed"] += 1

    def _stage_identify(self, record: BookRecord, file_path: Path):
        before = (record.isbn_13, record.isbn_10)
        harvest_identifiers(record)
        if (record.isbn_13, record.isbn_10) != before:
            with self._lock:
                self.stats["isbn_extracted"] += 1

        # Title-page evidence rescues a record whose filename says nothing. It
        # is always collected as *evidence* for the gate; it only becomes the
        # displayed title when the filename gave us nothing usable — a journal
        # header on page 1 must not displace a perfectly good filename title.
        if not record.front_matter:
            return
        from .text_utils import parse_front_matter
        front = parse_front_matter(record.front_matter, hint=record.title)

        filename_title_is_weak = (
            record.field_source("title") in ("", "filename")
            and len(re.findall(r"[^\W\d_]+", record.title or "", re.UNICODE)) < 2
        )
        if front.get("title") and len(front["title"]) >= 5 and filename_title_is_weak:
            record.set_field("title", front["title"], "front_matter", 0.5)
            if front.get("subtitle"):
                record.set_field("subtitle", front["subtitle"], "front_matter", 0.45)
        if front.get("authors") and not record.authors:
            record.set_field("authors", front["authors"], "front_matter", 0.5)
        if front.get("publisher") and not record.publisher:
            record.set_field("publisher", front["publisher"], "front_matter", 0.45)

    def _stage_enrich(self, record: BookRecord, file_path: Path):
        adjudicator = None
        if self.config.llm_enrich and self.config.llm_adjudicate and self._llm_available():
            from .llm_enricher import adjudicate_match
            adjudicator = adjudicate_match

        result = enrich_from_apis(record, adjudicator=adjudicator)
        with self._lock:
            if record.api_sources:
                self.stats["api_enriched"] += 1
            verdict = result.get("verdict")
            if verdict == "accept":
                self.stats["api_accepted"] += 1
            elif verdict == "partial":
                self.stats["api_partial"] += 1
            elif result.get("reason", "").startswith("insufficient evidence"):
                self.stats["api_no_evidence"] += 1
            else:
                self.stats["api_rejected"] += 1

        if not record.title:
            record.flag_review("no title could be established")

    def _stage_analyze(self, record: BookRecord, file_path: Path):
        analyze_themes(record)

    def _stage_llm(self, record: BookRecord, file_path: Path):
        if not self._llm_available():
            return
        from .llm_enricher import generate_llm_description, generate_llm_summary
        generate_llm_summary(record)
        if not record.description or len(record.description) < 50:
            generate_llm_description(record)
        with self._lock:
            self.stats["llm_enriched"] += 1

    def _stage_embed(self, record: BookRecord, file_path: Path):
        # Deferred: encoding one record at a time is 10-50x slower than a batch.
        with self._lock:
            self._pending_embed.append(record)

    def _stage_embed_batch(self):
        with self._lock:
            pending, self._pending_embed = self._pending_embed, []
        if not pending:
            return
        logger.info(f"\n🧮 EMBEDDING {len(pending)} books...")
        embed_records(pending)

        import numpy as np
        for record in pending:
            if not (record.embedding or record.metadata_embedding):
                continue
            try:
                content = (np.array(record.embedding, dtype=np.float32).tobytes()
                           if record.embedding else None)
                meta = (np.array(record.metadata_embedding, dtype=np.float32).tobytes()
                        if record.metadata_embedding else None)
                self.store.store_embedding(record.id, content, meta)
                record.mark_stage("embed", STAGE_VERSIONS["embed"])
                self.store.upsert(record)
            except Exception as e:
                logger.debug(f"Failed to store embedding for {record.file_name}: {e}")
        self.stats["stages_completed"].append("embed")

    def _llm_available(self) -> bool:
        if self._llm_ready is None:
            from .llm_enricher import is_available
            self._llm_ready = is_available()
            if not self._llm_ready:
                logger.warning("LLM enrichment requested but Ollama is not reachable — skipping")
        return self._llm_ready

    # ── Closing stages ───────────────────────────────────────────────────────

    def _scoped_records(self) -> list[BookRecord]:
        """
        Records the closing stages should look at.

        A narrowed run (`--only`, `--max`, `--type`) has no business walking the
        whole catalog: it used to `mdls` every book on disk to satisfy a
        one-file request.
        """
        narrowed = bool(self.config.only or self.config.max_books or self.config.file_types)
        if narrowed:
            return list(self._touched)
        return self.store.all_records()

    def _stage_cover_scrape(self):
        records = [r for r in self._scoped_records() if not r.cover_path]
        if not records:
            logger.info("\n🖼️  All books already have covers")
            return
        try:
            from .cover_scraper import fetch_cover_playwright, is_available as pw_available
            if not pw_available():
                logger.info("\n🖼️  Playwright not installed, skipping cover scraping")
                return
        except ImportError:
            return

        from .config import COVER_SCRAPER_HEADLESS
        logger.info(f"\n🖼️  SCRAPING covers for {len(records)} books...")
        for record in records:
            try:
                fetch_cover_playwright(record, headless=COVER_SCRAPER_HEADLESS)
                if record.cover_path:
                    self.stats["covers_scraped"] += 1
                    self.store.upsert(record)
            except Exception as e:
                logger.debug(f"Cover scraping failed for {record.file_name}: {e}")
        self.stats["stages_completed"].append("cover_scrape")

    def _stage_reading_progress(self):
        """
        Filesystem-derived reading hints, advanced monotonically.

        The one stage that touches a user-owned column, and the only one that
        may: `last_opened` is written by the reader on every open, while
        Spotlight only knows when the *file* was last opened on disk — usually
        older. So the stored value is the baseline and the hint may only move
        it forward. The comparison is against `user_data`, not the mirrored
        copy on the record, which is empty for a record built fresh this run.
        """
        from .reading_tracker import update_reading_progress
        logger.info("\n📖 TRACKING reading progress...")
        updated = 0
        for record in self._scoped_records():
            try:
                path = PROJECT_ROOT / record.file_path
                if not path.exists():
                    continue
                before = self.store.user_field(
                    record.id, "last_opened", record.file_path
                ) or record.last_opened
                record.last_opened = before
                update_reading_progress(record, path, known_last_opened=before)
                if record.last_opened and record.last_opened != before:
                    updated += 1
                    self.store.update_user_fields(
                        record.id,
                        {"last_opened": record.last_opened},
                        record.file_path,
                    )
            except Exception as e:
                logger.debug(f"Reading progress failed for {record.file_name}: {e}")
        self.stats["stages_completed"].append("reading_progress")
        logger.info(f"   Updated reading progress for {updated} books")

    def _stage_dedupe(self):
        """Global by design: a newly added book's twin may be anywhere in the catalog."""
        logger.info("\n🔍 DETECTING duplicates...")
        records = self.store.all_records()
        if not records:
            return
        before = {r.file_path: r.duplicate_of for r in records}
        detect_duplicates(records)
        changed = [r for r in records if before.get(r.file_path) != r.duplicate_of]
        for record in changed:
            self.store.upsert(record)
        dup_count = sum(1 for r in records if r.duplicate_of)
        self.stats["duplicates_found"] = dup_count
        self.stats["stages_completed"].append("dedupe")
        logger.info(f"   {dup_count} duplicates ({len(changed)} newly marked/cleared)")

    def _stage_reconcile(self):
        """Flag records whose files no longer exist rather than leaving phantoms."""
        missing = [
            path for path in self.store.all_paths()
            if not (PROJECT_ROOT / path).exists()
        ]
        if missing:
            self.store.mark_missing(missing)
            logger.info(f"\n🧹 Marked {len(missing)} records as missing (files deleted)")
        self.stats["missing_files"] = len(missing)
        self.stats["stages_completed"].append("reconcile")

    def _stage_save(self):
        logger.info("\n💾 SAVING catalog...")
        save_cache()
        if self.config.export_json:
            self.store.export_json()
        self.stats["stages_completed"].append("save")
        logger.info(f"   Catalog holds {self.store.count()} books")

    # ── Reporting ────────────────────────────────────────────────────────────

    def _verify_sources(self):
        from .providers import probe_sources
        logger.info("\n🔌 Probing metadata providers...")
        for name, result in probe_sources().items():
            if result.get("ok"):
                logger.info(
                    f"   ✅ {name}: HTTP {result['status_code']}, "
                    f"{result['results']} results, {result['elapsed_ms']}ms"
                )
            else:
                logger.error(f"   ❌ {name}: {result.get('error')}")

    def _print_summary(self):
        s = self.stats
        logger.info("\n" + "=" * 60)
        logger.info("PIPELINE SUMMARY")
        logger.info("=" * 60)
        logger.info(f"  Files found:      {s['files_found']}")
        logger.info(f"  Files processed:  {s['files_processed']}")
        logger.info(f"  Files skipped:    {s['files_skipped']} (already current)")
        logger.info(f"  OCR processed:    {s['ocr_processed']}")
        logger.info(f"  ISBNs extracted:  {s['isbn_extracted']}")
        logger.info(f"  LLM enriched:     {s['llm_enriched']}")
        logger.info(f"  Covers scraped:   {s['covers_scraped']}")
        logger.info(f"  Duplicates found: {s['duplicates_found']}")
        logger.info(f"  Missing files:    {s['missing_files']}")
        logger.info(f"  Errors:           {s['errors']}")
        logger.info("")
        logger.info("  Verification gate:")
        logger.info(f"    accepted:       {s['api_accepted']}")
        logger.info(f"    borderline:     {s['api_partial']} (descriptive fields only)")
        logger.info(f"    rejected:       {s['api_rejected']}")
        logger.info(f"    no evidence:    {s['api_no_evidence']} (no ISBN, unusable title)")
        logger.info(f"    needs review:   {s['needs_review']}")
        logger.info("")
        logger.info("  Provider health:")
        for source, counts in (s.get("provider_metrics") or {}).items():
            attempted = counts.get("attempted", 0)
            errors = counts.get("error", 0)
            rate = f"{errors / attempted:.0%}" if attempted else "n/a"
            logger.info(
                f"    {source:<14} attempted={attempted:<5} ok={counts.get('ok', 0):<5} "
                f"not_found={counts.get('not_found', 0):<5} error={errors:<4} "
                f"throttled={counts.get('cooldown', 0):<5} "
                f"cached={counts.get('cached', 0):<5} error_rate={rate}"
            )
        for source in s.get("unhealthy_sources") or []:
            logger.error(f"  ⚠️  SOURCE UNHEALTHY: {source} — check connectivity/rate limits")
        logger.info(f"  Total in catalog: {s.get('total_in_catalog', 0)}")
        logger.info(f"  Time elapsed:     {s.get('elapsed_seconds', 0)}s")
        logger.info("=" * 60)


def run_pipeline(config: PipelineConfig = None, **kwargs) -> dict:
    """Convenience wrapper: build a config from kwargs and run."""
    if config is None:
        config = PipelineConfig(**kwargs)
    return Pipeline(config).run()
