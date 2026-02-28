# Book Catalog Enrichment Pipeline
"""
A comprehensive pipeline for building an enriched book catalog from local PDF/EPUB files.

Modules:
    config           - Configuration and paths
    models           - Data models (BookRecord schema)
    scanner          - File scanning, SHA1, basic metadata
    title_parser     - Clean/parse titles from filenames
    pdf_extractor    - PDF metadata & text extraction
    epub_extractor   - EPUB metadata & text extraction
    ocr_extractor    - OCR for image-based PDFs (pytesseract + pdf2image)
    isbn_extractor   - ISBN extraction from text content
    api_enricher     - OpenLibrary + Google Books API enrichment
    llm_enricher     - LLM-powered summaries & themes (Ollama)
    cover_scraper    - Playwright-based cover image scraping
    theme_analyzer   - Extract themes/categories from text content
    embeddings       - Generate vector embeddings for semantic search
    duplicate_detector - Find duplicate books
    reading_tracker  - Track reading progress via filesystem metadata
    watcher          - Incremental folder watching with watchdog
    database         - JSON database management
    pipeline         - Orchestrate the full enrichment pipeline
"""

__version__ = "2.0.0"
