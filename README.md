# BookShelf — Smart Book Library

A local-first web application for managing, cataloging, and exploring your personal book collection (PDFs & EPUBs). Features full-text search, AI-powered analysis, semantic similarity, and a modern responsive UI.

## Features

- **Smart Cataloging** — Automatically extracts metadata (title, authors, ISBN, language, page count) from PDF and EPUB files
- **Full-Text Search** — SQLite FTS5 with Porter stemmer over two indexes: one for metadata (title, authors, description, themes, keywords…) and one for each book's own extracted prose. Results carry a highlighted snippet showing why they matched. Every token is quoted before it reaches FTS5, so punctuation and bare `AND` are searched as text rather than parsed as operators
- **Semantic Search** — Sentence-transformer embeddings enable "find books like this" similarity queries
- **Passage Search** — A chunk-level index over the full text of every book. Search the *inside* of your library by meaning, by exact term, or both fused with Reciprocal Rank Fusion; every hit carries its page and a link that opens the book there
- **Reactive Filters** — Sidebar filter counts update dynamically based on active search query and other selected filters, showing real-time availability
- **Reading View** — In-browser PDF and EPUB readers with adjustable zoom/font size, continuous or paginated flow, and a text-selection sidebar
- **Resume Where You Left Off** — Both readers persist page or EPUB position and progress percentage, feeding a *Continue reading* shelf on the home page
- **Similar Passages** — Select any paragraph and see where the same idea recurs *elsewhere in the same book*, and which passages in other books resemble it — the actual matching prose with its page, not a book recommendation
- **Stance Grouping** — Retrieved passages sorted into supports / complicates / contradicts, grounded entirely in retrieved text so every claim stays citable to a page
- **Concept Threads** — Recurring arguments within a book: the same idea in chapter 2 and chapter 11, found and linked
- **LLM Analysis** — Ollama-powered streaming analysis (summarize, explain, critique, compare) of selected text passages
- **Passage-Scoped Conversations** — Follow-up threads that pin the passage and its retrieved context, so "why?" still refers to something; saved against the book and exportable
- **Cover Art** — Automatic cover extraction from files and API enrichment from Open Library / Google Books
- **Dashboard** — Visual statistics with charts showing library composition by category, type, language, and reading progress
- **Four Themes** — Light, Dark, Paper (warm sepia) and Dim (soft dark), applied before first paint with system-preference detection. Press `d` to cycle
- **Responsive Grid/List Views** — Switch between grid and list layouts with sort and filter controls
- **Smart Autocomplete** — Multi-tier search suggestions (title prefix → FTS match → fuzzy LIKE fallback) with keyboard navigation and highlight matching
- **Reading Tracker** — Mark books as not started / in progress / finished / abandoned; progress percentage is maintained by the readers themselves
- **Reading Sessions** — Time actually spent reading, pages per week and streaks, recorded by heartbeat so closing the laptop does not log a fourteen-hour day
- **Markdown Export** — Highlights, notes, bookmarks and LLM threads out to a portable file, per book or for the whole library
- **Tags** — Add your own tags to any book and filter the library by them; the tag vocabulary is suggested back to you as you type
- **Duplicate Resolution** — Fuzzy-matched duplicates are grouped on their own page where you can choose which copy to keep. Nothing there deletes a file

## Tech Stack

| Layer      | Technology                                            |
| ---------- | ----------------------------------------------------- |
| Backend    | Python 3.11+, FastAPI, uvicorn                        |
| Database   | SQLite (WAL mode) + two FTS5 virtual tables           |
| Frontend   | React 18, TypeScript, Vite 8, Tailwind CSS v4         |
| State      | TanStack Query v5; UI state in the URL + localStorage |
| Charts     | Recharts                                              |
| Icons      | Lucide React                                          |
| Embeddings | sentence-transformers (`BAAI/bge-small-en-v1.5`)      |
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

This scans the files, extracts metadata, verifies it against OpenLibrary and Google
Books, and populates the SQLite database at `data/catalog.db`.

Nothing from an external provider is written because it was *returned* — it is written
because it *scored* against local evidence (filename, embedded metadata, title page,
ISBN). Matches at 0.75 or above are applied in full; 0.45–0.75 contributes descriptive
fields only and lands in the review queue; below that the result is rejected and logged.
Every field records where it came from and how confident we are, in `field_sources`.

Useful flags:

