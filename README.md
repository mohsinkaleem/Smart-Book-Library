# BookShelf — Smart Book Library

A local-first web application for managing, cataloging, and exploring your personal book collection (PDFs & EPUBs). Features full-text search, AI-powered analysis, semantic similarity, and a modern responsive UI.

## Features

- **Smart Cataloging** — Automatically extracts metadata (title, authors, ISBN, language, page count) from PDF and EPUB files
- **Full-Text Search** — SQLite FTS5 with Porter stemmer for fast, typo-tolerant search across all book metadata and text
- **Semantic Search** — Sentence-transformer embeddings enable "find books like this" similarity queries
- **Reading View** — In-browser text reader with adjustable font size, paragraph formatting, and copy-to-clipboard
- **LLM Analysis** — Ollama-powered streaming analysis (summarize, explain, critique, compare) of selected text passages
- **Cover Art** — Automatic cover extraction from files and API enrichment from Open Library / Google Books
- **Dashboard** — Visual statistics with charts showing library composition by category, type, language, and reading progress
- **Dark Mode** — Full dark/light theme toggle with system preference detection
- **Responsive Grid/List Views** — Switch between grid and list layouts with sort and filter controls
- **Reading Tracker** — Mark books as not started / in progress / finished / abandoned with progress percentage

## Tech Stack

| Layer      | Technology                                            |
| ---------- | ----------------------------------------------------- |
| Backend    | Python 3.11+, FastAPI, uvicorn                        |
| Database   | SQLite (WAL mode) + FTS5 virtual table                |
| Frontend   | React 18, TypeScript, Vite 8, Tailwind CSS v4         |
| State      | TanStack Query v5, Zustand                            |
| Charts     | Recharts                                              |
| Icons      | Lucide React                                          |
| Embeddings | sentence-transformers (`all-MiniLM-L6-v2`)            |
| LLM        | Ollama (local, optional)                              |
| OCR        | Tesseract + pdf2image (optional)                      |

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ and npm
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### 1. Install Python Dependencies

```bash
# With uv (recommended)
uv sync

# Or with pip
pip install -r requirements.txt
```

### 2. Build the Catalog

Place your PDFs in `pdfs/` and EPUBs in `epubs/`, then run:

```bash
python build_catalog.py
```

This scans the files, extracts metadata, and populates the SQLite database at `data/catalog.db`.

### 3. Build the Frontend

```bash
cd frontend
npm install
npx vite build
cd ..
```

### 4. Start the Server

```bash
python main.py
```

Open **http://127.0.0.1:8000** in your browser.

#### Server Options

```
python main.py --host 0.0.0.0     # Custom host
python main.py --port 3000         # Custom port
python main.py --network           # LAN access (binds 0.0.0.0)
python main.py --reload            # Auto-reload for development
python main.py --migrate           # Run DB migration before starting
```

### 5. Optional: LLM Analysis

