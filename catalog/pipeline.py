"""
Pipeline orchestrator - coordinates all enrichment stages.

Pipeline stages:
1.  SCAN      - Discover files, compute SHA1, basic file metadata
2.  PARSE     - Clean/parse titles from filenames
3.  EXTRACT   - Extract metadata & text from PDF/EPUB content
3b. OCR       - OCR image-based PDFs (pytesseract + pdf2image)
3c. ISBN      - Extract ISBNs from text content
4.  ENRICH    - Fetch metadata from OpenLibrary & Google Books APIs
5.  ANALYZE   - Detect themes, categories, keywords from content
5b. LLM       - Generate LLM-powered summaries/themes (Ollama)
6.  EMBED     - Generate vector embeddings for semantic search
6b. COVERS    - Scrape missing covers via Playwright
6c. READING   - Update reading progress from filesystem metadata
7.  DEDUPE    - Detect and mark duplicates
8.  SAVE      - Persist catalog to JSON database
"""
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import PROJECT_ROOT, BATCH_SIZE
from .models import BookRecord
from .scanner import scan_all_directories, create_basic_record
from .title_parser import parse_filename
from .pdf_extractor import extract_pdf_metadata
from .epub_extractor import extract_epub_metadata
from .api_enricher import enrich_from_apis, save_cache
from .theme_analyzer import analyze_themes
from .embeddings import generate_embeddings
from .duplicate_detector import detect_duplicates
from .database import CatalogDatabase, ProcessingLog
from .isbn_extractor import extract_isbn_from_content
from .reading_tracker import update_reading_progress

logger = logging.getLogger(__name__)


class PipelineConfig:
    """Configuration for which pipeline stages to run."""
    def __init__(
        self,
        scan: bool = True,
        parse: bool = True,
        extract: bool = True,
        ocr: bool = True,            # OCR image-based PDFs
        isbn_extract: bool = True,    # Extract ISBNs from text
        enrich_api: bool = True,
        analyze: bool = True,
        llm_enrich: bool = False,     # LLM summaries (requires Ollama)
        embed: bool = False,          # Off by default (requires sentence-transformers)
        cover_scrape: bool = False,   # Playwright cover scraping
        reading_progress: bool = True, # Track reading progress
        dedupe: bool = True,
        force_reprocess: bool = False,
        max_books: Optional[int] = None,  # Limit for testing
        skip_api_for_existing: bool = True,  # Don't re-query API if already enriched
        file_types: Optional[set] = None,  # Filter by file type (e.g., {"pdf"})
    ):
        self.scan = scan
        self.parse = parse
        self.extract = extract
        self.ocr = ocr
        self.isbn_extract = isbn_extract
        self.enrich_api = enrich_api
        self.analyze = analyze
        self.llm_enrich = llm_enrich
        self.embed = embed
        self.cover_scrape = cover_scrape
        self.reading_progress = reading_progress
        self.dedupe = dedupe
        self.force_reprocess = force_reprocess
        self.max_books = max_books
        self.skip_api_for_existing = skip_api_for_existing
        self.file_types = file_types


