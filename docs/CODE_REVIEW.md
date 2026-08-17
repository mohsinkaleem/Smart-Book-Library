# Code Review — Frontend & Backend

> ## Status — second remediation pass, 2026-08-17
>
> **§0 through §6 are now implemented**, bar the four exceptions named at the
> bottom of this box. Findings below are annotated inline; the original text is
> unchanged, so the tense still reads as it did at review time.
>
> | Marker | Meaning |
> | --- | --- |
> | ✅ **FIXED** | Implemented and verified. |
> | ⏭️ **OUT OF SCOPE** | §5/§6 work, deliberately not attempted in the *first* pass. Nearly all of it landed in the second — see below. |
> | ⚠️ **DEFERRED** | Judged too risky or low-value to land; reason given. |
>
> **Verified after this pass:** `pytest` 132 passed (111 after the first pass,
> 63 before it); `tsc -b` clean; `npm run lint` 0 errors; `npm run build`
> succeeds; every endpoint exercised against the real `data/catalog.db` (now
> 544 books) on port 8123; all four themes, the readers' progress persistence
> and the search snippets confirmed in a browser.
>
> ### What the second pass added
>
> **§5 — features.** Reading progress and reader position are persisted by both
> readers and feed a *Continue reading* shelf and a *Resume at n%* button
> (`useReadingProgress`, `user_data.reader_position`). Tags are creatable and
> removable on the book page, with the existing vocabulary suggested back.
> Duplicates are counted on the dashboard and flagged on the book page. The
> unprocessed-file count is on the Settings page, next to a real progress bar
> driven by `task_tracker`. **Book text is now indexed** — a second FTS5 table,
> `book_text_fts`, over `text_excerpt`/`front_matter`/`content_sample`, blended
> with the metadata index at 0.35 weight — and results carry `snippet()`
> highlights. `hybrid` is the default mode in the server, the UI and the
> README. Language facets are normalised to ISO-639-1 with an `unknown` bucket.
> The LLM buttons gate on `/api/reading/llm-status` and say which of "Ollama is
> down" and "the model is not pulled" applies. `GET /api/health` exists and
> `/covers` sends `Cache-Control`.
>
> **§6 — gaps.** `docs/API.md` and `README.md` are reconciled against the code,
> including every row of the drift table. `.env.example` exists. CI
> (`.github/workflows/ci.yml`) runs `pytest`, `tsc -b`, `npm run lint` and
> `npm run build`. The suggestion dropdown is a real `combobox`/`listbox` with
> `aria-activedescendant`.
>
> **Beyond the review:** the app has four themes rather than two — Light, Dark,
> **Paper** (warm sepia) and **Dim** (soft dark) — implemented by redefining
> Tailwind's colour variables per `data-theme`, so no component changed. `d`
> cycles them.
>
> ### Two things this pass changed that the review did not ask for
>
> 1. **Semantic search now has a relevance floor** (`MIN_SEMANTIC_SCORE`, plus
>    55% of the best score). §1.4's fix made `total` the true number of scored
>    books — which, with `hybrid` as the new default, meant "496 books" for
>    almost any query, because every book scores above zero against every
>    query. The floor is what makes "no results" possible. It cannot suppress
>    an exact keyword match: the FTS side is unioned in afterwards.
> 2. **`get_books` now shares `_apply_filters`** instead of re-implementing
>    every predicate inline. That was the remaining half of §4.2, and it fixed
>    a live divergence: `has_cover=false` was honoured by the list endpoint and
>    ignored by search. Booleans are symmetric in both now.
>
> ### Still outstanding
>
> 1. **Rotate the Google Books API key (§0.1)** — not a code change. The
>    handler that exposed it is closed; the key itself has not been rotated.
> 2. ⚠️ **`BookCover`'s canvas sampling** (§2.11) — wants a column computed by
>    the cover pipeline, and `catalog/` extraction stays out of scope.
> 3. ⚠️ **The `books`/`user_data` VIEW** (§4.10) — would require renaming the
>    table and rewriting every write path including the pipeline's.
> 4. ⚠️ **The `vite` beta pin** (§3) — moving off a beta major risks the build
>    for no correctness gain.
>
> Not attempted, and not previously promised: bulk select, a virtualised grid
> (its dependency was removed as dead in the first pass), and frontend test
> infrastructure — there are still no frontend tests.
>
> **Two defects the original review missed**, found while verifying §2.9 in a
> browser — both pre-existing, both fixed in the first pass:
> 1. **The EPUB reader never opened a book.** epub.js reads the URL extension
>    to choose its loader; `/api/books/{id}/file` has none, so it assumed an
>    *unpacked* EPUB directory and 404'd fetching `META-INF/container.xml`.
>    A `.epub` route alias fixes it.
> 2. **EPUB text selection never reached the sidebar.** The handler called
>    `window.getSelection()` on the *parent* window, which is always empty for
>    a selection inside the iframe — and the fallback listener polled for
>    `.ReactReader iframe`, a selector react-reader never renders.

**Date:** 2026-08-17
**Scope:** `server/`, `frontend/`, `main.py`, project config, docs.
**Out of scope (by request):** the catalog enrichment pipeline (`catalog/` extraction, providers, evidence, taxonomy, LLM enrichment). `catalog/schema.py`, `catalog/store.py` and `catalog/user_data.py` are covered only where the server calls into them.

**Catalog state at review time:** 212 books (175 PDF, 37 EPUB), 212 embeddings, 188 covers, 194 descriptions, 58 flagged `needs_review`, 0 rows in `user_data`. 618 files on disk, **406 of them not yet in the catalog**.

**How this was verified:** ran the server on port 8123 against the real `data/catalog.db` and exercised every endpoint with `curl`; ran `pytest` (63 passed), `tsc -b` (clean), and `eslint` (11 errors); read every file in `server/` and `frontend/src`.

---

## 0. Fix this first

### 0.1 Arbitrary file read over HTTP (path traversal)

