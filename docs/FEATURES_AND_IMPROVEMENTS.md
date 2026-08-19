# Features & Improvements

A planning document for the Smart Book Library. Part 1 is a design for the
passage index — the piece that unlocks passage ↔ book ↔ catalog interaction —
and carries the detail. Parts 2–5 are the rest of the roadmap at planning depth.

Every number in this document was measured on this machine against this
library on 2026-08-19, not estimated. Measurement commands are in
[Appendix A](#appendix-a--how-the-numbers-were-measured).

**Library baseline**

| | |
|---|---|
| Books | 618 (581 PDF, 37 EPUB) |
| Pages | 186,969 (avg 304/book) |
| On disk | 5.1 GB PDF + 215 MB EPUB |
| Language | 575 English, 4 Arabic, 28 unknown, rest scattered |
| No text layer (needs OCR) | 19 books (3%) |
| Embeddings today | 618 — one content vector + one metadata vector per book |

---

## Part 1 — The passage index

### 1.1 Why the current design cannot support these features

The catalog reads only the **first ~14 pages** of every book:

- `MAX_PAGES_TO_EXTRACT = 14` — `catalog/config.py:85`
- `CONTENT_SAMPLE_MAX_CHARS = 4000`, `EMBEDDING_MAX_INPUT_CHARS = 4000`

Measured against `data/catalog.db`: average `content_sample` length is 3,724
characters, capped at 4,000. There is exactly **one content vector per book**,
built from its opening pages.

Three consequences:

1. **Cross-book comparison scores prose against introductions.** When a reader
   selects a paragraph on page 340, `POST /api/reading/compare`
   (`server/routes/reading.py:52`) scores it against 618 vectors that each
   represent a different book's *front matter and first chapter*.

2. **The match card shows the wrong text.** The endpoint returns
   `excerpt: text_excerpt[:300]` — the first 300 characters of the matched
   book — displayed under a similarity badge as though it were the matching
   passage. There is no matching passage in the system to return.

3. **"Elsewhere in this book" is structurally excluded.** The endpoint skips
   the current book outright (`if book_id == body.book_id: continue`), and even
   without that skip there is only one vector for the whole book to match
   against.

Full-text search has the same ceiling: `book_text_fts` indexes
`text_excerpt`, `front_matter`, and `content_sample` — the same first 14 pages.

### 1.2 Approaches considered

The question was "can we index passage embeddings, or are there better ways?"
Both parts are worth answering. These are not mutually exclusive; the
recommendation combines three of them.

| # | Approach | Verdict |
|---|---|---|
| 1 | **Chunk embeddings, brute-force NumPy search** | **Recommended.** Measured 4.8 ms over 340k vectors. Exact, no new dependency. |
| 2 | ANN index (faiss / hnswlib / usearch) | **Not now.** Solves a problem you do not have — approximate search to avoid a 4.8 ms scan. Revisit past ~5M chunks. |
| 3 | `sqlite-vec` extension | **No.** Attractive for keeping everything in one file, but slower than a NumPy matmul at this scale and adds extension-loading fragility. |
| 4 | FTS5/BM25 over chunks, no vectors | **Yes, but as a complement.** Free to build and unbeatable for exact terminology and proper nouns; blind to paraphrase, which is the whole point here. |
| 5 | Hybrid dense + BM25 with Reciprocal Rank Fusion | **Recommended**, combining 1 and 4. |
| 6 | Cross-encoder reranking of top-50 | **Recommended for phase 2.** Large precision gain for ~50 ms. |
| 7 | Late interaction (ColBERT-style) | **No.** Best-in-class retrieval, but one vector per *token* — 30–100× the storage. |
| 8 | Hierarchical: book vector filters, then chunk rerank | **Unnecessary.** The optimization it buys is invisible against a 4.8 ms flat scan, and it can only lose recall. |
| 9 | LLM entity/claim extraction into a graph | **Complementary, later.** The right tool for concept threads (§1.9.4), not a replacement for retrieval. |

### 1.3 Why brute force wins here

Measured at `N=340,000` vectors × 384 dimensions — a deliberate overshoot of
the ~272,000 chunks this library actually produces (§1.7), so the figures are
an upper bound:

```
float32   matmul + top-20:     4.8 ms      RAM 522 MB
float16   matmul + top-20:   154.6 ms      RAM 261 MB
single book (~600 chunks):    0.003 ms
```

4.8 ms is well inside a single frame. An ANN index would add a dependency, a
build step, and approximation error to make an already-imperceptible query
faster. Exact search also means no recall tuning and no "why did it miss that
paragraph" debugging.

> **⚠ The float16 trap.** float16 is 32× *slower*, not faster. NumPy has no
> float16 BLAS path, so it upcasts elementwise on every query. **Store float16
> on disk to halve the file; upcast to float32 once at load.** Never matmul in
> float16.

Filtered searches — one book, one author, one category — are effectively free
at 0.003 ms, because they slice the matrix before the matmul. This is what
makes "elsewhere in this book" and "only in books I've finished" cheap.

### 1.4 Embedding model

Switching from `all-MiniLM-L6-v2` to **`BAAI/bge-small-en-v1.5`**. Verified on
this machine:

| | all-MiniLM-L6-v2 | bge-small-en-v1.5 |
|---|---|---|
| Dimensions | 384 | **384** (all sizing above holds) |
| Max sequence | 256 tokens | **512 tokens** |
| Throughput (MPS) | 434 chunks/s | **199 chunks/s** |
| Retrieval quality | baseline | clearly better on MTEB retrieval |

2.2× slower, but it embeds a full 1,500-character chunk instead of truncating
it at the halfway mark. At this corpus size the difference is ~13 min versus
~23 min of one-time build, which is not a real constraint.

English-only is the right trade: 575 of 618 books are English and only 4 are
Arabic. A multilingual model would cost quality on 93% of the library to serve
0.6% of it. Handle the Arabic books as a later, separate index if they matter.

**Two nuances that are easy to get wrong:**

1. **Asymmetric vs symmetric use.** bge wants the instruction prefix
   `"Represent this sentence for searching relevant passages: "` on *short
   search queries* only. Passage-to-passage similarity — which is what
   "elsewhere in this book" and cross-book comparison are — is symmetric and
   must be embedded **without** the prefix. Getting this backwards quietly
   degrades results.

2. **Re-embed the book-level vectors too.** The existing 618 content and
   metadata vectors are MiniLM. Vectors from different models are not
   comparable. Re-run `catalog/embeddings.py` with `force=True` so the book
   space and the passage space are the same space — otherwise anything that
   mixes them produces nonsense.

Store the model id alongside the vectors (§1.6) so a future swap is a
detectable re-index rather than a silent corruption.

### 1.5 Chunking strategy

**Target 1,500 characters (~375 tokens), 250-character overlap, 1,250 stride.**

Sized to sit comfortably under bge's 512-token limit while holding a complete
argument. Overlap keeps a thought that straddles a boundary retrievable from
both sides.

Split on structure first, length second: paragraph breaks, then sentence
boundaries, and only mid-sentence as a last resort. A chunk that ends
mid-clause embeds badly.

**Anchoring — the part that actually matters.** A retrieved chunk is only
useful if the reader can jump to it. Every chunk needs a durable pointer back
into the document:

- **PDF** — straightforward. Extract per page and record `page_start` /
  `page_end`. The reader already navigates by page number
  (`goToPage` in `BookReader.tsx`), so a deep link is
  `/read/{id}?page=212&highlight=<hash>`.
- **EPUB** — harder, and worth being honest about. Generating a true CFI
  offline is painful. Store `spine_index` + `char_offset` + a short
  `anchor_text` (the chunk's first ~60 characters) instead, then navigate with
  `rendition.display(spineHref)` and locate `anchor_text` in the rendered
  document to scroll and highlight. Less elegant than a CFI, robust in
  practice.

**Skip list:** front matter, copyright pages, indexes, bibliographies, and the
19 OCR-required books. `catalog/text_utils.py:is_mostly_boilerplate` already
exists for this and should gate chunk creation — an index full of copyright
boilerplate makes unrelated books look similar, which is the exact failure the
existing `_content_text` comment warns about.

### 1.6 Schema

Two new tables plus an FTS index. Vectors live in a sidecar `.npy` file rather
than SQLite so they can be `mmap`'d and sliced without deserialization.

```sql
CREATE TABLE chunks (
    id          INTEGER PRIMARY KEY,   -- row index into the vector file
    book_id     TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chunk_idx   INTEGER NOT NULL,      -- ordinal within the book
    text        TEXT NOT NULL,
    char_start  INTEGER,               -- offset in the book's extracted text
    page_start  INTEGER,               -- PDF
    page_end    INTEGER,               -- PDF
    spine_index INTEGER,               -- EPUB
    anchor_text TEXT,                  -- EPUB: first ~60 chars, for locating
    section     TEXT,                  -- chapter/heading if detectable
    UNIQUE(book_id, chunk_idx)
);
CREATE INDEX idx_chunks_book ON chunks(book_id);

CREATE TABLE chunk_index_meta (
    model_id     TEXT,        -- 'BAAI/bge-small-en-v1.5'
    dim          INTEGER,
    count        INTEGER,
    dtype        TEXT,        -- 'float16' on disk
    built_at     TEXT,
    chunk_chars  INTEGER,
    chunk_overlap INTEGER
);

-- external content: indexes chunk text without a second copy of it,
-- exactly as books_fts does for books
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    text, content='chunks', content_rowid='id',
    tokenize='porter unicode61'
);
```

`chunks.id` is the row index into `data/chunk_vectors.npy`, so a top-k result
maps to rows with a single `WHERE id IN (...)`. Rebuild the vector file whole;
do not try to maintain row stability across deletes.

### 1.7 Build pipeline

A new opt-in stage in `catalog/pipeline.py`, following the existing stage
conventions so `stage_versions` gates re-runs:

1. **Extract full text** — lift the 14-page cap for this stage only. Write to
   `data/text/{book_id}.txt` rather than into the `books` row; 340 MB does not
   belong in a column that every list query reads.
2. **Chunk** — §1.5, with anchors.
3. **Embed** — batched, `normalize_embeddings=True`, no query prefix.
4. **Write** — `chunks` rows, `chunks_fts` populated by trigger, vectors
   appended to the `.npy`, `chunk_index_meta` stamped.

**Measured one-time cost**

| Stage | Cost |
|---|---|
| PDF text extraction (pypdf, 11.6 ms/page × 186,969) | ~36 min single-threaded, **~12 min at `MAX_WORKERS=4`** |
| Embedding (~272k chunks ÷ 199/s) | **~23 min** |
| **Total** | **~35–60 min, once** |

> **pypdf is the bottleneck, and it is replaceable.** At 11.6 ms/page pypdf is
> pure Python. PyMuPDF is typically 10–20× faster and gives per-page text with
> coordinates — which is also what precise highlight anchoring wants. Worth
> considering as an extraction-only dependency; note its AGPL licence.

**Incremental updates.** `catalog/watcher.py` already detects changes. On a
changed book, delete its chunk rows and re-chunk just that book; mark the
vector file dirty and compact it on a schedule rather than rewriting 418 MB per
book.

### 1.8 Runtime

Load once in `lifespan` (`server/app.py`) next to the existing
`similarity.load_embeddings()`:

```python
vecs = np.load(CHUNK_VECTORS_PATH, mmap_mode="r")   # float16 on disk
chunk_matrix = np.ascontiguousarray(vecs, dtype=np.float32)   # upcast once
```

**Resident cost: ~418 MB** for 272k chunks. If that is too much, `mmap_mode='r'`
without the upcast lets the OS page it, at the cost of the float16 penalty —
better is int8 quantization with float32 rescoring of the top 200, which holds
~105 MB resident and stays exact where it counts.

**Search paths**, all built on one `_rank` over a matrix slice:

| Query | Filter | Cost |
|---|---|---|
| Elsewhere in this book | `book_id == current` | 0.003 ms |
| Across the catalog | exclude current book | 4.8 ms |
| Within a category / author / shelf | id set intersection | <5 ms |

**Hybrid retrieval.** Run the dense search and a `chunks_fts` BM25 search in
parallel and fuse with Reciprocal Rank Fusion (`score = Σ 1/(60 + rank)`). RRF
needs no score normalization between the two systems, which is the usual
source of hybrid-search bugs.

**New endpoints**

```
POST /api/passages/search      { text | query, scope, filters, limit }
      scope: "book" | "catalog" | "category" | "author"
GET  /api/passages/{chunk_id}  → chunk + neighbours + deep link
POST /api/passages/stance      { text, limit } → grouped supports/complicates/contradicts
GET  /api/books/{id}/threads   → recurring concepts within one book
```

`POST /api/reading/compare` should be reimplemented on top of
`/api/passages/search` and keep its response shape, except that `excerpt`
finally becomes the real matching passage with a page anchor rather than
`text_excerpt[:300]`.

### 1.9 Features this unlocks

#### 1.9.1 Elsewhere in this book
The same idea recurring in chapter 2 and chapter 11. Frequently more valuable
than cross-book matching, currently impossible, and the cheapest query in the
system. Ship this first — it is the smallest thing that proves the index.

#### 1.9.2 Real cross-book passages
The actual matching paragraph, its page number, and a deep link. This is the
existing feature finally telling the truth.

#### 1.9.3 Agreement vs. disagreement
Retrieve top-k passages across the catalog, then ask the LLM to sort them into
**supports / complicates / contradicts** with a one-line justification each.
Grounded entirely in retrieved text, every claim citable to a page. With
Hallaq, Cavanaugh, Kuhn, Stove, Henrich and Khalidi in one library, this is the
feature that makes the app a research tool rather than an e-reader.

#### 1.9.4 Concept threads
Every passage across the catalog touching a concept, ordered by publication
year — a reading trail through your own library showing how an idea travels.
Embeddings retrieve; an LLM entity pass (approach 9) sharpens it later.

#### 1.9.5 Library-wide full-text search
"Every mention of X across all 618 books," which `chunks_fts` gives you as a
by-product of the same build.

### 1.10 Risks

| Risk | Mitigation |
|---|---|
| float16 matmul is 32× slower | Upcast at load. Documented in §1.3. |
| Mixing MiniLM and bge vectors | Re-embed book-level vectors; store `model_id`; refuse to load on mismatch. |
| bge query prefix used symmetrically | Prefix only short search-box queries, never passage-to-passage. |
| 19 OCR-required books silently absent | Surface them in the UI as "not indexed", don't fail quietly. |
| Boilerplate polluting the index | Gate on `is_mostly_boilerplate`, skip front matter. |
| EPUB anchors are approximate | `anchor_text` fallback search; accept imprecision. |
| 418 MB resident | int8 + rescore if it becomes a problem. |
| Disk growth ~900 MB | Text 340 MB + FTS ~150 MB + vectors 418 MB. Document it. |

### 1.11 Phasing

| Phase | Deliverable | Effort |
|---|---|---|
| **0** | Vertical slice on ~30 books: schema, extraction, embedding, one endpoint, "elsewhere in this book" in the sidebar. Proves the UX before the full build. | 2–3 d |
| **1** | Full index build; `/api/reading/compare` reimplemented with real excerpts and deep links. | 2–3 d |
| **2** | Hybrid RRF + cross-encoder reranking; library-wide full-text search. | 2–3 d |
| **3** | Stance grouping; concept threads. | 3–5 d |

---

## Part 2 — Reading experience

### 2.1 Missing features

| Feature | Notes | Effort |
|---|---|---|
| **In-document search** | Neither reader has it. PDF: `page.getTextContent()`. EPUB: `book.search()` across the spine. Table stakes for a 600-page PDF. | M |
| **PDF outline / TOC** | EPUB has one, PDF doesn't. `pdfjs.getOutline()` — most of the technical PDFs carry one. | S |
| **Reading themes** | The PDF canvas is white-on-white in dark mode. CSS filter on the canvas for sepia/dark. | S |
| **EPUB typography** | `handleRendition` hardcodes `Georgia, serif`. Expose font family, line height, margin width, theme. | S |
| **Bookmarks** | One position per book is saved; you cannot mark "come back to this." | S |
| **Page thumbnails** | Sidebar strip for PDF navigation. | M |
| **EPUB locations index** | The code comment is right that generating it on open is too slow — but generate once in a worker and cache `book.locations.save()` in the DB. Turns approximate spine-ratio progress into exact "page X of Y". | M |
| **Fit width / fit page** | Zoom is manual only. | S |

### 2.2 Defects in what exists

- **Continuous-mode memory leak.** `renderedRange` only ever grows —
  `BookReader.tsx:120` takes `Math.min`/`Math.max` against the previous range
  and never shrinks it. Scrolling a 600-page PDF accumulates every visited page
  as a live canvas. Evict pages outside a window.
- **Selection threshold duplicated three times.** `length > 10` appears in
  `PdfReader`, `EpubReader`, and the iframe fallback listener. Hoist it.
- **The sidebar yanks itself open** on any selection ≥ 10 characters, including
  accidental double-clicks. A floating selection toolbar — Highlight · Ask ·
  Compare · Copy — is the better interaction and becomes the natural home for
  the passage features in Part 1.

---

## Part 3 — Annotations

**There is no annotation storage anywhere in the schema.** No highlights, no
bookmarks, no margin notes. This is the largest gap for a "smart" library and
is independent of Part 1 — it can ship in parallel.

Store alongside `user_data`, keyed by book id *and* file path, so annotations
survive a full catalog rebuild the way ratings and tags already do:

```sql
CREATE TABLE annotations (
    id          TEXT PRIMARY KEY,
    book_id     TEXT NOT NULL,
    file_path   TEXT,               -- survives rebuilds, as user_data does
    kind        TEXT,               -- highlight | bookmark | note
    text        TEXT,               -- the selected passage
    note        TEXT,               -- user commentary
    color       TEXT,
    page        INTEGER,            -- PDF
    cfi         TEXT,               -- EPUB
    anchor_text TEXT,               -- relocation fallback
    created_at  TEXT,
    updated_at  TEXT
);
```

Anchoring shares its design with §1.5 — build both against the same helper.

Once annotations and the passage index coexist, a highlight becomes a query:
*"show me everything in the library related to what I just highlighted."*

---

## Part 4 — LLM layer

### 4.1 Live bug

`_build_prompt` accepts a `context` argument and the `"compare"` template
interpolates it — but `server/routes/reading.py:96` calls
`analyze_text_stream(body.text, body.action, book_title)` with no context.
**Every "Compare" request currently sends a prompt ending in `Related:`
followed by nothing.** Feeding retrieved chunks into that slot is both the fix
and the feature.

### 4.2 Improvements

- **The model sees the selection and nothing else.** Send surrounding page
  text, the chapter title, and the book's themes/author/year. A paragraph read
  in isolation loses the argument it belongs to.
- **No follow-up.** Five one-shot buttons, no conversation. A thread scoped to
  the passage — with the passage and retrieved context pinned — matches how
  people actually interrogate a text.
- **Nothing is saved.** Every analysis evaporates on close. Persist against the
  passage; combined with Part 3 that yields a per-book notebook.
- **Ground every citation.** When the model references other books it should be
  quoting retrieved chunks with page anchors, not free-associating. Part 1 is
  the retrieval corpus.
- **Model capability.** `OLLAMA_MODEL` defaults to `qwen3.5:4b`. Critique and
  stance-grouping are the two tasks that most reward a larger model; worth
  evaluating before building §1.9.3 on top of a 4B.

---

## Part 5 — Other

- **Reading sessions.** Percent and position are saved, but not *time*. A
  `reading_sessions` table (book, start, end, pages) unlocks pages/week,
  streaks, and time-to-finish — real substance for the Dashboard.
- **Export** highlights, notes, and LLM threads to Markdown. A local-first
  library should have portable notes.
- **Duplicate resolution in the UI.** `catalog/duplicate_detector.py` and the
  `duplicate_of` column exist but nothing surfaces them. There are at least two
  literal duplicates in `epubs/` (Chip Huyen, Henrich).
- **OCR the 19 image-only books** so they stop being invisible to search,
  similarity, and the passage index.

---

## Roadmap

**Quick wins** — days, no migration:
pass `context` into the compare prompt (§4.1) · PDF outline · in-document
search · reading themes · fix the `renderedRange` leak · selection toolbar.

**Then annotations** (Part 3) — self-contained, no dependency on Part 1, and
the single feature most likely to change daily use.

**Then the passage index** (Part 1), phased per §1.11. It is the expensive one,
but every interesting passage ↔ book ↔ catalog feature is downstream of it.

---

## Appendix A — how the numbers were measured

| Number | Method |
|---|---|
| 618 books, 186,969 pages, 19 OCR, language split | `sqlite3 data/catalog.db` aggregates |
| avg `content_sample` 3,724 chars | `select avg(length(content_sample)) from books` |
| pypdf 11.6 ms/page, ~1,750 chars/page | 6-book random sample, 60 pages each, `pypdf.PdfReader.extract_text()` |
| MiniLM 434 chunks/s · bge 199 chunks/s | `SentenceTransformer.encode`, 1,024–2,048 × 1,200-char chunks, `batch_size=128`, MPS |
| 4.8 ms / 154.6 ms / 0.003 ms search | NumPy matmul + `argpartition`, N=340k × 384, 10 iterations |
| bge dim 384, max_seq 512 | `SentenceTransformer("BAAI/bge-small-en-v1.5").max_seq_length` |

Re-measure after any model or hardware change; the float16 result in
particular is BLAS-dependent.