class Pipeline:
    """Main catalog enrichment pipeline."""

    def __init__(self, config: PipelineConfig = None):
        self.config = config or PipelineConfig()
        self.db = CatalogDatabase()
        self.log = ProcessingLog()
        self.stats = {
            "started": datetime.now().isoformat(),
            "files_found": 0,
            "files_processed": 0,
            "files_skipped": 0,
            "api_enriched": 0,
            "ocr_processed": 0,
            "isbn_extracted": 0,
            "llm_enriched": 0,
            "covers_scraped": 0,
            "duplicates_found": 0,
            "errors": 0,
            "stages_completed": [],
        }

    def run(self) -> dict:
        """Run the full enrichment pipeline. Returns stats dict."""
        logger.info("=" * 60)
        logger.info("BOOK CATALOG ENRICHMENT PIPELINE")
        logger.info("=" * 60)
        start_time = time.time()

        try:
            # Stage 1: Scan
            if self.config.scan:
                files = self._stage_scan()
            else:
                files = []

            # Stage 2-6: Process each book (extract, parse, OCR, ISBN, API, analyze, LLM, embed)
            records = self._process_books(files)

            # Stage 6b: Scrape missing covers via Playwright
            if self.config.cover_scrape and records:
                self._stage_cover_scrape(records)

            # Stage 6c: Reading progress tracking
            if self.config.reading_progress and records:
                self._stage_reading_progress(records)

            # Stage 7: Deduplicate
            if self.config.dedupe and records:
                self._stage_dedupe(records)

            # Stage 8: Save
            self._stage_save()

            elapsed = time.time() - start_time
            self.stats["elapsed_seconds"] = round(elapsed, 1)
            self.stats["total_in_catalog"] = self.db.count()

            self.log.log("pipeline_complete", self.stats)
            self.log.save()

            self._print_summary()
            return self.stats

        except KeyboardInterrupt:
            logger.warning("\nPipeline interrupted by user. Saving progress...")
            self.db.save()
            save_cache()
            self.log.log("pipeline_interrupted", self.stats)
            self.log.save()
            raise
        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            self.db.save()
            save_cache()
            raise

    def _stage_scan(self) -> list[Path]:
        """Stage 1: Discover all book files."""
        logger.info("\n📂 Stage 1/8: SCANNING for book files...")
        files = scan_all_directories()

        # Apply filters
        if self.config.file_types:
            files = [
                f for f in files
                if f.suffix.lower().lstrip(".") in self.config.file_types
            ]

        if self.config.max_books:
            files = files[: self.config.max_books]

        self.stats["files_found"] = len(files)
        self.stats["stages_completed"].append("scan")
        logger.info(f"   Found {len(files)} book files")
        return files

    def _process_books(self, files: list[Path]) -> list[BookRecord]:
        """Process all discovered books through stages 2-6."""
        records = []
        total = len(files)

        for i, file_path in enumerate(files):
            # Progress reporting
            if (i + 1) % BATCH_SIZE == 0 or i == 0:
                logger.info(f"\n📖 Processing book {i + 1}/{total}: {file_path.name[:60]}...")

            try:
                record = self._process_single_book(file_path)
                if record:
                    records.append(record)
                    self.db.upsert(record)
                    self.stats["files_processed"] += 1

                    # Periodic save every 50 books
                    if (i + 1) % 50 == 0:
                        self.db.save()
                        save_cache()
                        logger.info(f"   💾 Progress saved ({i + 1}/{total})")

            except Exception as e:
                logger.error(f"   ❌ Failed to process {file_path.name}: {e}")
                self.stats["errors"] += 1

        return records

    def _process_single_book(self, file_path: Path) -> Optional[BookRecord]:
        """Process a single book through stages 2-6."""
        # Check if already processed (unless force reprocess)
        existing = self.db.get_by_path(str(file_path.relative_to(PROJECT_ROOT)))
        if existing and not self.config.force_reprocess:
            # Check if we should skip API enrichment too
            if self.config.skip_api_for_existing and existing.api_sources:
                self.stats["files_skipped"] += 1
                return existing

        # Stage 2: Create basic record + parse filename
        record = create_basic_record(file_path, PROJECT_ROOT)

        if self.config.parse:
            parsed = parse_filename(file_path.name)
            record.title = parsed["title"]
            if parsed["authors"]:
                record.authors = parsed["authors"]
            if parsed["publisher"]:
                record.publisher = parsed["publisher"]
            if parsed["publication_year"]:
                record.publication_year = parsed["publication_year"]

        # Stage 3: Extract metadata from file content
        if self.config.extract:
            if record.file_type == "pdf":
                record = extract_pdf_metadata(file_path, record)
            elif record.file_type == "epub":
                record = extract_epub_metadata(file_path, record)

        # Stage 3b: OCR for image-based PDFs
        if self.config.ocr and record.ocr_required and record.file_type == "pdf":
            try:
                from .ocr_extractor import ocr_pdf, is_available as ocr_available
                if ocr_available():
                    record = ocr_pdf(file_path, record)
                    self.stats["ocr_processed"] += 1
                else:
                    logger.debug("OCR not available (tesseract/poppler not installed)")
            except Exception as e:
                logger.debug(f"   OCR failed for {file_path.name}: {e}")
                record.processing_errors.append(f"OCR failed: {e}")

        # Stage 3c: Extract ISBNs from text content
        if self.config.isbn_extract and (not record.isbn_13 or not record.isbn_10):
            try:
                old_isbn = (record.isbn_13, record.isbn_10)
                record = extract_isbn_from_content(record)
                if (record.isbn_13, record.isbn_10) != old_isbn:
                    self.stats["isbn_extracted"] += 1
            except Exception as e:
                logger.debug(f"   ISBN extraction failed for {file_path.name}: {e}")

        # Use metadata title if our parsed title looks poor
        if record.original_title_meta and (
            not record.title
            or len(record.title) < 5
            or record.title == record.file_name
        ):
            record.title = record.original_title_meta

        # If metadata title is junk (e.g. "Microsoft Word - ..." ), try to
        # recover a better title from the text excerpt first lines
        junk_title_patterns = [
            "microsoft word", "untitled", "unknown", ".docx", ".doc",
            "converted by", "calibre", "scanned",
        ]
        if record.title and any(p in record.title.lower() for p in junk_title_patterns):
            recovered = _recover_title_from_text(record.text_excerpt)
            if recovered:
                record.original_title_meta = record.title  # preserve original junk
                record.title = recovered

        # Stage 4: API enrichment
        if self.config.enrich_api:
            try:
                enrich_from_apis(record)
                if record.api_sources:
                    self.stats["api_enriched"] += 1
            except Exception as e:
                logger.debug(f"   API enrichment failed for {file_path.name}: {e}")
                record.processing_errors.append(f"API enrichment failed: {e}")

        # Refine title: prefer API title if our parsed one is weak
        if record.original_title_meta and len(record.original_title_meta) > len(record.title):
            # Use API title if it's substantially more complete
            if len(record.original_title_meta) > len(record.title) * 1.3:
                record.title = record.original_title_meta

        # Stage 5: Theme analysis
        if self.config.analyze:
            record = analyze_themes(record)

        # Stage 5b: LLM-powered enrichment (summaries, themes, descriptions)
        if self.config.llm_enrich:
            try:
                from .llm_enricher import generate_llm_summary, generate_llm_description, is_available as llm_available
                if llm_available():
                    record = generate_llm_summary(record)
                    if not record.description or len(record.description) < 50:
                        record = generate_llm_description(record)
                    self.stats["llm_enriched"] += 1
                else:
                    logger.debug("LLM not available (Ollama not running)")
            except Exception as e:
                logger.debug(f"   LLM enrichment failed for {file_path.name}: {e}")
                record.processing_errors.append(f"LLM enrichment failed: {e}")

        # Stage 6: Embeddings
        if self.config.embed:
            record = generate_embeddings(record)

        return record

    def _stage_cover_scrape(self, records: list[BookRecord]):
        """Stage 6b: Scrape missing covers via Playwright."""
        missing_covers = [r for r in records if not r.cover_path]
        if not missing_covers:
            logger.info("\n🖼️  All books already have covers")
            return

        try:
            from .cover_scraper import fetch_cover_playwright, is_available as pw_available
            if not pw_available():
                logger.info("\n🖼️  Playwright not installed, skipping cover scraping")
                return
        except ImportError:
            return

        logger.info(f"\n🖼️  Stage 6b: SCRAPING covers for {len(missing_covers)} books...")
        for record in missing_covers:
            try:
                from .config import COVER_SCRAPER_HEADLESS
                fetch_cover_playwright(record, headless=COVER_SCRAPER_HEADLESS)
                if record.cover_path:
                    self.stats["covers_scraped"] += 1
                    self.db.upsert(record)
            except Exception as e:
                logger.debug(f"Cover scraping failed for {record.file_name}: {e}")

        self.stats["stages_completed"].append("cover_scrape")

    def _stage_reading_progress(self, records: list[BookRecord]):
        """Stage 6c: Update reading progress from filesystem metadata."""
        logger.info("\n📖 Stage 6c: TRACKING reading progress...")
        updated = 0
        for record in records:
            try:
                file_path = PROJECT_ROOT / record.file_path
                old_opened = record.last_opened
                record = update_reading_progress(record, file_path)
                if record.last_opened != old_opened:
                    updated += 1
                    self.db.upsert(record)
            except Exception as e:
                logger.debug(f"Reading progress failed for {record.file_name}: {e}")

        self.stats["stages_completed"].append("reading_progress")
        logger.info(f"   Updated reading progress for {updated} books")

    def _stage_dedupe(self, records: list[BookRecord]):
        """Stage 7: Detect duplicates."""
        logger.info("\n🔍 Stage 7/8: DETECTING duplicates...")
        records = detect_duplicates(records)
        dup_count = sum(1 for r in records if r.duplicate_of)
        self.stats["duplicates_found"] = dup_count
        self.stats["stages_completed"].append("dedupe")
        logger.info(f"   Found {dup_count} duplicates")

        # Update records in database
        for record in records:
            self.db.upsert(record)

    def _stage_save(self):
        """Stage 8: Save catalog."""
        logger.info("\n💾 Stage 8/8: SAVING catalog...")
        self.db.save()
        save_cache()
        self.stats["stages_completed"].append("save")
        logger.info(f"   Catalog saved with {self.db.count()} books")

    def _print_summary(self):
        """Print a summary of the pipeline run."""
        s = self.stats
        logger.info("\n" + "=" * 60)
        logger.info("PIPELINE SUMMARY")
        logger.info("=" * 60)
        logger.info(f"  Files found:      {s['files_found']}")
        logger.info(f"  Files processed:  {s['files_processed']}")
        logger.info(f"  Files skipped:    {s['files_skipped']}")
        logger.info(f"  API enriched:     {s['api_enriched']}")
        logger.info(f"  OCR processed:    {s['ocr_processed']}")
        logger.info(f"  ISBNs extracted:  {s['isbn_extracted']}")
        logger.info(f"  LLM enriched:     {s['llm_enriched']}")
        logger.info(f"  Covers scraped:   {s['covers_scraped']}")
        logger.info(f"  Duplicates found: {s['duplicates_found']}")
        logger.info(f"  Errors:           {s['errors']}")
        logger.info(f"  Total in catalog: {s.get('total_in_catalog', 0)}")
        logger.info(f"  Time elapsed:     {s.get('elapsed_seconds', 0)}s")
        logger.info("=" * 60)