> ✅ **FIXED** — `server/app.py` resolves the candidate and requires it to sit
> inside `frontend/dist`. All three probes now return the SPA shell; verified
> against the running server. Covered by `tests/test_server.py::test_spa_fallback_cannot_escape_dist`.
> ⚠️ **The key rotation is still outstanding** — deferred by the maintainer as
> low risk given the default `127.0.0.1` binding.

`server/app.py:84-90`

```python
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    file_path = FRONTEND_DIST / full_path   # ← full_path is attacker-controlled
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
```

`full_path` is joined onto `FRONTEND_DIST` with no containment check. URL-encoded `../` segments survive Starlette's path normalisation, so the handler happily serves **any file the server process can read**.

Verified against the running server:

| Request | Result |
| --- | --- |
| `GET /..%2f..%2f.env` | served `.env` in full, **including `GOOGLE_BOOKS_API_KEY`** |
| `GET /..%2f..%2fdata%2fcatalog.db` | served the SQLite database (5 MB) |
| `GET /..%2f..%2f..%2f..%2f..%2f..%2f..%2fetc%2fpasswd` | served `/etc/passwd` |

The `/covers` mount uses Starlette `StaticFiles`, which *is* protected — the same probe returns 404 there. Only the hand-rolled SPA fallback is vulnerable.

Default binding is `127.0.0.1`, which limits this to local processes — but `main.py --network` binds `0.0.0.0` and the README advertises it for LAN access. On that path, anyone on the network can read arbitrary files from the machine.

**Two actions:**

1. **Rotate the Google Books API key.** It has been served over HTTP by this endpoint. `.env` is correctly gitignored and was never committed (verified against git history), so the repo is clean — the leak vector is purely this handler.
2. **Contain the path.** Resolve and verify before serving:

```python
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    index = FRONTEND_DIST / "index.html"
    try:
        candidate = (FRONTEND_DIST / full_path).resolve()
        candidate.relative_to(FRONTEND_DIST.resolve())   # raises if outside
    except (ValueError, OSError):
        return FileResponse(str(index))
    if candidate.is_file():
        return FileResponse(str(candidate))
    return FileResponse(str(index))
```

A three-line `TestClient` test would have caught this and will stop it coming back.

---

## 1. Backend bugs

### 1.1 `GET /api/books?search=…` returns 500 on ordinary input

> ✅ **FIXED** — the strict builder moved to `catalog/fts.py` and is now the
> only one; `server/db.py::_build_fts_query` is deleted and `catalog/store.py`
> imports the shared version. Note the trade-off this makes explicit: quoted
> phrases, `OR`, and `title:` column syntax are no longer honoured as
> operators — every token is quoted literally, with optional prefix matching.

`server/db.py:214-216`

```python
if search:
    where_clauses.append("id IN (SELECT ... WHERE books_fts MATCH ?)")
    params.append(search)          # ← raw user input straight into MATCH
```

Every other search path runs input through `_build_fts_query`; this one does not. Any FTS5 metacharacter blows up the query.

Verified: `GET /api/books?search=self-help` → **500**. `GET /api/books?search=AND` → **500**.

Note that `catalog/store.py:53` already contains a *correct* sanitiser (`_fts_query`, which regex-tokenises and quotes every term). So the project has **two divergent FTS query builders**, and the server uses the unsafe one. Consolidate on the strict version and route `get_books(search=…)` through it.

### 1.2 `GET /api/filters?year_min=abc` returns 500

> ✅ **FIXED** — typed `Optional[int]` in the shared dependency
> (`server/routes/params.py`), so all three endpoints return 422. `_as_year`
> in `db.py` guards the DB layer as well.

`server/routes/filters.py:18-19` types `year_min`/`year_max` as `Optional[str]`, and `server/db.py:519-524` calls `int(f["year_min"])` on it with no guard. Verified: 500. Declare them `Optional[int]` and let FastAPI return a 422, or coerce defensively.

### 1.3 Unknown `/api/*` paths return `index.html` with status 200

> ✅ **FIXED** — the SPA fallback raises 404 for `api/` and `covers/` prefixes.

The SPA catch-all is registered after the routers but matches everything the routers didn't. Verified: `GET /api/nope` → **200 `text/html`**, `GET /api/books/x/y/z` → **200 `text/html`**.

The frontend's `client.ts` checks `res.ok` then calls `res.json()` — so a typo'd or renamed endpoint surfaces as `Unexpected token '<'` instead of a 404. Exclude `/api` (and `/covers`) from the fallback:

```python
if full_path.startswith(("api/", "covers/")):
    raise HTTPException(404, "Not found")
```

### 1.4 Semantic and hybrid search are capped at 200 results, and `total` lies

> ✅ **FIXED** — `semantic_search` ranks the whole matrix (`limit=None`),
> filters are applied in SQL, and `_page()` hydrates one page via a single
> `get_books_by_ids` round-trip instead of N `get_book()` calls. `?mode=semantic`
> now reports a real total (205 against the live catalog, not the 200 cap).

`server/search.py:50, 79, 89` all hard-code `limit=200`. `total` is then computed from that truncated list.

Verified: `GET /api/search?q=islam&mode=semantic&per_page=1` reports `total: 200, pages: 200` — the number 200 is the cap, not a real count. The equivalent text search reports `total: 80`.

Worse, pagination re-runs the entire scan: page 5 recomputes all 200 similarities and all 200 `get_book()` round-trips, then slices. With 212 books that is invisible; it stops being invisible around a few thousand.

Fix: score the whole matrix (it is one `numpy` matmul over ~212×384 — cheap), apply filters in SQL rather than per-row in Python, and paginate over the true result set.

### 1.5 The `tag` filter is silently ignored in semantic and hybrid mode

> ✅ **FIXED** — `search._matches_filters` is deleted. Semantic and hybrid
> intersect their candidates with `db.filtered_ids(**filters)`, so there is one
> filter implementation (SQL). Covered for all three modes by
> `test_tag_filter_is_not_ignored`.

