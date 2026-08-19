# API Documentation

> Base URL: `http://localhost:8000`  
> Version: `1.1.0` — see `GET /api/health`  
> Interactive docs: `http://localhost:8000/docs` (Swagger UI)

All endpoints return JSON unless otherwise noted.

---

## Books

### `GET /api/books`

List books with pagination, sorting, and filtering.

**Query Parameters:**

| Param             | Type   | Default  | Description                              |
| ----------------- | ------ | -------- | ---------------------------------------- |
| `page`            | int    | 1        | Page number (≥ 1)                        |
| `per_page`        | int    | 48       | Items per page (1–200)                   |
| `sort`            | string | `title`  | Sort field: `title`, `author`, `date_added`, `year`, `size`, `pages`, `rating`, `last_opened`. Unknown values fall back to `title`. |
| `order`           | string | `asc`    | Sort direction (`asc` or `desc`)         |
| `file_type`       | string | —        | `pdf` or `epub`                          |
| `category`        | string | —        | Filter by category name                  |
| `theme`           | string | —        | Filter by theme name                     |
| `author`          | string | —        | Filter by author name                    |
| `language`        | string | —        | Normalised ISO-639-1 code (e.g. `en`), or `unknown` — see `GET /api/filters` |
| `reading_status`  | string | —        | `not_started`, `in_progress`, `finished`, `abandoned` |
| `has_cover`       | bool   | —        | `true` requires a cover, `false` requires none |
| `has_description` | bool   | —        | `true` requires a description, `false` requires none |
| `year_min`        | int    | —        | Minimum publication year                 |
| `year_max`        | int    | —        | Maximum publication year                 |
| `rating_min`      | int    | —        | Minimum user rating (1–5)               |
| `favorite`        | bool   | —        | Filter favorites only                    |
| `tag`             | string | —        | Filter by user tag                       |
| `search`          | string | —        | Text filter over metadata **and** book text. Unlike `/api/search` this only filters — results stay in `sort` order and carry no snippet. |

**Response:**

```json
{
  "items": [{ "id": "abc123...", "title": "...", ... }],
  "total": 120,
  "page": 1,
  "per_page": 48,
  "pages": 3
}
```

---

### `GET /api/books/{book_id}`

Get full details for a single book.

**Response:** Full `Book` object with all metadata fields plus `has_embeddings: boolean`.

Every `Book` also carries `identity_confidence` (float, 0–1): how sure the catalog
is about *which book this is*, computed from `field_sources` for `title`, `authors`
and the ISBNs. It is derived on read, never stored, so it cannot drift from the
per-field provenance it summarises — and unlike `match_score` it is defined for a
record no provider ever matched.

---

### `GET /api/books/{book_id}/similar`

Get semantically similar books using embedding cosine similarity.

| Param    | Type   | Default    | Description                |
| -------- | ------ | ---------- | -------------------------- |
| `limit`  | int    | 8          | Max results (1–20)         |
| `method` | string | `combined` | `combined`, `content`, `metadata` |

**Response:** Array of `Book` objects with `similarity_score`. Returns `404` for an unknown `book_id`.

---

### `GET /api/books/continue-reading`

Books that have been opened and not finished, most recently opened first.
Populated by the readers, which stamp `last_opened`, `progress_percent` and
`reader_position` as you read.

| Param   | Type | Default | Description        |
| ------- | ---- | ------- | ------------------ |
| `limit` | int  | 8       | Max results (1–24) |

**Response:** Array of `Book` objects.

---

### `GET /api/books/{book_id}/file`

Serve the raw PDF or EPUB for in-browser reading. `GET /api/books/{book_id}/file.epub`
is an alias for the same bytes — epub.js chooses its loader from the URL
extension, and without one it treats the response as an unpacked EPUB
directory.

**Response:** the file, with `Content-Type` set from `file_type`. `404` if the
book is unknown or its file is no longer on disk.

---

### `PATCH /api/books/{book_id}`

Update the user-owned fields of a book. Pipeline-owned metadata is not writable
here — use `POST /api/review/{book_id}/pin` to correct catalogue data.

**Request Body:** any subset of