def _recover_title_from_text(text_excerpt: str) -> str:
    """Try to extract a real title from the first lines of text."""
    import re
    if not text_excerpt:
        return ""
    lines = text_excerpt.strip().split("\n")
    for line in lines[:5]:
        line = line.strip()
        # A good title candidate: 3-80 chars, not all lowercase, not a sentence
        if (
            5 <= len(line) <= 120
            and not line.endswith(".")
            and not line.startswith("by ")
            and not line.startswith("copyright")
            and not any(w in line.lower() for w in [
                "chapter", "page", "www.", "http", "isbn", "copyright",
                "all rights", "published by", "table of contents",
            ])
        ):
            return line
    return ""


def run_pipeline(
    max_books: Optional[int] = None,
    enrich_api: bool = True,
    embed: bool = False,
    force: bool = False,
    file_types: Optional[set] = None,
    ocr: bool = True,
    llm: bool = False,
    cover_scrape: bool = False,
    reading_progress: bool = True,
) -> dict:
    """
    Convenience function to run the pipeline with common options.

    Args:
        max_books: Limit number of books to process (for testing)
        enrich_api: Whether to call external APIs
        embed: Whether to generate embeddings
        force: Force reprocess all books
        file_types: Filter by file type (e.g., {"pdf", "epub"})
        ocr: Whether to OCR image-based PDFs
        llm: Whether to use LLM for summaries/themes
        cover_scrape: Whether to scrape missing covers via Playwright
        reading_progress: Whether to track reading progress

    Returns:
        Pipeline statistics dict
    """
    config = PipelineConfig(
        enrich_api=enrich_api,
        embed=embed,
        force_reprocess=force,
        max_books=max_books,
        file_types=file_types,
        ocr=ocr,
        llm_enrich=llm,
        cover_scrape=cover_scrape,
        reading_progress=reading_progress,
    )
    pipeline = Pipeline(config)
    return pipeline.run()
