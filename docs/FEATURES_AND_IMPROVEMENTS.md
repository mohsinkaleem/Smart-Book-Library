# Features & Improvements

A planning document for the Smart Book Library. Part 1 is a design for the
passage index — the piece that unlocks passage ↔ book ↔ catalog interaction —
and carries the detail. Parts 2–5 are the rest of the roadmap at planning depth.

Every number in this document was measured on this machine against this
library on 2026-08-19, not estimated. Measurement commands are in
[Appendix A](#appendix-a--how-the-numbers-were-measured).

## Status

Implemented on 2026-08-19: the quick wins, all of Part 3, and the embedding
model switch from §1.4. Sections that have shipped are marked **✅ Shipped**
and rewritten in the past tense; everything unmarked is still a plan.

| Part | State |
|---|---|
| **1 — Passage index** | Not started. §1.4's model switch shipped ahead of it (below); the rest stands as designed. |
| **2 — Reading experience** | Most of §2.1 and all of §2.2 shipped. Page thumbnails and the EPUB locations index remain. |
| **3 — Annotations** | ✅ Shipped in full. |
| **4 — LLM layer** | §4.1 fixed. §4.2 partly done: context and retrieval grounding shipped; threads and persistence remain. |
| **5 — Other** | Not started. |

The build is at 199 backend tests and 45 frontend tests (`pytest` and
`npm test --prefix frontend`), up from 145 and none.

### What the implementation changed about the plan

Four things were only visible once the code ran, and are recorded where they
belong rather than here:

* Highlight anchoring needs *positional* matching, not text containment —
  §3 and `pdfHighlight.ts`.
* The relevance floors in `similarity.py` are model-specific and had to be
  re-measured for bge — §1.4.
* EPUB navigation has exactly one owner, or it renders blank pages — §2.2.
* `is_mostly_boilerplate` gating (§1.5) is still the right call, but the
  measured book-level retrieval it produces is noticeably topical rather than
  textual, which is the case for Part 1 restated in evidence — §1.9.2.

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
   (`server/routes/reading.py`) scores it against 618 vectors that each
   represent a different book's *front matter and first chapter*. Still true;
   measured output in §1.9.2.

2. **The match card shows the wrong text.** The endpoint returned
   `excerpt: text_excerpt[:300]` — the first 300 characters of the matched
   book — under a similarity badge as though it were the matching passage.
   *Partly addressed:* it now returns `content_sample`, which is at least prose
   past the front matter rather than the title page. It is still not the
   matching passage, because there is no matching passage in the system to
   return. Only the chunk index fixes this.

3. **"Elsewhere in this book" is structurally excluded.** The endpoint skips
   the current book outright (`if match_id == book_id: continue`), and even
   without that skip there is only one vector for the whole book to match
   against. Unchanged.

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

### 1.4 Embedding model — ✅ Shipped

Switched from `all-MiniLM-L6-v2` to **`BAAI/bge-small-en-v1.5`**. This landed
ahead of the rest of Part 1, because it is a prerequisite for it and improves
book-level search on its own. Verified on this machine:

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

**What shipped**

* `EMBEDDING_MODEL` defaults to `BAAI/bge-small-en-v1.5`; `EMBEDDING_QUERY_PREFIX`
  holds the instruction string.
* The two uses are separate functions rather than a boolean argument, because
  getting them the wrong way round fails silently:
  `catalog.embeddings.encode_query` applies the prefix,
  `encode_passage` never does. `SimilarityEngine` exposes both;
  `/api/reading/compare` runs on the symmetric one.
* `embeddings.model_id` stamps every row, `ensure_schema` adds the column, and
  `SimilarityEngine.load_embeddings` **skips rows built by another model** and
  says so in the log, rather than mixing two vector spaces in one matrix — a
  failure that does not raise, it just returns confident nonsense.
* `scripts/reembed.py` re-embeds the catalog. All 618 books, 21 s.
* `STAGE_VERSIONS["embed"]` bumped to 3, and the gap-filling embed task now
  tests for a *current* embedding rather than any embedding — otherwise a model
  switch looks like "everything is already done".

**The trap that was not in the plan: the relevance floors are model-specific.**

`MIN_SEMANTIC_SCORE` and `SEMANTIC_RELATIVE_FLOOR` in `server/similarity.py`
were calibrated against MiniLM's score distribution and carried over unchanged.
bge packs every score into a high, narrow band, so the old values sat below its
*noise* floor and semantic search returned the entire library for any input.
Re-measured on this catalog:

| | top score |
|---|---|
| Six real queries | 0.655 – 0.834 |
| Four nonsense queries | 0.564 – 0.621 |

The gap is 0.03 wide, where under MiniLM it was around 0.2. Floors moved to
**0.63** absolute and **0.84** relative — the 50th result of a real query
scores ~0.84 of the best one, while for nonsense the ranking is flat at ~0.91
because nothing is genuinely more relevant than anything else. After the
change, nonsense returns 0 books and a query on the catalog's dominant subject
returns 129.

`tests/test_similarity_floors.py` pins the invariant so a future model change
fails a test instead of quietly returning everything.

> **Re-measure these after any model change.** They are the one part of the
> switch that does not announce itself when it breaks.

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
  (`goToPage` in `PdfReader.tsx`), so a deep link is
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

**Now with evidence.** `/api/reading/compare` was reimplemented on the current
book-level vectors (§4.1), which is as far as it can go before this lands, and
the ceiling is visible in the output. Comparing a passage on the state's
production of the category of religion returns books that are *topically*
right — Islam & Politics, and so on — scored 0.58–0.61, with an excerpt taken
from each book's opening pages rather than from anything resembling the
selection. The card is honest about what it has, but what it has is a book
recommendation, not a passage match. Everything in §1.9 stays blocked on the
chunk index.

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
| Mixing MiniLM and bge vectors | ✅ Handled. Book-level vectors re-embedded; `embeddings.model_id` stamped per row; `load_embeddings` skips non-matching rows and logs it. |
| bge query prefix used symmetrically | ✅ Handled. Two functions rather than a flag: `encode_query` prefixes, `encode_passage` never does. |
| 19 OCR-required books silently absent | Still open, and now wider than retrieval: with no text layer, selection, highlighting and in-document search are all inert in the reader too. Surface them as "not indexed". |
| Relevance floors tuned to the wrong model | ✅ Handled for book-level search, and **the lesson generalises**: the floors are a property of the model's score distribution, not of the catalog. Re-measure if the chunk index gets its own. Pinned by `tests/test_similarity_floors.py`. |
| Anchors matched by containment rather than position | ✅ Learned the hard way in Part 3. Chunk anchoring must be positional for the same reason — see "The anchoring lesson". |
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

| Feature | State |
|---|---|
| **In-document search** | ✅ Shipped, both formats. |
| **PDF outline / TOC** | ✅ Shipped. |
| **Reading themes** | ✅ Shipped — five, incl. `auto`. |
| **EPUB typography** | ✅ Shipped — face, line height, margins. |
| **Bookmarks** | ✅ Shipped, as an annotation kind (Part 3). |
| **Fit width / fit page** | ✅ Shipped. |
| **Page thumbnails** | Still open. Sidebar strip for PDF navigation. |
| **EPUB locations index** | Still open. Generate once in a worker and cache `book.locations.save()` in the DB; turns approximate spine-ratio progress into exact "page X of Y". |

**In-document search.** PDF scans every page's `getTextContent()`, yielding
every 10 pages so a 1,454-page book does not freeze the frame, and reports
progress while it runs. Matches are marked in the live text layer, not just
listed. EPUB has no `book.search()` despite the plan saying so — searching is
per *spine item*, and each has to be `load`ed before `find` sees its text and
`unload`ed afterwards or the whole book stays resident. Both cap at 300 hits
and debounce, so typing a word is one scan rather than one per keystroke.

**PDF outline.** `getOutline()` resolves each entry's destination to a page —
named destinations need a `getDestination` lookup first, and an entry whose
destination will not resolve still belongs in the tree, just without a link.
Renders nested and collapsible with the current page marked. The empty state
says the PDF carries no table of contents rather than showing nothing.

**Reading themes.** `invert(1) hue-rotate(180deg)` for Night — the rotation is
what stops figures and syntax-highlighted code becoming colour negatives. Paper
and Sepia are a sepia/brightness pair rather than a colour overlay, so the ink
stays black. The filter goes on the *wrapper*, not the canvas: on the canvas
alone it would invert the ink but not the highlights sitting over it. EPUBs get
real CSS through epub.js themes instead, since they have real text.

`auto` is the default and follows the app's existing four themes, which is the
actual complaint the row above encodes — a white page in a dark app.

**EPUB typography.** Applied through an effect on the live rendition, so a
change takes effect immediately. `handleRendition` reads current values through
refs; it is handed to the reader once and would otherwise apply whatever the
render that created it happened to see.

### 2.2 Defects in what exists — ✅ All fixed

* **Continuous-mode memory leak.** `renderedRange` took `Math.min`/`Math.max`
  against its previous value and so only ever grew — scrolling a 600-page PDF
  end to end left every visited page as a live canvas. It is recomputed as a
  window around the visible page now (`WINDOW_BEFORE` / `WINDOW_AFTER`), so
  pages behind you unmount and their canvases are freed.

  Fixing this exposed a second bug it had been masking: jumping from page 3 to
  page 400 scrolled to nothing, because the target slot does not exist until
  the window moves. The jump is recorded and replayed when the slot mounts.

* **Selection threshold duplicated three times.** Hoisted to
  `MIN_SELECTION_CHARS` in `selection.ts`, along with the separate
  `MIN_COMPARE_CHARS` — there is less text needed to act on a selection than
  to retrieve against it, and conflating the two was part of why the numbers
  drifted apart.

* **The sidebar yanking itself open** is replaced by the floating toolbar the
  row proposed: Highlight · Note · Ask · Compare · Copy, positioned over the
  selection and clamped to the viewport. The reader opens the sidebar; it no
  longer happens to them.

**Two bugs found while testing, not in the original list:**

* **EPUB navigation must have exactly one owner.** `goToCfi` called
  `rendition.display(cfi)` *and* set the `location` prop that react-reader
  turns into its own `display` for the same target. epub.js rendered the
  section but left the paginated column offset pointing at the other call's
  result, so every search hit and every bookmark navigated to a **blank page**
  with the text sitting off-screen in a 10,000px-wide strip. Navigation now
  goes through `location` and nowhere else.

* **EPUB selections outside epub.js's own event had no anchor.** The fallback
  iframe `mouseup` listener — which exists because epub.js's `selected` misses
  selections in scrolled-doc mode — passed no CFI, so a highlight made through
  it was stored with an empty anchor and could never be repainted or navigated
  back to. The CFI is derived from the range via the `Contents` that owns the
  iframe window.

**File layout.** The 928-line `BookReader.tsx` held both readers and was the
wrong unit to keep adding to. Split into `PdfReader.tsx` and `EpubReader.tsx`,
with `selection.ts`, `readingTheme.ts` and `pdfHighlight.ts` holding the parts
that are pure — which is what let the last of those get unit tests after it
turned out to be wrong (Part 3).

---

## Part 3 — Annotations — ✅ Shipped

There was no annotation storage anywhere in the schema — no highlights, no
bookmarks, no margin notes. It was the largest gap for a "smart" library, and
being independent of Part 1, it shipped first.

The table is as designed, with `kind` constrained to
`highlight | bookmark | note` and every column defaulted:

```sql
CREATE TABLE annotations (
    id          TEXT PRIMARY KEY,
    book_id     TEXT NOT NULL,
    file_path   TEXT,               -- survives rebuilds, as user_data does
    kind        TEXT NOT NULL DEFAULT 'highlight',
    text        TEXT DEFAULT '',    -- the selected passage
    note        TEXT DEFAULT '',    -- user commentary
    color       TEXT DEFAULT 'yellow',
    page        INTEGER,            -- PDF
    cfi         TEXT DEFAULT '',    -- EPUB
    anchor_text TEXT DEFAULT '',    -- relocation fallback
    created_at  TEXT DEFAULT '',
    updated_at  TEXT DEFAULT ''
);
```

**Layout.** `catalog/annotations.py` owns the SQL, so the pipeline store and
the web server share one write path, as `user_data` already does.
`server/routes/annotations.py` is the HTTP surface —
`GET/POST /api/annotations`, `PATCH`/`DELETE /api/annotations/{id}`, documented
in `docs/API.md`. `id` and `book_id` are fixed at creation: an update that
could move an annotation to a different book is a bug surface with no feature
behind it.

**Rebuild survival is active, not just recorded.** Storing `file_path` is only
half of it — `relink_orphans` runs at startup and re-points annotations whose
`book_id` no longer exists at whatever book now holds their path. Book ids are
content hashes, so re-encoding a PDF gives it a new id and would otherwise
orphan every highlight in it.

**UI.** Highlights in four colours and notes are created from the §2.2
selection toolbar; `B` bookmarks the current spot. A Marks tab in the reader
sidebar filters by kind, navigates to each anchor, and edits notes inline.
Highlights are repainted in the document: through the text layer for PDF, and
`rendition.annotations.add` for EPUB.

### The anchoring lesson: containment is not enough

§1.5 says anchoring should share a helper with the chunk index. It should — but
the first implementation here was wrong in a way worth recording before Part 1
inherits it.

A PDF text run is a *positioning artefact*, not a word. One highlighted
sentence is spread across dozens of runs and a run can end mid-word. The
obvious rule — mark any run whose text appears inside the highlighted passage —
is wrong, and visibly so: highlighting a sentence containing `namedtuple` lit
up **every other occurrence of `namedtuple` on the page**, because each is its
own short run and each is genuinely a substring of the passage.

The fix is positional. Join the page's runs back into one string, locate the
passage *in that string*, and mark only the runs covering that span. Offsets
survive normalisation by carrying a parallel index table, so whitespace and
case can be collapsed for matching without losing the ability to say *where*
the match sits. Resolved once per page from react-pdf's `onGetTextSuccess`,
not per run.

Measured on the page that exposed it: 4 runs read `namedtuple`, 1 is inside the
highlight, 1 is marked.

`pdfHighlight.ts` is pure and has 20 unit tests, including that case by name.
**Part 1 should build chunk anchoring on the same positional approach** — a
chunk index anchored by containment would mislocate for exactly the same
reason, and far less visibly.

Once annotations and the passage index coexist, a highlight becomes a query:
*"show me everything in the library related to what I just highlighted."*

---

## Part 4 — LLM layer

### 4.1 Live bug — ✅ Fixed

`_build_prompt` accepted a `context` argument that only the `"compare"`
template interpolated, and the route called it without one. **Every Compare
request sent a prompt ending in a bare `Related:` with nothing after it.**

Fixed as the plan proposed — by filling the slot rather than removing it.
`/api/reading/analyze` now retrieves for `compare` and `related` (the two
actions whose prompts are grounded in other material; retrieval for `explain`
would cost a matmul and dilute the prompt), and passes the results in numbered
and attributed so the model can cite them.

Two details that were not in the plan:

* **The empty case.** When nothing is retrieved, the prompt degrades to a
  self-contained question instead of rendering the heading with no body under
  it. Every optional block is omitted entirely rather than emitted empty —
  which is the general form of the original bug.
* **A prompt budget.** A 4B model with a 4k window truncates from the *front*,
  which drops the instruction and keeps the retrieved noise. Retrieved and
  surrounding blocks are capped before assembly and the whole prompt after it,
  so the passage and the instruction always survive.

Measured on the real catalog: a Compare prompt is ~3,400 characters carrying 4
cited sources. `tests/test_reading_prompt.py` covers it, including a test that
asserts the prompt does not end in a dangling heading.

### 4.2 Improvements

- **The model sees the selection and nothing else.** ✅ Partly done. The
  request now carries `surrounding` — the prose around the selection, taken
  from its enclosing block — plus the book's author, year, categories and
  themes. Measured live: a 150-character selection ships with 1,100 characters
  of surrounding page text.

  The climb to find that block is the whole job, and got it wrong once:
  stopping at the first enclosing element returns the *selected paragraph*,
  which is nothing the model does not already have, because selecting a whole
  paragraph is the common case. It now climbs until an ancestor carries
  meaningfully more text than the selection — and stops at `body`, since
  walking past it reaches the Document node, whose `textContent` is null and
  wiped the result. Chapter title is still not sent; there is no reliable
  source for it in either reader yet.
- **No follow-up.** Still open. Five one-shot buttons, no conversation. A
  thread scoped to the passage — with the passage and retrieved context pinned
  — matches how people actually interrogate a text.
- **Nothing is saved.** Still open. Every analysis evaporates on close. Persist
  against the passage; with Part 3 now in place, the `annotations` table is the
  obvious home and a `note` on a highlight is most of the shape already.
- **Ground every citation.** ✅ For books, not yet for passages. The model is
  told not to invent sources beyond those listed, and the listed ones are real
  retrieved excerpts. But retrieval is still book-level — the excerpt is the
  book's opening pages, not the matching passage, and there is no page anchor
  to cite. That is Part 1's job and does not get better until it lands.
- **Model capability.** Still open. `OLLAMA_MODEL` defaults to `qwen3.5:4b`.
  Critique and stance-grouping most reward a larger model; worth evaluating
  before building §1.9.3 on top of a 4B.

---

## Part 5 — Other

- **Reading sessions.** Percent and position are saved, but not *time*. A
  `reading_sessions` table (book, start, end, pages) unlocks pages/week,
  streaks, and time-to-finish — real substance for the Dashboard.
- **Export** highlights, notes, and LLM threads to Markdown. A local-first
  library should have portable notes. Cheaper now than when this was written:
  `GET /api/annotations` already returns everything but the LLM threads, in
  reading order.
- **Duplicate resolution in the UI.** `catalog/duplicate_detector.py` and the
  `duplicate_of` column exist but nothing surfaces them. There are at least two
  literal duplicates in `epubs/` (Chip Huyen, Henrich).
- **OCR the 19 image-only books** so they stop being invisible to search,
  similarity, and the passage index. Now also invisible to the two features
  added in Part 2: with no text layer there is nothing to select, highlight or
  search within — the reader renders the page and every text affordance is
  inert. Worth surfacing in the UI as "not indexed" (§1.10) rather than
  letting it read as a broken reader.

---

## Roadmap

**Quick wins** — ✅ done. `context` into the compare prompt (§4.1) · PDF
outline · in-document search · reading themes · the `renderedRange` leak ·
selection toolbar. Plus fit-width/fit-page and EPUB typography, which were
adjacent enough to be cheaper together than separately.

**Annotations** (Part 3) — ✅ done, storage through to UI.

**Next: the passage index** (Part 1), phased per §1.11. Nothing about the
design changed; the work above only sharpened three inputs to it:

1. **The model switch (§1.4) is already done**, so Phase 0 starts at chunking
   rather than at a re-embed — and the book and passage spaces will match by
   construction. Remember the query prefix is asymmetric.
2. **Anchor positionally, not by containment** (Part 3). The failure mode is
   the same for chunks as for highlights, but far less visible: a chunk
   anchored to the wrong occurrence of a word still returns text, just from
   the wrong place on the page.
3. **Re-measure the relevance floors** if the chunk index gets its own (§1.4).
   The ones in `similarity.py` are calibrated for book-level metadata vectors
   and will not transfer to chunk scores unchanged.

**Then** the rest of §4.2 — passage-scoped threads and persistence — which
Part 1 makes worth doing, since that is when the retrieved context is actually
citable.

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

Added 2026-08-19, during implementation:

| Number | Method |
|---|---|
| Re-embed 618 books in 21 s | `python scripts/reembed.py`, batch 32, MPS, model cached |
| bge score band: real 0.655–0.834, nonsense 0.564–0.621 | Top `metadata_matrix @ encode_query(q)` over 6 real and 4 nonsense queries, 618 books |
| 50th result ≈ 0.84 of best (real), ≈ 0.91 (nonsense) | Same runs, `np.sort(scores)[::-1][49] / [0]` |
| Compare prompt ≈ 3,400 chars, 4 cited sources | `_build_prompt` on a real selection against the live catalog |
| Surrounding context 1,100 chars for a 150-char selection | Intercepted `POST /api/reading/analyze` body in the browser |
| 4 runs read `namedtuple`, 1 marked | `document.querySelectorAll` over the rendered text layer, p130 of the Python 3 Standard Library |

Re-measure after any model or hardware change; the float16 result in
particular is BLAS-dependent, and the **score band and relevance floors are
model-specific** — see §1.4.