| Field              | Type       | Notes                                                    |
| ------------------ | ---------- | -------------------------------------------------------- |
| `reading_status`   | string     | `not_started`, `in_progress`, `finished`, `abandoned`     |
| `progress_percent` | float      | 0–100                                                     |
| `reader_position`  | string     | Opaque resume token: an EPUB CFI or a PDF page number (max 2000 chars) |
| `user_rating`      | float\|null | 0–5; send `null` to clear                                |
| `user_tags`        | string[]   |                                                           |
| `favorite`         | bool       |                                                           |
| `last_opened`      | string     | ISO 8601                                                  |

Only the fields present in the body are written. Unknown field names are
rejected with `422` — this endpoint previously accepted them and dropped them
silently. Returns `404` if the book does not exist.

---

## Search

### `GET /api/search`

Full-text and/or semantic search across the library.

| Param      | Type   | Default  | Description                                    |
| ---------- | ------ | -------- | ---------------------------------------------- |
| `q`        | string | required | Search query                                   |
| `mode`            | string | `hybrid` | `text` (full-text), `semantic`, or `hybrid`    |
| `page`            | int    | 1        | Page number                                    |
| `per_page`        | int    | 48       | Results per page                               |
| `file_type`       | string | —        | Filter by `pdf` or `epub`                      |
| `category`        | string | —        | Filter by category name                        |
| `theme`           | string | —        | Filter by theme name                           |
| `language`        | string | —        | Filter by language code                        |
| `reading_status`  | string | —        | Filter by reading status                       |
| `favorite`        | bool   | —        | Filter favorites only                          |
| `has_cover`       | bool   | —        | Filter by cover availability                   |
| `has_description` | bool   | —        | Filter by description availability             |
| `year_min`        | int    | —        | Minimum publication year                       |
| `year_max`        | int    | —        | Maximum publication year                       |
| `author`          | string | —        | Filter by author name                          |
| `tag`             | string | —        | Filter by user tag                             |

**Search modes:**
- **`text`** — SQLite FTS5 with Porter stemmer, across **two** indexes: `books_fts`
  over metadata (title, authors, description, summary, themes, categories,
  keywords, publisher, raw subjects) and `book_text_fts` over the book's own
  extracted prose (`text_excerpt`, `front_matter`, `content_sample`). A book
  matching both is scored on both, with the text side weighted at 0.35 so a
  title match still outranks a passing mention in a 5 000-character excerpt.
- **`semantic`** — Encodes the query with `BAAI/bge-small-en-v1.5` and ranks the whole
  catalog by cosine similarity. Requires embeddings. Results must clear a
  relevance floor — an absolute 0.28 and 55% of the best score — because
  otherwise every book in the library scores above zero against every query
  and `total` would always be the size of the library.
- **`hybrid`** *(default)* — Runs both and merges on normalised scores
  (40% FTS + 60% semantic). The FTS side is unioned in, so an exact keyword
  match is never dropped by the semantic floor.

Every token of the query is quoted before it reaches FTS5, so `AND`, `-`, `*`,
`"` and `title:` are matched as literal text rather than as operators. Prefix
matching is applied automatically to tokens longer than two characters;
quoted phrases, `OR` and column-scoped search are **not** supported as
operators.

All search modes support the full set of filter parameters, applied server-side.

**Response:** Same paginated format as `GET /api/books`, plus per item:

| Field         | Type   | Description                                                    |
| ------------- | ------ | -------------------------------------------------------------- |
| `_score`      | float  | Rank score. bm25 for `text` (lower is better), cosine otherwise |
| `match_type`  | string | `fts`, `semantic` or `hybrid`                                   |
| `match_field` | string | `text` or `metadata` — which index produced the snippet         |
| `snippet`     | string | Matching excerpt, present when the match came from FTS          |

Matched terms inside `snippet` are wrapped in the control characters `U+0002`
and `U+0003` rather than in markup, so a client can highlight them without
rendering server-supplied HTML. Elisions are marked with `…`.

---

### `GET /api/search/suggest`

Autocomplete suggestions for the search bar. Uses a multi-tier strategy:
1. **Title prefix match** — FTS5 prefix search on the title column (highest priority)
2. **Broad FTS match** — Full-text search across all indexed fields
3. **LIKE fallback** — Case-insensitive substring match on title and author for fuzzy matching