```bash
python build_catalog.py --only "Aisha.pdf"   # process one file (repeatable)
python build_catalog.py --max 50             # first 50 books
python build_catalog.py --type epub          # EPUBs only
python build_catalog.py --llm                # Ollama summaries + borderline adjudication
python build_catalog.py --verify-sources     # probe providers before running
python build_catalog.py --force              # redo everything, ignoring stage versions
python build_catalog.py --report             # catalog quality report
python build_catalog.py --review             # list records needing human review
python build_catalog.py --export-json        # write data/catalog.json (an export, not a source)
```

Re-runs are incremental: each stage carries a version, and a stage only runs again when
its version changed, the file's content hash changed, or `--force` is given. Bumping one
stage version in `catalog/config.py` re-runs just that stage across the catalog.

**Provider API keys.** Google Books' anonymous quota is small and per-IP, so bulk runs
get 429s. Copy `.env.example` to a gitignored `.env` at the project root and put a key
in it to lift the limit:

```bash
cp .env.example .env
```

```
GOOGLE_BOOKS_API_KEY=your-key-here
```

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
```

### 5. Optional: LLM Analysis

Install and run [Ollama](https://ollama.ai) for AI-powered text analysis:

```bash
ollama serve
ollama pull llama3.2
```

The reading view's analysis panel checks `GET /api/reading/llm-status` and enables
its buttons only when Ollama answers *and* the configured model is pulled — otherwise
it says which of the two is missing instead of failing on click.

Both the model and the endpoint are configurable:

```
OLLAMA_MODEL=llama3.2
OLLAMA_BASE_URL=http://localhost:11434
```

### 6. Optional: Generate Embeddings

For semantic search and "similar books" features:

```bash
# Via the Settings page in the UI, or:
curl -X POST http://127.0.0.1:8000/api/pipeline/generate-embeddings
```

This uses `BAAI/bge-small-en-v1.5` to generate 384-dimensional embeddings for each
book's text. It replaced `all-MiniLM-L6-v2`: same dimensions, so nothing about the
storage or the search changes, but a 512-token sequence limit instead of 256 — the
old model truncated a 4,000-character content sample around its halfway mark.

Vectors from two models share a shape and mean nothing together, so each row is
stamped with the model that produced it and the server refuses to load rows that
do not match. After changing `EMBEDDING_MODEL`, re-embed the whole catalog:

```bash
python scripts/reembed.py
```

### 7. Optional: Build the Passage Index

Everything under *Passage Search*, *Similar Passages*, *Stance Grouping* and
*Concept Threads* runs on a chunk-level index over your books' full text. Until
it is built those features say so rather than returning empty results.

```bash
python scripts/build_passage_index.py --limit 30   # try it on 30 books first
python scripts/build_passage_index.py              # then the whole library
python scripts/build_passage_index.py --status     # what is indexed now
```

It is resumable: a second run indexes only the books the first did not reach,
and carries existing vectors over rather than recomputing them. Measured on a
618-book / 187,000-page library: roughly **50 minutes once**, and about
**530 MB** on disk (extracted text plus float16 vectors plus the FTS index).

Passage search is exact brute-force — a NumPy matmul over the whole index,
measured at 0.30 ms for 24,000 chunks. There is no ANN index to tune and no
approximation to debug.

Two optional switches:

```bash
PASSAGE_RERANK=1 python main.py    # cross-encoder reranking (~80 MB model, +50 ms/query)
CHUNK_TARGET_CHARS=1200 python scripts/build_passage_index.py --force
```

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
│   ├── similarity.py        # SimilarityEngine — book-level embedding cosine similarity
│   ├── passages.py          # PassageIndex — chunk retrieval: dense + BM25, RRF, reranking
│   ├── llm_service.py       # Ollama async streaming client
│   ├── tasks.py             # Background task runner
│   └── routes/
│       ├── params.py        # Shared filter query-parameter dependency
│       ├── schemas.py       # Shared request bodies
│       ├── books.py         # /api/books — CRUD, list, similar, file, user fields
│       ├── search.py        # /api/search — Full-text, semantic and hybrid search
│       ├── filters.py       # /api/filters — Reactive facets scoped to search/filters
│       ├── stats.py         # /api/stats — Library statistics
│       ├── reading.py       # /api/reading — Reading text, compare, LLM analyze
│       ├── passages.py      # /api/passages — Passage search, stance, concept threads
│       ├── annotations.py   # /api/annotations — Highlights, notes, bookmarks
│       ├── threads.py       # /api/threads — Passage-scoped LLM conversations
│       ├── sessions.py      # /api/sessions — Reading time; EPUB locations cache
│       ├── export.py        # /api/export — Markdown export of notes and threads
│       ├── duplicates.py    # /api/duplicates — Duplicate groups and resolution
│       ├── pipeline.py      # /api/pipeline — Re-process, embeddings
│       └── review.py        # /api/review — Review queue, pinned corrections
│
├── frontend/                # React + TypeScript SPA
│   ├── src/
│   │   ├── App.tsx          # Router setup
│   │   ├── api/             # TanStack Query hooks and API client
│   │   ├── components/
│   │   │   ├── books/       # BookCard, BookGrid, BookList, BookCover, ContinueReading
│   │   │   ├── common/      # Spinner, ErrorBoundary, EmptyState, Badge, Rating, ProgressBar
│   │   │   ├── detail/      # BookHeader, SimilarBooks, TagEditor
│   │   │   ├── layout/      # Header, Sidebar (reactive filter counts), ThemePicker
│   │   │   ├── reading/     # PdfReader, EpubReader, ReaderSidebar, PassagePanel, ThreadPanel
│   │   │   ├── search/      # SearchBar (multi-mode, keyboard nav), SnippetText
│   │   │   └── stats/       # Dashboard charts
│   │   ├── hooks/           # useLibraryParams (URL state), useTheme, useReadingProgress, shortcuts
│   │   ├── pages/           # Route-level page components
│   │   └── utils/           # Formatting helpers
│   └── dist/                # Production build output (served by FastAPI)
│
├── catalog/                 # Catalog pipeline modules
│   ├── full_text.py         # Whole-document extraction with a page/spine offset map
│   ├── chunking.py          # Passage chunker — structure-first, positionally anchored
│   ├── passage_index.py     # Index builder — chunk, embed, write chunks + vectors
│   ├── annotations.py       # Highlights, bookmarks and notes (shared write path)
│   ├── threads.py           # LLM thread and message storage
│   ├── reading_sessions.py  # Heartbeat-closed reading sessions, streaks
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
│   ├── store.py             # CatalogStore — SQLite store of record
│   ├── schema.py            # Shared DDL, column lists, FTS index
│   ├── user_data.py         # User-owned fields and pinned corrections
│   ├── fts.py               # The one FTS5 query builder
│   ├── languages.py         # ISO-639-1 normalisation for dirty language values
│   ├── evidence.py          # Match scoring and verification evidence
│   ├── providers.py         # Metadata provider clients
│   ├── taxonomy.py          # Category/theme normalisation
│   ├── text_utils.py        # Text cleaning helpers
│   ├── names.py             # Author name parsing
│   ├── reporting.py         # Catalog quality report
│   ├── models.py            # BookRecord dataclass
│   ├── config.py            # Pipeline configuration
│   ├── pipeline.py          # Orchestration pipeline
│   └── watcher.py           # File system watcher
│
├── data/                    # Runtime data (gitignored)
│   ├── catalog.db           # SQLite database
│   ├── catalog.json         # Legacy JSON catalog
│   └── covers/              # Extracted cover images
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
| GET     | `/api/books/continue-reading` | Opened-but-unfinished books, most recent first |
| GET     | `/api/books/{id}/file`     | Raw PDF/EPUB bytes for the in-browser readers |
| PATCH   | `/api/books/{id}`          | Update user fields (status, rating, tags, favourite, progress, position) |

**Query parameters for `GET /api/books`:**

| Param       | Type   | Description                                      |
| ----------- | ------ | ------------------------------------------------ |
| `page`      | int    | Page number (default: 1)                         |
| `per_page`  | int    | Items per page (default: 48, max: 200)           |
| `sort`      | string | `title`, `author`, `date_added`, `year`, `size`, `pages`, `rating`, `last_opened` |
| `order`     | string | `asc` or `desc`                                  |
| `category`  | string | Filter by category                               |
| `theme`     | string | Filter by theme                                  |
| `author`    | string | Filter by author                                 |
| `language`  | string | Normalised ISO-639-1 code, or `unknown`          |
| `file_type` | string | Filter by type: `pdf`, `epub`                    |
| `reading_status` | string | Filter by reading status                    |
| `tag`       | string | Filter by user tag                               |
| `favorite`  | bool   | Filter favorites only                            |

### Search — `/api/search`

| Method | Endpoint              | Description                               |
| ------ | --------------------- | ----------------------------------------- |
| GET    | `/api/search`         | Search books (FTS5 / semantic / hybrid)   |
| GET    | `/api/search/suggest` | Autocomplete suggestions                  |

**Query parameters for `GET /api/search`:**

| Param             | Type   | Description                                          |
| ----------------- | ------ | ---------------------------------------------------- |
| `q`               | string | Search query text                                    |
| `mode`            | string | `text` (full-text), `semantic`, or `hybrid` (default)|
| `page`            | int    | Page number                                          |
| `per_page`        | int    | Items per page                                       |
| `file_type`       | string | Filter by type: `pdf`, `epub`                        |
| `category`        | string | Filter by category                                   |
| `theme`           | string | Filter by theme                                      |
| `language`        | string | Normalised ISO-639-1 code, or `unknown`              |
| `reading_status`  | string | Filter by reading status                             |
| `favorite`        | bool   | Filter favorites only                                |
| `has_cover`       | bool   | Filter by cover availability                         |
| `has_description` | bool   | Filter by description availability                   |
| `year_min`        | int    | Minimum publication year                             |
| `year_max`        | int    | Maximum publication year                             |
| `author`          | string | Filter by author                                     |
| `tag`             | string | Filter by user tag                                   |

### Filters — `/api/filters`

| Method | Endpoint               | Description                                    |
| ------ | ---------------------- | ---------------------------------------------- |
| GET    | `/api/filters`         | Reactive filter facets scoped to current query  |

`GET /api/filters` accepts the same filter query parameters as `GET /api/books` (e.g. `search`, `category`, `file_type`, etc.). Each facet dimension excludes its own filter but applies all others, so counts reflect what's available if the user changes that particular filter while all other constraints remain.

### Statistics — `/api/stats`

| Method | Endpoint              | Description                    |
| ------ | --------------------- | ------------------------------ |
| GET    | `/api/stats`          | Library overview statistics    |

### Reading — `/api/reading`

| Method | Endpoint                     | Description                          |
| ------ | ---------------------------- | ------------------------------------ |
| GET    | `/api/reading/llm-status`    | Check Ollama availability            |
| GET    | `/api/reading/{id}/text`     | Get book text for reading view       |
| POST   | `/api/reading/compare`       | Passages resembling a selection      |
| POST   | `/api/reading/analyze`       | SSE-stream LLM analysis of text      |

### Passages — `/api/passages`

| Method | Endpoint                        | Description                                   |
| ------ | ------------------------------- | --------------------------------------------- |
| GET    | `/api/passages/status`          | Whether the index is built, and over what     |
| POST   | `/api/passages/search`          | Hybrid / semantic / keyword passage search    |
| POST   | `/api/passages/similar`         | Passages resembling a selection               |
| GET    | `/api/passages/{chunk_id}`      | One passage plus its neighbours               |
| POST   | `/api/passages/stance`          | Supports / complicates / contradicts          |
| GET    | `/api/books/{id}/threads`       | Recurring concepts within one book            |

### Threads, sessions and export

| Method | Endpoint                          | Description                              |
| ------ | --------------------------------- | ---------------------------------------- |
| GET/POST | `/api/threads`                  | Passage-scoped LLM conversations         |
| POST   | `/api/threads/{id}/messages`      | Ask a follow-up; SSE, both turns stored  |
| POST   | `/api/sessions/heartbeat`         | "Still reading" — extends a session      |
| GET    | `/api/sessions/stats`             | Time, pages/week, streaks                |
| GET    | `/api/books/{id}/locations`       | Cached EPUB locations index              |
| GET    | `/api/export/markdown`            | Highlights, notes and threads as Markdown |
| GET    | `/api/duplicates`                 | Duplicate groups, canonical first        |
| POST   | `/api/duplicates/{id}/keep`       | Make this copy canonical                 |

### Pipeline — `/api/pipeline`

| Method | Endpoint                             | Description                    |
| ------ | ------------------------------------ | ------------------------------ |
| GET    | `/api/pipeline/status`               | Pipeline run status            |
| POST   | `/api/pipeline/run`                  | Trigger catalog re-processing  |
| POST   | `/api/pipeline/generate-embeddings`  | Generate sentence embeddings   |
| GET    | `/api/pipeline/embedding-status`     | Embedding generation status    |
| GET    | `/api/pipeline/unprocessed`          | Count files on disk not yet catalogued |
| GET    | `/api/pipeline/report`               | Catalog quality report         |

### Review — `/api/review`

Records the verification gate could not confirm. A correction made here is pinned as
`source: "user"`, `confidence: 1.0`, and no future pipeline run may overwrite it.

| Method | Endpoint                      | Description                          |
| ------ | ----------------------------- | ------------------------------------ |
| GET    | `/api/review/queue`           | Records needing review, worst first  |
| POST   | `/api/review/{id}/pin`        | Pin a corrected field value          |
| POST   | `/api/review/{id}/resolve`    | Mark a record as reviewed            |

### Operations

| Method | Endpoint       | Description                                            |
| ------ | -------------- | ------------------------------------------------------ |
| GET    | `/api/health`  | Version, book count, whether embeddings loaded         |

Cover images under `/covers/` are served with `Cache-Control: public, max-age=604800`
alongside the `ETag`/`Last-Modified` handling `StaticFiles` already does, so a hard
refresh no longer re-downloads every image in the library.

## Development

### Tests and linting

CI (`.github/workflows/ci.yml`) runs all of this on every push and pull request.
Run it locally the same way:

```bash
pytest -q                 # backend: 262 tests — catalog pipeline + every API route
cd frontend
npx tsc -b                # type check
npm run lint              # eslint, including the React hooks rules
npm run build             # production build
npx vitest run            # frontend: 45 unit tests
```

`pytest` needs only the `dev` extra (`pip install -e ".[dev]"` or `uv sync --extra dev`).
The route tests build the real app against a throwaway SQLite database via the
fixtures in `tests/conftest.py`, so they need no catalog and no embeddings.

### Configuration

Copy `.env.example` to `.env` and fill in what you need. Everything in it is
optional — the app runs with no `.env` at all.

| Variable                | Default                  | Used by                              |
| ----------------------- | ------------------------ | ------------------------------------ |
| `GOOGLE_BOOKS_API_KEY`  | —                        | Catalog enrichment; lifts the anonymous per-IP quota |
| `OLLAMA_BASE_URL`       | `http://localhost:11434` | Reading-view analysis, `--llm` runs   |
| `OLLAMA_MODEL`          | `llama3.2`               | Reading-view analysis, `--llm` runs   |