`server/routes/search.py:52-53` accepts `tag`; `server/search.py:132-166` `_matches_filters` has branches for `file_type`, `category`, `theme`, `language`, `reading_status`, `favorite`, `has_cover`, `has_description`, `year_min`, `year_max`, `author` — **and no branch for `tag`**. Verified: `?mode=semantic&tag=foo` returns 200 with unfiltered results.

This is a symptom of a bigger duplication: filter logic exists twice, once as SQL (`db._apply_filters`) and once as Python predicates (`search._matches_filters`), and they have already drifted. Push semantic/hybrid filtering into SQL (filter the candidate ID set) and delete `_matches_filters`.

### 1.6 Passage comparison uses *metadata* embeddings, not *content* embeddings

> ✅ **FIXED** — added `SimilarityEngine.passage_search`, scoring against
> `content_matrix`; `/api/reading/compare` uses it. The search box keeps
> metadata scoring, as recommended.

`server/similarity.py:157-164`:

```python
def semantic_search(self, query_embedding, limit=20):
    scores = self.metadata_matrix @ query_embedding
```

`POST /api/reading/compare` sends a selected passage of prose and compares it against embeddings of `"Title: … Authors: … Description: … Themes: …"` (built in `catalog/embeddings.py:101-122`). Content embeddings *are* generated and *are* loaded into `content_matrix` — they are simply never used for this.

That is why "Similar in Other Books" tends to return topical near-misses rather than passages that actually resemble the selection. For `/api/reading/compare`, score against `content_matrix` (or blend the two). Metadata-only is defensible for the search box; it is the wrong index for a passage.

### 1.7 Blocking HTTP inside an `async` generator blocks the event loop

> ✅ **FIXED** — `httpx.AsyncClient` with `client.stream(...)` and
> `aiter_lines()`. Closing the panel now tears down the upstream request, so
> Ollama stops generating into a dead socket. Model and base URL are
> configurable via `OLLAMA_MODEL` / `OLLAMA_BASE_URL`.

`server/llm_service.py:41-63` — `analyze_text_stream` is `async def` but uses synchronous `requests.post(..., stream=True)` and a blocking `for line in resp.iter_lines()`. Because the route returns a `StreamingResponse` over this generator, **the whole server stalls for the duration of every LLM generation** (potentially 120 s). One user hitting "Explain" freezes everyone else's page loads.

Fix with `httpx.AsyncClient` (`async with client.stream(...)`), or run the sync generator through a threadpool. While you are in there: nothing detects client disconnect, so closing the panel mid-stream leaves Ollama generating to a dead socket.

### 1.8 One unguarded SQLite connection shared across every thread

> ✅ **FIXED** — `BookDatabase` takes a `threading.RLock` and a 30 s busy
> timeout, matching `CatalogStore`. Reads go through new `query`/`query_one`
> helpers; the callers that reached for `db.conn` directly were updated.

`server/db.py:54` opens with `check_same_thread=False` and no lock. FastAPI runs all these sync route handlers in a threadpool, *and* `server/tasks.py` spawns background pipeline/embedding threads that touch the same DB. `catalog/store.py:68-74` — same file, same project — does this properly with a `threading.RLock`. The server side should match, or move to a per-request connection.

### 1.9 Connection leak on `/api/pipeline/report`

> ✅ **FIXED** — `try/finally` closes the store in both places. Verified: open
> `catalog.db` handles stay flat across 10 consecutive requests.

`server/routes/pipeline.py:83-88` calls `build_report(CatalogStore())`. `CatalogStore.__init__` opens a new SQLite connection and runs `ensure_schema`; nothing ever calls `.close()`. Every hit of this endpoint leaks a connection and a file handle. Same pattern in `server/tasks.py:143`. Use a `try/finally` or a context manager.

### 1.10 `PATCH` on a nonexistent book leaves an orphan row

> ✅ **FIXED** — `update_user_fields` checks the book exists inside the lock
> before writing. Covered by `test_patch_unknown_book_404s_without_orphaning_a_row`.

`catalog/user_data.py:55-65` — `_ensure_row` INSERTs into `user_data` before anything confirms the book exists. Verified: `PATCH /api/books/doesnotexist` correctly returns 404 *and* leaves a junk `user_data` row behind (I cleaned mine up). Check book existence first.

### 1.11 `/api/stats` counts records the rest of the app hides

> ✅ **FIXED** — every count in `get_stats` carries `status != 'missing'`,
> including `by_type`, `by_status`, the histogram, the category/theme counts
> and `recently_processed`. `test_stats_totals_match_the_library` pins it.

`server/db.py:606-669` — `get_stats` has no `status != 'missing'` predicate, while `get_books` (`db.py:173`) and `get_review_queue` (`db.py:272`) both do. The moment a file is deleted from disk and marked missing, the dashboard total will disagree with the library total, permanently. Same for `by_type`, `by_status`, `year_histogram`, `recently_processed` and the category/theme counts.

### 1.12 `/api/books/{id}/file` resolves a relative path against the process CWD

> ✅ **FIXED** — joined against `PROJECT_ROOT` and containment-checked, so the
> server can be started from anywhere.

`server/routes/books.py:97` — `Path(book.get("file_path", ""))` is a *relative* path (`pdfs/…`) stored in the DB. `FileResponse` resolves it against whatever directory uvicorn was started from. Start the server from anywhere but the project root and every "Read Book" click 404s. Join against `PROJECT_ROOT` explicitly.

### 1.13 Minor

> ✅ **FIXED** (3 of 4) — `/similar` on an unknown id now 404s;
> `load_embeddings` validates each blob's shape and substitutes a zero vector
> with a warning rather than raising; a JSON exception handler returns
> `{"detail": …}` and logs the request path.
> ⚠️ **DEFERRED: the `embeddings` foreign key.** Adding it to `catalog/schema.py`
> would only affect freshly created databases — SQLite cannot add a FK to an
> existing table without a full rebuild, and `catalog/schema.py` was outside
> this pass's scope. Orphan embedding rows remain possible.