| Param   | Type   | Default | Description           |
| ------- | ------ | ------- | --------------------- |
| `q`     | string | `""` | Partial query string  |
| `limit` | int    | 8       | Max suggestions (1–20)|

**Response:**

```json
[
  { "id": "abc123", "title": "Machine Learning in Action", "author": "Peter Harrington" },
  { "id": "def456", "title": "Hands-On Machine Learning", "author": "Aurélien Géron" }
]
```

---

## Filters

### `GET /api/filters`

Get filter facets with counts, **reactively scoped** to current search and active filters.

Each facet dimension excludes its own filter but applies all others. For example, when `category=Python` is active, the category facet shows counts as if that filter were removed (so you can see alternatives), but all other facets (themes, languages, file types, etc.) only count books in the "Python" category.

**Query Parameters:**

Accepts the same filter parameters as `GET /api/books`:

| Param             | Type   | Description                              |
| ----------------- | ------ | ---------------------------------------- |
| `search`          | string | Scope facets to FTS search results       |
| `file_type`       | string | `pdf` or `epub`                          |
| `category`        | string | Filter by category name                  |
| `theme`           | string | Filter by theme name                     |
| `language`        | string | Normalised ISO-639-1 code, or `unknown`  |
| `reading_status`  | string | Filter by reading status                 |
| `favorite`        | string | `true` to filter favorites               |
| `has_cover`       | string | `true` to filter books with covers       |
| `has_description` | string | `true` to filter books with descriptions |
| `year_min`        | string | Minimum publication year                 |
| `year_max`        | string | Maximum publication year                 |
| `author`          | string | Filter by author name                    |
| `tag`             | string | Filter by user tag                       |

When called with no parameters, returns unfiltered global facet counts.

**Language facets are normalised.** Stored values come from file metadata and
are not all ISO-639-1 — the catalog holds `po`, `sp` and `ge` alongside empty
strings. Each value is folded to a two-letter code where it validly maps
(`EN`, `en-GB`, `eng` → `en`) and bucketed as `unknown` where it does not,
rather than being guessed at. Passing `language=unknown` back as a filter
matches every raw value in that bucket. `unknown` always sorts last.

**Response:**

```json
{
  "categories": [{ "name": "Computers", "count": 21 }, ...],
  "themes": [...],
  "authors": [...],
  "languages": [...],
  "file_types": [...],
  "years": { "min": 1950, "max": 2024 },
  "reading_statuses": [...],
  "tags": [...],
  "total_matching": 85
}
```

---

## Statistics

### `GET /api/stats`

Library overview statistics.

**Response:**

```json
{
  "total_books": 120,
  "total_size_bytes": 1097869527,
  "by_type": { "epub": 37, "pdf": 83 },
  "by_status": { "not_started": 120 },
  "with_cover": 118,
  "with_description": 92,
  "with_embeddings": 0,
  "duplicates": 24,
  "avg_rating": null,
  "categories": [...],
  "themes": [...],
  "year_histogram": [...],
  "recently_processed": [...]
}
```

All counts exclude records whose file is no longer on disk (`status = "missing"`),
matching `GET /api/books`.

---

## Reading

### `GET /api/reading/llm-status`

Whether the LLM analysis actions will work, and why not when they will not.
The result is cached for 30 s, because the frontend gates its Analysis buttons
on this and each probe costs the connect timeout when Ollama is down.

**Response:**

```json
{
  "available": true,
  "model": "llama3.2",
  "model_installed": false,
  "reason": "model 'llama3.2' is not pulled",
  "base_url": "http://localhost:11434"
}
```

`model` and `base_url` come from the `OLLAMA_MODEL` and `OLLAMA_BASE_URL`
environment variables. `reason` is empty when everything is ready.

### `GET /api/reading/{book_id}/text`

Get book text for the reading view.

### `POST /api/reading/compare`

Find semantically similar passages across other books.

**Request Body:**

```json
{
  "text": "Selected text passage...",
  "book_id": "abc123",   // optional — exclude this book from results
  "limit": 5
}
```

**Response:**