Install and run [Ollama](https://ollama.ai) for AI-powered text analysis:

```bash
ollama serve
ollama pull llama3.2
```

The reading view's analysis panel will automatically detect Ollama and enable streaming summarization, explanation, critique, and comparison features.

### 6. Optional: Generate Embeddings

For semantic search and "similar books" features:

```bash
# Via the Settings page in the UI, or:
curl -X POST http://127.0.0.1:8000/api/pipeline/generate-embeddings
```

This uses `all-MiniLM-L6-v2` to generate 384-dimensional embeddings for each book's text.

## Project Structure

```
books/
├── main.py                  # Application entry point
├── build_catalog.py         # Catalog builder (scan → extract → enrich → store)
├── pyproject.toml           # Python project config and dependencies
├── requirements.txt         # Pip requirements
│
├── server/                  # FastAPI backend
│   ├── app.py               # App factory, lifespan, middleware, static mount
│   ├── config.py            # Paths and constants
│   ├── db.py                # BookDatabase — SQLite + FTS5 operations
│   ├── search.py            # SearchEngine — FTS5, semantic, and hybrid search
│   ├── similarity.py        # SimilarityEngine — embedding cosine similarity
│   ├── llm_service.py       # Ollama streaming client
│   ├── migrate.py           # JSON → SQLite migration
│   ├── tasks.py             # Background task runner
│   └── routes/
│       ├── books.py         # /api/books — CRUD, list, similar, text
│       ├── search.py        # /api/search — Full-text and semantic search
│       ├── filters.py       # /api/filters — Category/theme/author facets
│       ├── stats.py         # /api/stats — Library statistics
│       ├── reading.py       # /api/reading — Reading text, compare, LLM analyze
│       ├── pipeline.py      # /api/pipeline — Re-process, embeddings
│       └── user.py          # /api/user — Reading status, ratings, tags
│
├── frontend/                # React + TypeScript SPA
│   ├── src/
│   │   ├── App.tsx          # Router setup
│   │   ├── api/             # TanStack Query hooks and API client
│   │   ├── components/
│   │   │   ├── books/       # BookCard, BookGrid, BookList, BookCover
│   │   │   ├── common/      # Spinner, ErrorBoundary
│   │   │   ├── detail/      # BookHeader, SimilarBooks
│   │   │   ├── layout/      # Header, Sidebar
│   │   │   ├── reading/     # ReadingView, LLMPanel
│   │   │   ├── search/      # SearchBar
│   │   │   └── stats/       # Dashboard charts
│   │   ├── hooks/           # Custom React hooks
│   │   ├── pages/           # Route-level page components
│   │   ├── stores/          # Zustand state stores
│   │   └── utils/           # Formatting helpers
│   └── dist/                # Production build output (served by FastAPI)
│
├── catalog/                 # Catalog pipeline modules
│   ├── scanner.py           # File system scanner
│   ├── pdf_extractor.py     # PDF metadata + text extraction
│   ├── epub_extractor.py    # EPUB metadata + text extraction
│   ├── isbn_extractor.py    # ISBN detection from text/metadata
│   ├── title_parser.py      # Filename → title/author parser
│   ├── api_enricher.py      # Open Library / Google Books enrichment
│   ├── cover_scraper.py     # Cover image extraction and download
│   ├── llm_enricher.py      # LLM-based summarization
│   ├── theme_analyzer.py    # Keyword/theme extraction
│   ├── embeddings.py        # Sentence-transformer embedding generation
│   ├── duplicate_detector.py# Fuzzy duplicate detection
│   ├── reading_tracker.py   # Reading status management
│   ├── ocr_extractor.py     # OCR for scanned PDFs
│   ├── database.py          # Catalog JSON/DB storage
│   ├── models.py            # BookRecord dataclass
│   ├── config.py            # Pipeline configuration
│   ├── pipeline.py          # Orchestration pipeline
│   └── watcher.py           # File system watcher
│
├── data/                    # Runtime data (gitignored)
│   ├── catalog.db           # SQLite database
│   ├── catalog.json         # Legacy JSON catalog
│   ├── covers/              # Extracted cover images
│   └── text_excerpts/       # Extracted text files
│
├── pdfs/                    # PDF book files
└── epubs/                   # EPUB book files
```

## API Reference

The server exposes a REST API at `http://localhost:8000/api/`. Interactive Swagger docs are available at `/docs`.

### Books — `/api/books`

| Method  | Endpoint                   | Description                          |
| ------- | -------------------------- | ------------------------------------ |
| GET     | `/api/books`               | List books (paginated, filterable)   |
| GET     | `/api/books/{id}`          | Get single book details              |
| GET     | `/api/books/{id}/similar`  | Get semantically similar books       |
| GET     | `/api/books/{id}/text`     | Get book text excerpt                |
| PATCH   | `/api/books/{id}`          | Update book metadata                 |

**Query parameters for `GET /api/books`:**

| Param       | Type   | Description                                      |
| ----------- | ------ | ------------------------------------------------ |
| `page`      | int    | Page number (default: 1)                         |
| `per_page`  | int    | Items per page (default: 48, max: 200)           |
| `sort`      | string | Sort field: `title`, `date_added`, `year`, etc.  |
| `order`     | string | `asc` or `desc`                                  |
| `category`  | string | Filter by category                               |
| `theme`     | string | Filter by theme                                  |
| `author`    | string | Filter by author                                 |
| `language`  | string | Filter by language                               |
| `file_type` | string | Filter by type: `pdf`, `epub`                    |
| `status`    | string | Filter by reading status                         |
| `favorite`  | bool   | Filter favorites only                            |

### Search — `/api/search`

| Method | Endpoint              | Description                               |
| ------ | --------------------- | ----------------------------------------- |
| GET    | `/api/search`         | Search books (FTS5 / semantic / hybrid)   |
| GET    | `/api/search/suggest` | Autocomplete suggestions                  |

**Query parameters for `GET /api/search`:**

| Param    | Type   | Description                                          |
| -------- | ------ | ---------------------------------------------------- |
| `q`      | string | Search query text                                    |
| `mode`   | string | `fts` (full-text), `semantic`, or `hybrid` (default) |
| `page`   | int    | Page number                                          |
| `per_page` | int  | Items per page                                       |

### Filters — `/api/filters`

| Method | Endpoint               | Description                     |
| ------ | ---------------------- | ------------------------------- |
| GET    | `/api/filters`         | All filter facets with counts   |
| GET    | `/api/filters/categories` | Category facets              |
| GET    | `/api/filters/themes`  | Theme facets                    |
| GET    | `/api/filters/authors` | Author facets                   |
| GET    | `/api/filters/languages` | Language facets               |
| GET    | `/api/filters/years`   | Publication year facets         |
| GET    | `/api/filters/tags`    | User tag facets                 |

### Statistics — `/api/stats`

| Method | Endpoint              | Description                    |
| ------ | --------------------- | ------------------------------ |
| GET    | `/api/stats`          | Library overview statistics    |
| GET    | `/api/stats/reading`  | Reading progress statistics    |

### Reading — `/api/reading`

| Method | Endpoint                     | Description                          |
| ------ | ---------------------------- | ------------------------------------ |
| GET    | `/api/reading/llm-status`    | Check Ollama availability            |
| GET    | `/api/reading/{id}/text`     | Get book text for reading view       |
| POST   | `/api/reading/compare`       | Compare text semantically            |
| POST   | `/api/reading/analyze`       | SSE-stream LLM analysis of text      |

### User — `/api/user`

| Method | Endpoint                    | Description                          |
| ------ | --------------------------- | ------------------------------------ |
| PATCH  | `/api/user/books/{id}`      | Update reading status, rating, tags  |

### Pipeline — `/api/pipeline`

| Method | Endpoint                             | Description                    |
| ------ | ------------------------------------ | ------------------------------ |
| GET    | `/api/pipeline/status`               | Pipeline run status            |
| POST   | `/api/pipeline/run`                  | Trigger catalog re-processing  |
| POST   | `/api/pipeline/generate-embeddings`  | Generate sentence embeddings   |
| GET    | `/api/pipeline/embedding-status`     | Embedding generation status    |
| GET    | `/api/pipeline/unprocessed`          | List unprocessed books         |

## Development

### Frontend Dev Server

For hot-reload during frontend development:

```bash
cd frontend
npm run dev   # Starts Vite on port 5173
```

The backend has CORS configured for `localhost:5173`.

### Database

The SQLite database uses WAL mode for concurrent reads and includes an FTS5 virtual table for full-text search. The schema stores all book metadata, reading progress, user tags, and embeddings.

To inspect the database:

```bash
sqlite3 data/catalog.db
.tables
.schema books
SELECT count(*) FROM books;
```

### Adding Books

1. Drop PDF/EPUB files into the `pdfs/` or `epubs/` directory
2. Run `python build_catalog.py` to process new files
3. Or use the Settings page in the UI to trigger a pipeline run

## License

Private project — not licensed for redistribution.