### Frontend Dev Server

For hot-reload during frontend development:

```bash
cd frontend
npm run dev   # Starts Vite on port 5173
```

The backend has CORS configured for `localhost:5173`.

### Database

`data/catalog.db` is the store of record: the pipeline writes it directly and the server
reads it, so there is no JSON round-trip and no "which store is current?" question.
`data/catalog.json` is produced only by `--export-json`.

The database uses WAL mode for concurrent reads and two FTS5 virtual tables for
full-text search — `books_fts` over metadata and `book_text_fts` over each book's
extracted prose, kept separate so a 5 000-character excerpt cannot outrank an exact
title match on term frequency alone. Both are external-content indexes over `books`,
so neither stores a second copy of the text, and triggers keep them in sync.

Three tables hold book data:

- `books` — everything the pipeline produces, including `field_sources` (per-field source
  and confidence), `match_score`, `needs_review` and `stage_versions`
- `user_data` — ratings, tags, favourites, reading progress, reader position and pinned
  corrections. The pipeline does not write these columns, so a run (or a full rebuild)
  cannot destroy them. One declared exception: the opt-in reading-progress stage may
  *advance* `last_opened` when the filesystem reports a newer open, never move it back
- `embeddings` — content and metadata vectors

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
3. Or use the Settings page in the UI, which shows how many files on disk are
   not yet in the catalog and reports per-book progress while a run is going

### Schema migrations

`catalog/schema.py` is the only place the DDL lives, and `ensure_schema()` runs
on every start from both the pipeline and the server. It adds missing columns
in place and rebuilds an FTS index whenever its indexed column set changes, so
upgrading is just starting the app. It is additive only — no existing table is
dropped or rewritten — but `data/catalog.db` is your library's memory, so take
a copy before a version jump:

```bash
sqlite3 data/catalog.db ".backup 'data/catalog.db.bak'"
```

## License

Private project — not licensed for redistribution.
