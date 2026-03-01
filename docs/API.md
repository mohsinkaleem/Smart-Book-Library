# API Documentation

> Base URL: `http://localhost:8000`  
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
| `sort`            | string | `title`  | Sort field (`title`, `date_added`, `publication_year`, `size`, `authors`) |
| `order`           | string | `asc`    | Sort direction (`asc` or `desc`)         |
| `file_type`       | string | —        | `pdf` or `epub`                          |
| `category`        | string | —        | Filter by category name                  |
| `theme`           | string | —        | Filter by theme name                     |
| `author`          | string | —        | Filter by author name                    |
| `language`        | string | —        | Filter by language code (e.g. `en`)      |
| `reading_status`  | string | —        | `not_started`, `in_progress`, `finished`, `abandoned` |
| `has_cover`       | bool   | —        | Filter by cover availability             |
| `has_description` | bool   | —        | Filter by description availability       |
| `year_min`        | int    | —        | Minimum publication year                 |
| `year_max`        | int    | —        | Maximum publication year                 |
| `rating_min`      | int    | —        | Minimum user rating (1–5)               |
| `favorite`        | bool   | —        | Filter favorites only                    |
| `tag`             | string | —        | Filter by user tag                       |
| `search`          | string | —        | Quick text search filter                 |

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

---

### `GET /api/books/{book_id}/similar`

Get semantically similar books using embedding cosine similarity.

| Param    | Type   | Default    | Description                |
| -------- | ------ | ---------- | -------------------------- |
| `limit`  | int    | 8          | Max results (1–20)         |
| `method` | string | `combined` | `combined`, `semantic`     |

**Response:** Array of `Book` objects with `similarity_score`.

---

### `GET /api/books/{book_id}/text`

Get the text excerpt for a book.

**Response:**

```json
{
  "id": "abc123...",
  "title": "Book Title",
  "text": "Extracted text content up to ~5000 characters..."
}
```

---

### `PATCH /api/books/{book_id}`

Update book metadata fields.

**Request Body:** JSON object with fields to update. Accepts any book field name.

---

## Search

### `GET /api/search`

Full-text and/or semantic search across the library.

| Param      | Type   | Default  | Description                                    |
| ---------- | ------ | -------- | ---------------------------------------------- |
| `q`        | string | required | Search query                                   |
| `mode`            | string | `text`   | `text` (full-text), `semantic`, or `hybrid`    |
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
- **`text`** — SQLite FTS5 with Porter stemmer. Matches against title, authors, description, themes, categories, keywords, and publisher. Supports prefix matching, quoted phrase queries, OR operators, and column-scoped search (e.g. `title:python`).
- **`semantic`** — Encodes the query with `all-MiniLM-L6-v2` and finds nearest neighbors via cosine similarity. Requires embeddings to be generated.
- **`hybrid`** — Runs both FTS5 and semantic, then merges and re-ranks results (40% FTS + 60% semantic weighting).

All search modes support the full set of filter parameters, applied server-side.

**Response:** Same paginated format as `GET /api/books`. Each item includes `_score` and `match_type` fields.

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
| `language`        | string | Filter by language code                  |
| `reading_status`  | string | Filter by reading status                 |
| `favorite`        | string | `true` to filter favorites               |
| `has_cover`       | string | `true` to filter books with covers       |
| `has_description` | string | `true` to filter books with descriptions |
| `year_min`        | string | Minimum publication year                 |
| `year_max`        | string | Maximum publication year                 |
| `author`          | string | Filter by author name                    |
| `tag`             | string | Filter by user tag                       |

When called with no parameters, returns unfiltered global facet counts.

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

### Individual Facet Endpoints

| Endpoint                  | Returns            |
| ------------------------- | ------------------ |
| `GET /api/filters/categories` | Category facets |
| `GET /api/filters/themes`     | Theme facets    |
| `GET /api/filters/authors`    | Author facets   |
| `GET /api/filters/languages`  | Language facets |
| `GET /api/filters/years`      | Year facets     |
| `GET /api/filters/tags`       | User tag facets |

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
  "avg_rating": null,
  "categories_top": [...],
  "languages": [...]
}
```

### `GET /api/stats/reading`

Reading progress statistics.

---

## Reading

### `GET /api/reading/llm-status`

Check if Ollama is running and available.

**Response:**

```json
{ "available": true }
```

### `GET /api/reading/{book_id}/text`

Get book text for the reading view (same as `/api/books/{id}/text`).

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
  "action": "summarize"      // explain | summarize | compare | critique | related
}
```

**Response:** `text/event-stream` with chunked tokens:

```
data: {"token": "This "}
data: {"token": "passage "}
data: {"token": "discusses..."}
data: [DONE]
```

---

## User

### `PATCH /api/user/books/{book_id}`

Update user-specific fields for a book.

**Request Body:**

```json
{
  "reading_status": "in_progress",
  "progress_percent": 45,
  "user_rating": 4,
  "user_tags": ["favorites", "technical"],
  "favorite": true
}
```

All fields are optional. Only provided fields are updated.

---

## Pipeline

### `GET /api/pipeline/status`

Get current pipeline run status.

### `POST /api/pipeline/run`

Trigger a catalog re-processing run.

**Request Body:**

```json
{
  "force": false,            // Re-process already processed books
  "book_ids": ["abc123"]     // Optional — process specific books only
}
```

### `POST /api/pipeline/generate-embeddings`

Start embedding generation for all books with text.

### `GET /api/pipeline/embedding-status`

Check embedding generation progress.

### `GET /api/pipeline/unprocessed`

List books that haven't been processed yet.

---

## Static Assets

| Path              | Description              |
| ----------------- | ------------------------ |
| `/covers/{file}`  | Book cover images        |
| `/*`              | Frontend SPA (React app) |

---

## Error Responses

All errors return JSON:

```json
{
  "detail": "Book not found"
}
```

Common HTTP status codes:
- `400` — Bad request / invalid parameters
- `404` — Resource not found
- `500` — Internal server error