- `GET /api/books/{id}/similar` on an unknown ID returns `200 []` instead of 404 (`routes/books.py:58-66`) — `find_similar` never checks the book exists.
- `SimilarityEngine.load_embeddings` (`similarity.py:33-47`) does `np.frombuffer` with no length check; one truncated blob makes `np.vstack` raise at startup and kills the whole similarity feature.
- Embeddings are never deleted when a book is removed — `embeddings` has no FK to `books` (`catalog/schema.py:129-135`) even though `PRAGMA foreign_keys=ON` is set.
- `500` responses are plain-text `Internal Server Error`; `docs/API.md:381-389` promises JSON `{"detail": …}`. Add an exception handler.

---

## 2. Frontend bugs

### 2.1 React hooks called conditionally

> ✅ **FIXED** — replaced by `usePagedBooks` (§4.7), which calls both hooks
> unconditionally and lets `enabled` decide which one fetches.

`frontend/src/pages/HomePage.tsx:39-41`

```tsx
const booksQuery = searchQuery
  ? useSearch({ ... })
  : useBooks(queryParams);
```

Two `rules-of-hooks` errors from eslint. This only works today because both branches happen to call the same number of hooks internally — a version bump of TanStack Query that changes either implementation turns this into "Rendered more hooks than during the previous render". Call both unconditionally and let `enabled` decide:

```tsx
const searchResult = useSearch({ q: searchQuery, enabled: !!searchQuery, ... });
const listResult   = useBooks({ ...queryParams, enabled: !searchQuery });
const booksQuery   = searchQuery ? searchResult : listResult;
```

### 2.2 `npm run lint` fails — 11 errors

> ✅ **FIXED** — `npm run lint` exits 0. The memoization warnings were resolved
> by hoisting `textData?.text` to a local and by destructuring the stable
> `mutate` out of `useCompare()` rather than depending on the mutation object.

Nobody is running it. Full list:

| File | Issue |
| --- | --- |
| `pages/HomePage.tsx:40,41` | `useSearch`/`useBooks` called conditionally |
| `pages/HomePage.tsx:34,40,63` | unused `_` in destructuring (×3) |
| `components/reading/ReadingView.tsx:27,44` | React Compiler could not preserve manual memoization (`[textData?.text]` vs inferred `textData.text`) |
| `components/reading/LLMPanel.tsx:19,63` | unused `_bookTitle`, unused `err` |
| `components/reading/BookReader.tsx:736` | unused `_contents` |

`tsc -b` is clean, so the build passes — which is exactly why these have accumulated.

### 2.3 The page number is not reset when the search or filters change

> ✅ **FIXED** — search, mode and filters moved into the URL alongside `page`
> (`useLibraryParams`); anything that changes the result set resets `page`.
> Note the subtlety: the reset must be a no-op when nothing actually changed,
> or `SearchBar`'s mount-time `onChange('')` strips `page` out of a bookmarked
> URL before the first render finishes. Verified in a browser both ways.

`HomePage.tsx:22` reads `page` from the URL; `searchQuery` and `filters` live in `AppShell` React state. Search from page 3 and you get page 3 of the new result set — usually blank, with working "Previous"/"Next" buttons and no explanation. Reset `page=1` whenever the query or filter set changes.

### 2.4 Dark-mode toggle desyncs from its own icon

> ✅ **FIXED** — one external store (`useDarkMode`, via `useSyncExternalStore`)
> owns the class, the storage key and the state. Verified in a browser: `d`
> and the header button now agree in both directions.

Two independent sources of truth:

- `App.tsx:60-64` — `toggleDark` reads the DOM class, flips it, writes `localStorage` directly. Bound to the `d` shortcut.
- `Header.tsx:16-25` — keeps its own `useLocalStorage('darkMode')` React state, initialised once from the DOM.

Press `d`: theme flips, `Header`'s state doesn't, so the sun/moon icon now shows the wrong thing. Click the header button next and it toggles from the *stale* value — the theme appears to not respond. Lift this into one hook (or a tiny context) used by both.

### 2.5 `j` / `k` are documented but do nothing

> ✅ **FIXED** — wired to the HomePage pagination via `onNextPage`/`onPrevPage`,
> clamped to the real page count. `g r` for the review queue was added too.

`hooks/useKeyboardShortcuts.ts:20-21` lists "j — Next page" / "k — Previous page", and the shortcuts dialog renders them. `App.tsx:66-72` never passes `onNextPage`/`onPrevPage`, so `useKeyboardShortcuts.ts:94-103` calls `undefined?.()`. Either wire them to the HomePage pagination or drop them from `SHORTCUTS`.

### 2.6 Global shortcuts collide with reader shortcuts

> ✅ **FIXED** — `useKeyboardShortcuts` takes `enabled`, and `AppShell` passes
> `false` on `/reader/*` routes, so only the reader's handler is live there.

`useKeyboardShortcuts` is mounted in `AppShell` on *every* route, including `/reader/*`, where `useReaderKeyboard` is also listening on `window`. Both are live at once:

| Key | Global handler | Reader handler | Result |
| --- | --- | --- | --- |
| `Escape` | `navigate(-1)` | `navigate('/books/:id')` | both fire — history goes somewhere unpredictable |
| `t` | toggle library sidebar | toggle EPUB TOC | both toggle |
| `j` / `k` | (dead) | page turn | works, by luck |
| `d`, `1`, `2` | theme / grid / list | — | fire inside the reader, where they mean nothing |

Gate `useKeyboardShortcuts` on the route, or have the reader stop propagation.

### 2.7 `useState(() => …)` used as an effect — one of them is a real functional bug

