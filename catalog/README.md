# 📚 Book Catalog Enrichment Pipeline

A comprehensive Python pipeline for building an enriched metadata catalog from local PDF/EPUB book collections.

## Features

- **File Scanning** - Discovers all PDF/EPUB files, computes SHA1 checksums
- **Smart Title Parsing** - Cleans book titles from messy filenames (libgen, z-lib, dokumen.pub patterns)
- **PDF/EPUB Extraction** - Extracts metadata, text content, and cover images from files
- **API Enrichment** - Fetches rich metadata from OpenLibrary and Google Books APIs
- **Theme Analysis** - Detects broad categories, themes, and keywords from content
- **Duplicate Detection** - Finds duplicates by SHA1, ISBN, and fuzzy title matching
- **Vector Embeddings** - Optional embedding generation for semantic search
- **JSON Catalog** - Persistent catalog database with search and export

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Quick test (5 books, no API calls)
python build_catalog.py --test

# Full pipeline with API enrichment
python build_catalog.py

# View statistics
python build_catalog.py --stats

# Search catalog
python build_catalog.py --search "machine learning"
```

## Usage

```bash
# Process only EPUBs
python build_catalog.py --type epub

# Process first 20 books
python build_catalog.py --max 20

# Skip API calls (file metadata only)
python build_catalog.py --no-api

# Force reprocess everything
python build_catalog.py --force

# Include vector embeddings
python build_catalog.py --embed

# Export to CSV
python build_catalog.py --export-csv

# Verbose logging
python build_catalog.py -v
```

## Pipeline Stages

| Stage | Description |
|-------|-------------|
| 1. **SCAN** | Discover files, compute SHA1, capture file metadata |
| 2. **PARSE** | Clean/parse titles, authors, publishers from filenames |
| 3. **EXTRACT** | Extract metadata & text from PDF/EPUB content |
| 4. **ENRICH** | Fetch metadata from OpenLibrary & Google Books APIs |
| 5. **ANALYZE** | Detect themes, categories, keywords from content |
| 6. **EMBED** | Generate vector embeddings (optional) |
| 7. **DEDUPE** | Detect and mark duplicate books |
| 8. **SAVE** | Persist catalog to JSON database |

## Project Structure

```
books/
├── catalog/                    # Pipeline package
│   ├── __init__.py
│   ├── config.py              # Configuration & paths
│   ├── models.py              # BookRecord data model
│   ├── scanner.py             # File discovery & SHA1
│   ├── title_parser.py        # Filename → clean title
│   ├── pdf_extractor.py       # PDF metadata & text extraction
│   ├── epub_extractor.py      # EPUB metadata & text extraction
│   ├── api_enricher.py        # OpenLibrary & Google Books APIs
│   ├── theme_analyzer.py      # Theme/category detection
│   ├── embeddings.py          # Vector embedding generation
│   ├── duplicate_detector.py  # Duplicate detection
│   ├── database.py            # JSON catalog management
│   └── pipeline.py            # Pipeline orchestrator
├── data/
│   ├── catalog.json           # Generated catalog (output)
│   ├── catalog.csv            # CSV export (optional)
│   ├── api_cache.json         # API response cache
│   ├── covers/                # Extracted/downloaded cover images
│   └── text_excerpts/         # (future) extracted text files
├── epubs/                     # Your EPUB files
├── pdfs/                      # Your PDF files
├── build_catalog.py           # Main entry point
├── requirements.txt           # Python dependencies
└── README.md
```

## Catalog Schema

Each book record contains:

- **File Identity**: SHA1 ID, file path, name, type, size
- **Bibliographic**: Title, authors, publisher, year, language, page count, ISBN
- **Content & Discovery**: Description, summary, themes, categories, keywords
- **Assets**: Cover image path, text excerpt (~2 pages)
- **Embeddings**: Content and metadata vector embeddings
- **Processing Flags**: has_text, ocr_required, api_sources
- **User Fields**: reading_status, progress, rating, tags, favorite
- **Housekeeping**: duplicate_of, processing_errors, timestamps

## Handling Challenges

### Messy Filenames
The title parser handles patterns from libgen, z-lib, dokumen.pub, PDFDrive, etc. It strips source prefixes, extracts authors/publishers/years, and cleans titles.

### Missing Metadata
Multiple enrichment layers: filename parsing → file metadata → API enrichment (OpenLibrary → Google Books fallback)

### Image-based/Scanned PDFs
Detected automatically by checking if text extraction yields less than 100 characters. Marked with `has_text=false` and `ocr_required=true` for future OCR processing.

### Duplicates
Detected by three methods:
1. Identical SHA1 hash (exact file copies)
2. Matching ISBN
3. Fuzzy title matching (>85% similarity)

The canonical copy is chosen based on metadata completeness, text availability, and file size.

## Configuration

Edit `catalog/config.py` to customize:
- Book directories
- API rate limits
- Text extraction limits
- Duplicate detection thresholds
- Embedding model

## Optional: Google Books API Key

For higher API rate limits, set:
```bash
export GOOGLE_BOOKS_API_KEY="your-key-here"
```

## Future: Web App

The catalog JSON is designed to power a web app with:
- Smart search (text, themes, metadata, embeddings)
- Sort and filter system
- Individual book pages with similar books
- Reading view with cross-catalog comparison