```json
{
  "matches": [
    {
      "book_id": "def456",
      "title": "Similar Book",
      "author": "Author Name",
      "excerpt": "First 300 chars of text...",
      "similarity": 87.3,
      "cover_url": "/covers/def456.jpg"
    }
  ]
}
```

### `POST /api/reading/analyze`

Stream LLM analysis of selected text via Server-Sent Events (SSE).

**Request Body:**

```json
{
  "text": "Text to analyze...",
  "book_id": "abc123",       // optional — provides book context
  "action": "summarize",     // explain | summarize | compare | critique | related
  "surrounding": "…"         // optional — prose around the selection
}
```

`surrounding` is the enclosing block of the selection, sent by the reader. A
paragraph read in isolation loses the argument it belongs to, so it is passed
to the model as background and clipped server-side.

For `compare` and `related` the server also retrieves the closest passages
from the rest of the library and interpolates them into the prompt, numbered
and attributed so the model can cite them. This used to be missing: the
`compare` template has always interpolated a `context` argument, and the route
never supplied one — so every Compare request sent a prompt ending in a bare
`Related:` with nothing after it. When nothing is retrieved the prompt now
degrades to a self-contained question rather than a dangling heading.

**Response:** `text/event-stream` with chunked tokens:

```
data: {"token": "This "}
data: {"token": "passage "}
data: {"token": "discusses..."}
data: [DONE]
```

---

## Annotations

Highlights, bookmarks and margin notes — the only data in the catalog a human
authors directly. Stored keyed by book id *and* file path, so a full catalog
rebuild cannot orphan them: book ids are content hashes, so re-encoding a file
changes its id, and the server relinks annotations by path at startup.

Anchoring is per format and deliberately approximate:

| Format | Anchor | Fallback |
|---|---|---|
| PDF | `page` | `anchor_text` |
| EPUB | `cfi` | `anchor_text` |

`anchor_text` is the first ~60 characters of the selection, whitespace
collapsed — the needle used to relocate a mark when its page or CFI no longer
resolves. It is set from `text` when not supplied.

### `GET /api/annotations`

**Query Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `book_id` | string | — | Scope to one book |
| `kind` | string | — | `highlight`, `bookmark` or `note` |
| `limit` | int | 500 | 1–2000 |

Returned in reading order: by page where there is one, then by CFI.

```json
{
  "annotations": [
    {
      "id": "ab2fe8f083df4711a161d830ec0e6b49",
      "book_id": "abc123",
      "file_path": "pdfs/example.pdf",
      "kind": "highlight",
      "text": "The religious and the scientific process…",
      "note": "Iqbal on the unity of method",
      "color": "yellow",
      "page": 12,
      "cfi": "",
      "anchor_text": "The religious and the scientific process, though invol",
      "created_at": "2026-08-19T13:39:05",
      "updated_at": "2026-08-19T13:39:05"
    }
  ],
  "total": 1
}
```

### `POST /api/annotations`

Creates one annotation. `book_id` is required and must resolve; everything
else is optional. Returns `201` with the stored row.

```json
{
  "book_id": "abc123",
  "kind": "highlight",
  "text": "The selected passage",
  "note": "",
  "color": "yellow",
  "page": 12,
  "cfi": "",
  "anchor_text": ""
}
```

`text` and `note` are capped at 8000 characters and truncated rather than
rejected. `page` is 1-indexed. An unknown `kind` is `422`; an unknown
`book_id` is `404`.

### `PATCH /api/annotations/{annotation_id}`

Patches `kind`, `text`, `note`, `color`, `page`, `cfi` or `anchor_text`.
`id` and `book_id` are fixed at creation — an annotation cannot be moved to a
different book. Returns the updated row, or `404`.

### `DELETE /api/annotations/{annotation_id}`

`204` on success, `404` if it does not exist.

---

## User fields

User-owned fields are written through `PATCH /api/books/{book_id}` — see above.
There used to be a second, near-identical route at `PATCH /api/user/books/{id}`;
it has been removed.

---

## Pipeline

### `GET /api/pipeline/status`

Current pipeline run status. `{"status": "idle"}` when nothing has run this
process, otherwise the tracked task:

```json
{
  "status": "running",
  "progress": 41,
  "total": 74,
  "message": "Extracting metadata: Atomic Habits",
  "started_at": "2026-08-17T11:04:22",
  "completed_at": null,
  "error": null
}
```

`status` is one of `idle`, `running`, `completed`, `failed`.

### `POST /api/pipeline/run`

Trigger a catalog re-processing run.

Returns `409` if a run is already in progress.

**Request Body:** all fields optional.

| Field        | Type      | Default | Description                                     |
| ------------ | --------- | ------- | ----------------------------------------------- |
| `max_books`  | int       | `0`     | Cap the number of books processed; `0` = no cap |
| `file_types` | string[]  | `null`  | Restrict to e.g. `["pdf"]`                      |
| `llm`        | bool      | `false` | Run the LLM enrichment stage                    |
| `embed`      | bool      | `false` | Generate embeddings as part of the run          |
| `force`      | bool      | `false` | Re-process already processed books              |

There is no `book_ids` parameter.

### `POST /api/pipeline/generate-embeddings`

Start embedding generation for all books with text.

### `GET /api/pipeline/embedding-status`

Check embedding generation progress.

### `GET /api/pipeline/unprocessed`

Count — not list — the files on disk that are not in the catalog yet.

```json
{ "unprocessed": 74, "total_files": 618 }
```

An `error` key is added instead of raising if the scan fails.

### `GET /api/pipeline/report`

Catalog quality report: field fill rates, provenance breakdown and confidence
distribution.

---

## Review queue

Records the verification gate could not confirm surface here. A human
correction is pinned as `source: "user"`, `confidence: 1.0`, and no future
pipeline run may overwrite it.

### `GET /api/review/queue`

Records needing confirmation, least certain identity first.

Ordered by `identity_confidence` — how sure we are *which book this is*, derived
from the provenance of `title`, `authors` and the ISBNs — not by `match_score`,
which only scores an API candidate and is `null` for a record identified from
the file's own embedded metadata.

| Param      | Type | Default | Description            |
| ---------- | ---- | ------- | ---------------------- |
| `page`     | int  | 1       | Page number            |
| `per_page` | int  | 25      | Items per page (1–100) |

**Response:** the same paginated envelope as `GET /api/books`.

### `POST /api/review/{book_id}/pin`

Pin a corrected field value permanently.

```json
{ "field": "title", "value": "The Corrected Title" }
```

`field` must be one of `title`, `subtitle`, `authors`, `publisher`,
`publication_year`, `isbn_10`, `isbn_13`, `language`, `description`,
`summary`, `categories`, `themes`, `keywords`, `cover_path` — anything else is
a `400`. Returns the updated `Book`, or `404` if it does not exist.

### `POST /api/review/{book_id}/resolve`

Mark a record as reviewed.

```json
{ "resolution": "confirmed" }
```

---

## Operations

### `GET /api/health`

Liveness, plus the three facts worth knowing before blaming the UI.

```json
{
  "status": "ok",
  "version": "1.1.0",
  "books": 544,
  "embeddings_loaded": true,
  "database": "/path/to/data/catalog.db"
}
```

`embeddings_loaded: false` means semantic and hybrid search have nothing to
rank against.

---

## Static Assets

| Path              | Description                                                       |
| ----------------- | ----------------------------------------------------------------- |
| `/covers/{file}`  | Book cover images. `Cache-Control: public, max-age=604800`, plus `ETag`/`Last-Modified` conditional requests |
| `/assets/{file}`  | Built frontend assets                                             |
| `/*`              | Frontend SPA (React app)                                          |

Paths under `/api/` and `/covers/` are excluded from the SPA fallback and
return a JSON `404` rather than the app shell. The fallback resolves and
containment-checks every candidate path, so it cannot serve a file outside
`frontend/dist`.

---

## Error Responses

All errors return JSON:

```json
{
  "detail": "Book not found"
}
```

Common HTTP status codes:
- `400` — Bad request (e.g. an empty `PATCH` body, an unpinnable field)
- `404` — Resource not found
- `409` — Conflict: a pipeline or embedding run is already in progress
- `422` — Request validation failed (wrong parameter type, unknown body field)
- `500` — Internal server error