> ✅ **FIXED** — both are real effects now. Fixing `ReaderSidebar` alone did
> *not* revive the panel: EPUB selection was broken by two further defects this
> review did not catch (see the status header). All three are fixed, and the
> panel was confirmed populating in a browser.

Two places call `useState` with a side-effecting initialiser instead of `useEffect`:

- `BookReader.tsx:465-473` — dynamic `import('react-reader')`. Under `StrictMode` the initialiser runs twice, so the module is imported twice on every mount.
- `ReaderSidebar.tsx:46-50` — "Auto-compare when selected text changes". **It never re-runs.** `selectedText` is empty on first mount (the sidebar opens *because* text was selected, but the prop arrives on the following render), so the comparison fires with nothing and never fires again. The "Similar in Other Books" panel in the PDF/EPUB reader is therefore permanently empty. `ReadingView.tsx:32-42` gets this right with a real handler — the reader path does not.

### 2.8 Stale closure in the EPUB `getRendition` callback

> ✅ **FIXED** — `getRendition` is a stable `useCallback` reading `fontSize`
> through a ref; the `selected` handler no longer tests `sidebarOpen` at all
> (it always opens the sidebar), and the other selection handlers use the
> functional `setSidebarOpen(true)`.

`BookReader.tsx:713-744` captures `fontSize` and `sidebarOpen` from the render in which it was created. `rendition.themes.fontSize(\`${fontSize}%\`)` applies the initial 100% regardless of what the user set beforehand, and the `selected` handler tests a frozen `sidebarOpen`. Use refs (there is already a `renditionRef` next door) or functional updates.

### 2.9 A "local-first" app that needs the internet to open a PDF

> ✅ **FIXED** — vendored exactly as suggested; `pdfjs-dist` is now a direct
> dependency rather than a transitive one. Confirmed in a browser: the worker
> loads from `/assets/pdf.worker.min-*.mjs`, no request to unpkg.

`BookReader.tsx:27`

```ts
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;
```

Offline — or on a locked-down network — the PDF reader silently fails. Also a protocol-relative URL, so it breaks under `file://`. Vendor the worker instead:

```ts
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;
```

### 2.10 Query errors are invisible

> ✅ **FIXED** — `common/ErrorBoundary` now exists (wrapping every route) and
> exports a shared `ErrorState`. `isError` branches added to HomePage,
> BookPage, Dashboard, ReadingView and both readers. `client.ts` surfaces the
> API's `{"detail": …}` and aborts after 30 s.

Only `ReviewPage.tsx:127` handles `isError`. Elsewhere:

- `HomePage` — a failed fetch leaves `data` undefined, so `data?.items.length === 0` is false and it renders `BookGrid books={[]}` → a silent blank page.
- `BookPage` — renders "Book not found" for a network failure.
- `Dashboard` — `return null`, a blank screen.
- `ReadingView` — falls through to "No Text Available", blaming the book for a server error.

`README.md:176` claims a `common/ErrorBoundary` exists. It does not — `src/components/common/` contains Badge, EmptyState, KeyboardShortcutsDialog, Rating, Spinner. Add one, plus `isError` branches.

### 2.11 Smaller frontend items

> ✅ **FIXED** — `NaN%` (guarded), `SortSelector` (replaced by a "Sorted by
> relevance" note while searching), `perPage` (one size, 48, for both views),
> `BookCard` (link overlay instead of a nested button), URL-backed filters, and
> `client.ts` (conditional `Content-Type`, plus an abort timeout).
> ⚠️ **DEFERRED: `BookCover` canvas sampling.** The right fix is a column
> computed by the cover pipeline, and `catalog/` was outside this pass's scope.
> Still 48 `getImageData` calls per grid page.

- `Dashboard.tsx:27` — `stats.with_cover / stats.total_books` renders `NaN%` on an empty library.
- `SortSelector` stays visible and clickable while searching, but `/api/search` has no `sort` parameter — the control is inert in exactly the mode where ordering matters most.
- `HomePage.tsx:25` — `perPage` changes with the view (48 grid / 100 list), so toggling views while deep in pagination can land you past the last page.
- `BookCover.tsx:32-69` — every cover is decoded into a canvas and pixel-sampled on load to detect blank/spine images. That is 48 `getImageData` calls per grid page to work around bad data in the catalog; the check belongs in the cover pipeline, with the result stored as a column.
- `BookCard.tsx:37` — a `<button>` nested inside a `<Link>`. It works via `preventDefault`, but it is invalid HTML and confusing for keyboard/screen-reader users.
- Filters and the search query live in React state, not the URL, while `page`/`sort`/`order` live in the URL. A filtered view can't be bookmarked or shared and is lost on refresh. Pick one model — the URL is the right one.
- `client.ts` sets `Content-Type: application/json` on GETs too, and has no timeout/abort.

---

## 3. Stale and dead code

> ✅ **FIXED — every backend and frontend item in this section is deleted.**
> `analyze_text`, the five `config.py` constants (three of which are now *used*
> by `main.py` and the routes rather than deleted), `PATCH /api/user/books/{id}`
> (whole module), `GET /api/books/{id}/text`, `GET /api/stats/reading`,
> `GET /api/review/fields`, the six facet endpoints, `_count_json_array_field`,
> and `server/migrate.py` (with its `--migrate` flag and README references).
> Frontend: `@headlessui/react`, `@tanstack/react-virtual`, the Zustand claim,
> `StatsPage`/`ReadingPage`, `setActiveAction`, `dropdownRef`, `truncate`,
> `.skeleton`. `tests/test_server.py::test_removed_endpoints_are_gone` keeps
> them gone.
>
> `GET /api/reading/llm-status` is the **one deliberate exception** — kept
> rather than deleted, because §5 wants the LLM buttons gated on it. It is
> still uncalled.
>
> **Repo hygiene:** `requirements.txt` and `pyproject.toml` reconciled (pyproject
> is now stated as the source of truth; the `pytest` disagreement resolved in
> favour of the `dev` extra; the `uv sync` / `--extra embed` trap documented).
> `frontend/README.md` replaced. The `.DS_Store` files turned out **not** to be
> tracked — `git ls-files` shows none, so nothing to untrack.
> ⚠️ **DEFERRED: the `vite` beta pin.** Moving off a beta major risks the build
> for no correctness gain; left as-is with the `overrides` entry intact.

### Backend

| Item | Location | Note |
| --- | --- | --- |
| `analyze_text` (non-streaming) | `llm_service.py:25-38` | defined, imported at `routes/reading.py:8`, never called |
| `DEFAULT_HOST`, `DEFAULT_PORT`, `DEFAULT_PAGE_SIZE`, `MAX_PAGE_SIZE`, `TEXT_EXCERPTS_DIR` | `server/config.py:8-16` | all five unused — `main.py` and the routes hardcode the same numbers |
| `GET /api/reading/llm-status` | `routes/reading.py:25-27` | frontend never calls it (the LLM panel offers its buttons unconditionally and only fails on click) |
| `PATCH /api/user/books/{id}` | `routes/user.py` | frontend never calls it; duplicates `PATCH /api/books/{id}` with a stricter schema |
| `GET /api/books/{id}/text` | `routes/books.py:69-76` | byte-for-byte duplicate of `GET /api/reading/{id}/text`; only the latter is used |
| `GET /api/stats/reading` | `routes/stats.py:12-18` | never called |
| `GET /api/review/fields` | `routes/review.py:38-41` | never called |
| `/api/filters/{categories,themes,authors,languages,years,tags}` | `routes/filters.py:80-113` | six endpoints, none called. Each runs the **full** `get_filter_facets()` — ~7 aggregate queries — and discards all but one key |
| `_count_json_array_field` | `db.py:582-590` | identical to `_count_json_array_field_filtered` with `where='1=1'` |
| `server/migrate.py` | | one-time legacy `catalog.json` → SQLite import, still wired to `main.py --migrate` and documented in the README as if it were routine |

`routes/search.py:29-53` also hand-builds a filter dict with 25 lines of `if x: filters[...] = x`, duplicating `routes/filters.py::_collect_filter_params`. One shared FastAPI dependency replaces both.

### Frontend

| Item | Note |
| --- | --- |
| `@headlessui/react` | in `package.json`, imported nowhere |
| `@tanstack/react-virtual` | in `package.json`, imported nowhere |
| Zustand | listed in `README.md:27` as the state layer — **not installed and not used**; state is `useState` + `useLocalStorage` |
| `pages/StatsPage.tsx`, `pages/ReadingPage.tsx` | 5-line pass-throughs to a single component |
| `LLMPanel.tsx:22` | `const [, setActiveAction] = useState(...)` — the value is written and never read |
| `SearchBar.tsx:26` | `dropdownRef` assigned, never read |
| `utils/format.ts:19` | `truncate` never imported |
| `index.css:55-59` | `.skeleton` class defined, never used |

### Repo hygiene

- `requirements.txt` and `pyproject.toml` are two hand-maintained dependency lists that have already drifted — `pytest` is a core requirement in one and a `dev` extra in the other; `requirements.txt` comments out `sentence-transformers` while `uv sync` won't install it either, so the README's step 6 fails on a fresh install with no clear message.
- `.DS_Store` files committed at repo root, `frontend/`, `server/`, `epubs/`, `data/` (gitignored *now*, but four are tracked).
- `.playwright-cli/` (13 session dumps), `__pycache__/`, `.pytest_cache/` present in the working tree.
- `data/text_excerpts/` — empty, referenced by `server/config.py:8` and `README.md:212`, never written to.
- `frontend/README.md` is the stock Vite template.
- `vite: ^8.0.0-beta.13` with a matching `overrides` entry — a beta build tool pinned into the project.

---

## 4. Simplification opportunities

> ✅ **FIXED — 1 through 9.** One FTS builder (`catalog/fts.py`); one filter
> implementation (SQL only); one user-fields write path (typed
> `UserFieldsUpdate` on `PATCH /api/books/{id}` — note this keeps the *typed*
> schema but on the *books* route, and uses `exclude_unset` so an explicit
> `null` can still clear a rating); one query-param dependency
> (`routes/params.py`); facets collapsed; counters merged; `usePagedBooks`;
> `StatsPage`/`ReadingPage` deleted and routed direct; `<SimilarPassages />`
> extracted.
>
> ⚠️ **DEFERRED: 10, the `books`/`user_data` VIEW.** It would require renaming
> the table and rewriting every write path, including the pipeline's — too
> invasive to land safely alongside the rest of this pass. The mirrored
> columns and their divergence risk remain.

1. **One FTS query builder.** `server/db.py:420-454` (permissive, unsafe) and `catalog/store.py:53-62` (strict, safe) do the same job differently. Move the strict one somewhere shared and delete the other. Fixes §1.1 for free.
2. **One filter implementation.** `db._apply_filters` (SQL) and `search._matches_filters` (Python) have already diverged (§1.5). Filter in SQL only.
3. **One user-fields write path.** `PATCH /api/books/{id}` and `PATCH /api/user/books/{id}` reach the same function through different schemas. Keep the typed one, delete the untyped one, point the frontend at it.
4. **One query-param dependency.** `books.list_books`, `search.search_books` and `filters.get_all_filters` each re-declare ~14 identical `Optional[...]` parameters, with slightly different types (`favorite: bool` in two, `Optional[str]` in the third). A single Pydantic dependency removes ~60 lines and the type inconsistency.
5. **Collapse the six unused facet endpoints** into the one that is actually used.
6. **Merge `_count_json_array_field` into `_count_json_array_field_filtered`.**
7. **Frontend: one `usePagedBooks` hook** that internally decides search vs list. Removes the conditional-hook problem (§2.1) and shrinks `HomePage`.
8. **Delete `StatsPage.tsx` / `ReadingPage.tsx`** and route directly to `Dashboard` / `ReadingView`.
9. **Extract `<SimilarPassages matches={...} />`** — `ReadingView.tsx:211-238` and `ReaderSidebar.tsx:110-135` are the same 25-line block twice.
10. **The `books` table mirrors six user-owned columns from `user_data`** so old queries keep working. That is a deliberate, documented trade-off, but it means two rows can disagree if anything ever writes `books` directly. A `VIEW` joining the two tables would give the same query surface with one source of truth.

---

## 5. Improvements and features worth adding

> ✅ **IMPLEMENTED in the second pass**, except where noted below.
>
> Reading progress and reader position persist (`useReadingProgress` +
> `user_data.reader_position`), feeding a *Continue reading* shelf and a
> *Resume at n%* button. Tags are creatable and removable on the book page.
> Duplicates are counted on the dashboard and flagged on the book page. The
> unprocessed count sits on the Settings page beside a live progress bar. Book
> text is indexed in a second FTS5 table with `snippet()` highlights on
> results. `hybrid` is the default in all three places. Language values are
> normalised to ISO-639-1 with an `unknown` bucket. The LLM buttons gate on
> `/api/reading/llm-status`. `GET /api/health` exists; `/covers` sends
> `Cache-Control`.
>
> ⏭️ **Not done: bulk select and the virtualised grid.** The virtualisation
> dependency was deleted as dead in the first pass (§3), and re-adding it to
> virtualise a 48-item page is not worth it. Bulk select is a genuine gap.

### Things the schema already promises but nothing delivers

- **Reading progress is entirely inert.** `progress_percent` and `last_opened` exist in the schema, in `USER_FIELDS`, in the TypeScript `Book` type, and as a `sort=last_opened` option in `db.py:229` — and **nothing in the app ever writes either one**. The README advertises "reading status … with progress percentage". Wire the readers: `PATCH` `last_opened` on mount, `progress_percent` on page change (debounced). That unlocks a *Continue reading* shelf, a real "Recently opened" sort, and makes the `in_progress` status meaningful rather than manual.
- **Reader position is never saved.** The EPUB `location` is component state (`BookReader.tsx:450`) and the PDF page resets to 1. Reopening a 600-page book puts you back at the cover. Persist alongside progress.
- **User tags are filterable but uncreatable.** `user_tags` is stored, indexed, faceted in the sidebar and exposed as a `tag` filter — with no UI to add a tag to a book.
- **Duplicates are detected and hidden.** `duplicate_of` is computed by the pipeline, stored, indexed, and present in the TS type — and never rendered. A "3 possible duplicates" badge on the stats page would make that work visible.
- **406 of 618 files on disk are not in the catalog.** `GET /api/pipeline/unprocessed` reports this correctly and no page displays it. The Settings page has a "Process New Books" button that gives no indication there is anything to process. Surface the count.

### Search and discovery

- **Book text is not searchable.** `FTS_COLUMNS` (`catalog/schema.py:86-96`) indexes metadata only — `text_excerpt` is excluded. "Full-Text Search" in the README means full-text over metadata. Indexing excerpts (a separate FTS table keyed by book id, to keep bm25 sane) would make the feature match its name.
- **No result snippets.** FTS5 has `snippet()` and `highlight()` built in; search results currently show the same card as browsing, with no indication of *why* a book matched.
- **Default search mode is `text`** in both the server (`routes/search.py:12`) and the UI (`App.tsx:42`), while `README.md:260` documents `hybrid` as the default. Given embeddings exist for all 212 books, `hybrid` is probably the better default — pick one and make the three places agree.
- **Language facet values are dirty:** `en` (188), `''` (18), `ar` (2), `es`, `fr`, `po`, `sp` (1 each). `po` and `sp` are not ISO-639-1. Normalise at read time so the sidebar doesn't offer junk options.

### UX

- Bulk select in grid/list → favourite / set status / tag several books at once.
- Virtualised grid — `@tanstack/react-virtual` is already a dependency, unused; at 200 books per page the DOM is heavy.
- Gate the LLM buttons on `GET /api/reading/llm-status` (the endpoint exists and is unused) rather than letting every click fail with an error string.
- Make the Ollama model and base URL configurable — `llm_service.py:12-13` hardcodes `llama3.2` and `localhost:11434`.
- `g r` shortcut for the review queue, which has a header icon but no shortcut while Stats and Settings have both.
- Live pipeline progress on the Settings page: `task_tracker` already reports `progress`/`total`/`message` per book and the UI shows only a spinner and a string.

### Operations

- `GET /api/health` and a version endpoint.
- `Cache-Control`/`ETag` on `/covers` — 18 MB of images re-requested on every hard refresh.
- Structured exception handler so 500s return JSON and get logged with the request path.

---

## 6. Gaps worth naming explicitly

> ✅ **Addressed, except for frontend tests.**
> ✅ **Testing** — `tests/conftest.py` builds an app against a temp DB;
> `tests/test_server.py` now holds 69 route tests (132 total, up from 63). The
> three defects named below are each pinned by a test, as is every behaviour
> added in the second pass. **Frontend tests remain absent.**
> ✅ **Documentation drift** — every row of the table below is now correct,
> along with the new endpoints, the snippet delimiters, the search-mode
> semantics and the pipeline request body.
> ✅ **Lint in CI** — `.github/workflows/ci.yml` runs `pytest`, `tsc -b`,
> `npm run lint` and `npm run build` on every push and pull request.
> ✅ **`.env.example`** — added, covering `GOOGLE_BOOKS_API_KEY`,
> `OLLAMA_BASE_URL` and `OLLAMA_MODEL`.
> ✅ **Accessibility** — the first pass added `aria-label` to the header's
> icon-only buttons, `aria-pressed` to `FilterRadio` and the view toggles,
> `aria-expanded` to the filter sections, and untangled `BookCard`'s nested
> interactive elements. The second pass made the suggestion dropdown a real
> `combobox` with `role="listbox"`, `role="option"` and
> `aria-activedescendant`, and gave the theme menu `role="menu"` /
> `menuitemradio`.

**Testing.** 63 tests pass, and every one of them is in `catalog/` (`test_names`, `test_analysis`, `test_pipeline_stages`, `test_title_parser`, `test_verification`). There are **zero tests for `server/`** and zero for the frontend. Three of the defects above — the path traversal, the `search=self-help` 500, and the `year_min=abc` 500 — are each one line of `TestClient` away from being caught:

```python
def test_spa_fallback_cannot_escape_dist(client):
    assert client.get("/..%2f..%2f.env").status_code == 404

def test_search_filter_accepts_punctuation(client):
    assert client.get("/api/books?search=self-help").status_code == 200
```

A `conftest.py` fixture building an app against a temp DB would make the whole route layer testable in an afternoon.

**Lint is not in the loop.** `npm run lint` exits with 11 errors, including the two `rules-of-hooks` violations. There is no CI, so nothing enforces it.

**No `.env.example`.** The only way to learn that `GOOGLE_BOOKS_API_KEY` exists is to read the README's step 2 prose.

**Documentation drift.** `docs/API.md` and `README.md` describe an API that partly no longer exists:

| Claim | Reality |
| --- | --- |
| `API.md:22` sort fields `publication_year`, `authors` | actual keys are `year`, `author`; `pages`, `rating`, `last_opened` undocumented |
| `API.md:68` similar `method`: `combined`, `semantic` | actual: `combined`, `content`, `metadata` |
| `API.md:94` PATCH "accepts any book field name" | only the six `USER_FIELDS` are applied; everything else is silently dropped |
| `API.md:128` "All search modes support the full set of filter parameters" | `tag` is ignored in semantic/hybrid (§1.5) |
| `API.md:234` stats returns `categories_top`, `languages` | actual keys: `categories`, `themes`, `year_histogram`, `recently_processed` |
| `API.md:350` pipeline run body `{force, book_ids}` | actual: `{max_books, file_types, llm, embed, force}` — no `book_ids` |
| `API.md:366` unprocessed "List books" | returns two integers, no list |
| `API.md` | `/api/books/{id}/file`, `/api/pipeline/report` and the entire `/api/review/*` group are missing |
| `README.md:27` state = Zustand | not installed |
| `README.md:176` `common/ErrorBoundary` | does not exist |
| `README.md:202` `catalog/database.py` | does not exist (it is `store.py`); `evidence.py`, `providers.py`, `taxonomy.py`, `text_utils.py`, `names.py`, `schema.py`, `user_data.py`, `reporting.py` are all absent from the tree diagram |
| `README.md:260` search default `hybrid` | server and UI both default to `text` |

**Accessibility.** No `aria-label` on any icon-only button (the header has six), nested interactive elements in `BookCard`, the suggestion dropdown has no `role="listbox"`/`aria-activedescendant` despite implementing full keyboard navigation, and `FilterRadio` renders `<button>`s with no `aria-pressed`.

---

## 7. Suggested order of work

> **Items 2–14 are all done.** Item 1 is the maintainer's to do.

**Now**
1. ⚠️ Rotate the Google Books API key. — **still outstanding**, deferred as low
   risk given the `127.0.0.1` default. The leak vector itself is closed.
2. ✅ Patch the SPA fallback path traversal (§0.1).
3. ✅ Exclude `/api` from the SPA fallback (§1.3).
4. ✅ Sanitise the `search=` parameter and type `year_min`/`year_max` as `int` (§1.1, §1.2).
5. ✅ Add `tests/test_server.py` covering exactly those four. — done, and 44
   further cases besides.

**Next**
6. ✅ Fix the conditional hooks and clear the 11 lint errors (§2.1, §2.2).
7. ✅ Fix `ReaderSidebar`'s auto-compare `useState`-as-effect (§2.7) — the reader's similar-passages panel is dead right now.
   **This one needed more than the review found:** the `useState` bug was real,
   but fixing it alone left the panel dead, because EPUB books would not open
   at all and EPUB selections never reached the sidebar. See the status header.
8. ✅ Unify dark mode (§2.4); reset page on search/filter change (§2.3).
9. ✅ Vendor the PDF.js worker (§2.9).
10. ✅ Make `analyze_text_stream` non-blocking (§1.7); add a lock or per-request connections (§1.8); close `CatalogStore` (§1.9).

**Then**
11. ✅ Persist reading progress and reader position (§5) — the single largest gap between what the schema promises and what the app does.
12. ✅ Consolidate the duplicated FTS/filter/param code (§4.1–4.4) and delete the dead endpoints (§3).
13. ✅ Fix semantic pagination and switch `/api/reading/compare` to content embeddings (§1.4, §1.6).
14. ✅ Bring `docs/API.md` and `README.md` back in line with the code (§6).

---

## 8. Suggested order of work — what remains

1. **Rotate the Google Books API key** (§0.1). Nothing else here is blocking,
   and this is the only item that is not a code change.
2. **Frontend tests.** The backend has 132; the frontend has none. The highest
   value cases are the ones that already broke once: theme persistence across
   a reload, `useLibraryParams` resetting `page` without eating a bookmarked
   one, and `useReadingProgress` flushing on unmount.
3. **Bulk select** in the grid and list — favourite, set status or tag several
   books at once. The only §5 UX item not taken.
4. The three deferred items, in rough value order: `BookCover`'s canvas
   sampling (needs a column computed by the cover pipeline), the
   `books`/`user_data` VIEW (§4.10), the `vite` beta pin (§3).
5. **Revisit `MIN_SEMANTIC_SCORE` / `SEMANTIC_RELATIVE_FLOOR`** once the
   catalog grows. They were set from the score distribution measured over 544
   books; the shape of that distribution will move.
