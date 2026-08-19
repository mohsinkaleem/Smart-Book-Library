# Features & Improvements

A planning document for the Smart Book Library. Part 1 is a design for the
passage index — the piece that unlocks passage ↔ book ↔ catalog interaction —
and carries the detail. Parts 2–5 are the rest of the roadmap at planning depth.

Every number in this document was measured on this machine against this
library on 2026-08-19, not estimated. Measurement commands are in
[Appendix A](#appendix-a--how-the-numbers-were-measured).

## Status

Implemented on 2026-08-19: the quick wins, all of Part 3, the embedding model
switch from §1.4, and then **the whole of the remaining roadmap** — Part 1
through Part 5. Sections that have shipped are marked **✅ Shipped** and
rewritten in the past tense.

| Part | State |
|---|---|
| **1 — Passage index** | ✅ Shipped. Schema, chunker, build pipeline, hybrid retrieval, all endpoints, and the §1.9 features. Built over a 59-book vertical slice; the full build is one command. |
| **2 — Reading experience** | ✅ Shipped in full. Page thumbnails and the EPUB locations index closed the last two gaps. |
| **3 — Annotations** | ✅ Shipped in full. |
| **4 — LLM layer** | ✅ Shipped. §4.1 fixed earlier; threads and persistence closed §4.2. Model capability is the one item left as a judgement call, not a build. |
| **5 — Other** | ✅ Shipped. Reading sessions, Markdown export, duplicate resolution UI, and OCR surfacing plus an on-demand script. |

The build is at **262 backend tests and 45 frontend tests** (`pytest` and
`npm test --prefix frontend`), up from 199 and 45.

### What the implementation changed about the plan

Four things were only visible once the code ran, and are recorded where they
belong rather than here:

* Highlight anchoring needs *positional* matching, not text containment —
  §3 and `pdfHighlight.ts`. Chunk anchoring inherited it — §1.5.
* The relevance floors in `similarity.py` are model-specific and had to be
  re-measured for bge — §1.4. **The chunk index needed its own, and they came
  out the opposite way round** — §1.8.
* EPUB navigation has exactly one owner, or it renders blank pages — §2.2.
  A second owner appeared during Part 1 and cost three EPUB fetches per open —
  §2.1.
* `is_mostly_boilerplate` gating (§1.5) was the right call, and needed a
  second filter beside it — §1.5.

### The four findings from building Part 1

Each is written up where it belongs; collected here because they are the
things a reader of the original plan would not have predicted.

1. **At chunk scale the *absolute* relevance floor works and the *relative*
   one does not** — the reverse of the book-level result in §1.4. Measured in
   §1.8.
2. **The relevance floor has to be applied after fusion, not inside the dense
   search.** Applied only to the dense side, every BM25 hit entered the ranking
   unfiltered and "zebra husbandry in antarctica" came back with five results.
   §1.8.
3. **A fusion score is not a similarity score.** RRF lives around 0.03, and
   returning it as `score` made every result read as a 3% match *and* made the
   floors unenforceable. Two fields now. §1.8.
4. **A recurring passage is not automatically a concept.** The first run of
   §1.9.4 over a conference proceedings returned four threads at strength
   0.935, every one of them a bibliography. §1.9.4.

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

### 1.5 Chunking strategy — ✅ Shipped

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
exists for this and gates chunk creation — an index full of copyright
boilerplate makes unrelated books look similar, which is the exact failure the
existing `_content_text` comment warns about.

**What shipped** — `catalog/chunking.py`, pure and covered by 21 unit tests.

Sizing and structure are as designed. Two things the plan did not anticipate:

* **`is_mostly_boilerplate` alone was not enough.** It reads the first 800
  characters and wants three hits, which a contents page ("Copyright" +
  "Table of Contents" = two) walks straight through. A second gate on
  `prose_score` — which returns 0 outright for anything with dot leaders —
  catches contents pages, endnote lists and index tails. Measured over four
  books it drops 0–12% of candidates, and what it drops is exactly right.

* **...but not every book is prose.** A command reference or a code cookbook
  scores low on every page, and dropping it out of the index entirely is a far
  worse answer than indexing its code blocks. The filter stands down when it
  would take more than 60% of a book. `test_reference_material_survives_the_prose_floor`
  pins this.

`chunk_idx` numbers the *kept* passages contiguously, because "the next passage
in this book" has to mean the next one a reader can be shown.

Measured on this library: ~1,378 characters per chunk on average, ~400 chunks
per book.

### 1.6 Schema — ✅ Shipped

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

### 1.7 Build pipeline — ✅ Shipped

A new opt-in stage in `catalog/pipeline.py`, following the existing stage
conventions so `stage_versions` gates re-runs:

1. **Extract full text** — lift the 14-page cap for this stage only. Write to
   `data/text/{book_id}.txt` rather than into the `books` row; 340 MB does not
   belong in a column that every list query reads.
2. **Chunk** — §1.5, with anchors.
3. **Embed** — batched, `normalize_embeddings=True`, no query prefix.
4. **Write** — `chunks` rows, `chunks_fts` populated by trigger, vectors
   appended to the `.npy`, `chunk_index_meta` stamped.

**Measured cost — projected, then actual**

| Stage | Projected | Measured |
|---|---|---|
| PDF text extraction | ~36 min (pypdf, 11.6 ms/page) | **1.5–2.9 ms/page with PyMuPDF** — 4–8× faster, so ~5–9 min single-threaded over 186,969 pages |
| Embedding | ~23 min at 199 chunks/s | **~94 chunks/s** at the shipped 1,378-char chunk size; 23,920 chunks took 4½ min |
| **Vertical slice (59 books)** | — | **23,920 chunks, 275 s, 18 MB of vectors, 30 MB of text** |

Extrapolating the slice: the full 618-book library is roughly 250k chunks,
~50 min of embedding, ~190 MB of vectors and ~340 MB of text.

> **pypdf was the bottleneck and it was replaceable.** PyMuPDF is now a core
> dependency and the extraction stage runs on it. Note its AGPL licence — that
> was a deliberate choice, taken with the trade-off stated.

**What shipped**

* `catalog/full_text.py` — full-document extraction with a per-page (PDF) or
  per-spine-item (EPUB) **offset map**, cached to `data/text/{book_id}.txt`
  with a `.json` sidecar. The offset map is the whole reason this is not
  `"".join(pages)`: it is what makes anchoring positional.
* `catalog/passage_index.py` — the builder. It owns the id space and renumbers
  every chunk on every build, because `chunks.id == row index into the .npy` is
  only worth having if nothing can drift.
* **Rewriting the vector file does not mean re-embedding the library.** Vectors
  for untouched books are carried over by `(book_id, chunk_idx)`. Verified:
  adding one book to a 58-book index reused 23,897 vectors and embedded 23, in
  16 seconds.
* `scripts/build_passage_index.py`, with `--limit`, `--force`, `--status` and
  `--drop`. Resumable by construction.

**Two traps the plan did not name:**

* `np.save` appends `.npy` unless the name already ends in it, so a temp file
  called `chunk_vectors.npy.tmp` is written as `chunk_vectors.npy.tmp.npy` and
  the rename looks for a file numpy never wrote.
* A build in which every target book fails must not be allowed to wipe an index
  that was working a moment earlier.

**Incremental updates.** `catalog/watcher.py` already detects changes. On a
changed book, delete its chunk rows and re-chunk just that book; mark the
vector file dirty and compact it on a schedule rather than rewriting 418 MB per
book.

### 1.8 Runtime — ✅ Shipped

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

**Search paths**, measured on the shipped 23,920-chunk index:

| Query | Filter | Projected | Measured |
|---|---|---|---|
| Elsewhere in this book | contiguous slice | 0.003 ms | **0.008 ms** (1,295 chunks) |
| Across the catalog | exclude current book | 4.8 ms | **0.30 ms** (23,920 chunks) |
| Within a category / author / shelf | id set intersection | <5 ms | **0.30 ms** |

The in-book slice is free because the builder writes each book's chunks
contiguously, so the matrix is sliced *before* the matmul rather than masked
after it. `PassageIndex.load` verifies that contiguity rather than assuming it:
if a future builder breaks it, the slice would silently return another book's
passages.

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

`POST /api/reading/compare` was reimplemented on the chunk index and keeps its
response shape. `excerpt` is now the real matching passage with a page anchor
and a deep link. Books the index has not reached fall back to book-level
matching, flagged `is_passage: false` with no page — honest about being a book
recommendation rather than a passage match.

### The three retrieval findings

**1. The chunk index needed its own relevance floors, and they came out the
opposite way round.** §1.4 warned the floors would not transfer. They did not,
but not as expected. Re-measured with the §1.4 protocol on 23,920 chunks:

| | top score | 50th / best |
|---|---|---|
| Six real queries | 0.694 – 0.844 | 0.88 – 0.95 |
| Four nonsense queries | 0.609 – 0.642 | 0.89 – 0.95 |

At book level the two *absolute* bands nearly touched (0.03 apart) and the
relative floor did the discriminating. At chunk level it is the reverse: the
absolute bands separate cleanly by 0.05, and the relative bands **overlap
completely** — there is no gap to put a cutoff in.

That is the shape of the data, not noise. A ranking over 618 book vectors goes
flat for a nonsense query because nothing is genuinely more relevant than
anything else; a ranking over 23,920 passages is always steep, because *some*
passage is always more textually similar to any input than the 50th is. So the
shape stops carrying signal and only the height does. Floors: **0.66** absolute,
**0.80** relative as a long-tail trim only. Passage-to-passage comparison is a
third distribution again (second-best match 0.867–0.923, 200th 0.689–0.716) and
gets its own floor of **0.75**.

**2. The floor has to be applied after fusion, not inside the dense search.**
Applied only to the dense side — the obvious place — every BM25 hit entered the
fused ranking unfiltered. "Zebra husbandry in antarctica" returned five
results, because three rare words each matched *something* and RRF ranked them
happily. A lexical hit is a proposal; whether it is relevant is still a cosine
question, and answering it costs one gather and one dot product. After the fix
all three nonsense queries return 0.

`keyword` mode is the deliberate exception: §1.9.5 is "every mention of X",
where an exact term match *is* the answer and a semantic floor would suppress
precisely the rare-word hits being looked for.

**3. A fusion score is not a similarity score.** RRF is a sum of reciprocal
ranks and lives around 0.03. Returning it as `score` made every result read as
a 3% match, and — worse — made the floors unenforceable, because they are
cosine thresholds and RRF is not a cosine. `score` and `rrf` are separate
fields now. The same mistake recurred once more in `keyword` mode, where BM25
(unbounded, and 11.04 on this index) was rendered as **1104%**.

**Cross-encoder reranking** (§1.11 phase 2) shipped behind `PASSAGE_RERANK`,
off by default: the model is an ~80 MB download and a surprise download on
someone's first search is not a feature. A failure to load is recorded once and
falls back to the fused order — a reranker that cannot load must cost one
warning, not one per query.

### 1.9 Features this unlocks — ✅ Shipped

#### 1.9.1 Elsewhere in this book — ✅ Shipped
The same idea recurring in chapter 2 and chapter 11. Frequently more valuable
than cross-book matching, previously impossible, and — as predicted — the
cheapest query in the system at 0.008 ms.

`POST /api/passages/similar` with `scope: "book"`, surfaced as the **This book**
tab of the reader's Passages panel. The selection's own chunk is filtered out;
a 1.0 match with itself tells the reader nothing.

#### 1.9.2 Real cross-book passages — ✅ Shipped
The actual matching paragraph, its page number, and a deep link. The existing
feature finally telling the truth.

**The before and after, measured on the same kind of selection.** Against
book-level vectors, a passage on the state's production of the category of
religion returned books that were *topically* right — Islam & Politics, and so
on — scored 0.58–0.61, with an excerpt from each book's opening pages rather
than anything resembling the selection.

Against the chunk index, a selection from a book of fiqh on who is exempt from
fasting in Ramaḍān returns **the corresponding passage in Hallaq's
*The Impossible State*, chapter 3, at 79%** — the actual argument, with its
section and a link that opens the book there. That is the difference the whole
of Part 1 was for.

Cross-book match rates on the 59-book slice: 6 of 8 sampled selections return
real passages; the other 2 have a genuine cross-book ceiling of 0.72–0.73,
below the 0.75 floor, and correctly fall back to book-level matching. The
fallback rate drops as the index grows.

#### 1.9.3 Agreement vs. disagreement — ✅ Shipped
`POST /api/passages/stance`. Retrieved passages are handed to the model
numbered, and it sorts them into **supports / complicates / contradicts** with
a one-line justification each. It is never asked to recall anything, and every
returned item keeps its `chunk_id` and page, so each claim stays citable.

Two things the plan did not account for, both consequences of a 4B model:

* **JSON is a request, not a guarantee.** A failed parse falls back to line
  scraping rather than discarding a usable answer.
* **Anything unassigned is reported as `unsorted`, never dropped.** A passage
  the model failed to mention is still a real retrieved passage the reader
  should see.

#### 1.9.4 Concept threads — ✅ Shipped
`GET /api/books/{id}/threads`. Every passage in a book against every other —
a ~600×600 matmul, well under a millisecond — with neighbouring chunks excluded
by construction, since they overlap by design and would otherwise make every
"thread" a chunk plus its two neighbours.

**The finding: a recurring passage is not automatically a concept.** The first
run over a conference proceedings returned four threads at strength 0.935, and
every one of them was a *bibliography*. Each paper in the volume ends in a
reference list, and reference lists resemble each other far more than any two
arguments do. They are recurring, and they are not a finding.

Seeds are now filtered to passages that read as argument rather than apparatus,
on three cheap signals a bibliography trips and prose does not: digit density,
citation vocabulary, and having almost no sentences. On the same book the
threads became real subject matter; on a prose book they are chapter-spanning
arguments, which is what §1.9.4 promised.

Scoped to one book rather than the catalog, and not ordered by publication
year — the cross-catalog, chronological version the plan describes is a
worthwhile follow-on and is what the `/api/passages/search` scope filters
already support.

#### 1.9.5 Library-wide full-text search — ✅ Shipped
"Every mention of X across all 618 books," a by-product of the same build, at
`/passages` in the UI with three modes.

`keyword` mode exists precisely because the relevance floor must not apply
here: an exact term match *is* the answer, and the floor would suppress the
rare-word hits being looked for. That is a real behavioural difference, not a
label — see finding 2 in §1.8.

### 1.10 Risks

| Risk | Mitigation |
|---|---|
| float16 matmul is 32× slower | Upcast at load. Documented in §1.3. |
| Mixing MiniLM and bge vectors | ✅ Handled. Book-level vectors re-embedded; `embeddings.model_id` stamped per row; `load_embeddings` skips non-matching rows and logs it. |
| bge query prefix used symmetrically | ✅ Handled. Two functions rather than a flag: `encode_query` prefixes, `encode_passage` never does. |
| 19 OCR-required books silently absent | ✅ Handled. The build skips them by `has_text`, the book page says *"No text layer"* and names the fix, and `scripts/ocr_books.py` runs OCR on demand. Actually running it is opt-in — hours of compute at 300 DPI. |
| Relevance floors tuned to the wrong model | ✅ Handled at both levels. The chunk index got its own, re-measured — and they behave **the opposite way round** from the book-level ones. §1.8, finding 1. |
| Anchors matched by containment rather than position | ✅ Handled. Chunks carry character spans and their page is bisected out of the offset map; nothing searches the document for a chunk's text. Pinned by `test_repeated_phrase_is_anchored_by_position_not_containment`. |
| Boilerplate polluting the index | ✅ Handled, and it took two gates — `is_mostly_boilerplate` walks straight past a contents page. See §1.5. |
| EPUB anchors are approximate | ✅ Shipped as designed. `spine_index` gets the reader to the section, `anchor_text` is searched inside it, and a miss leaves them at the top of the right chapter rather than nowhere. |
| 418 MB resident | Not yet a problem: the 59-book index is **35 MB resident**, and the full library extrapolates to ~380 MB. int8 + rescore remains the answer if it becomes one. |
| Disk growth ~900 MB | Measured on the slice: 30 MB text + 18 MB vectors for 59 books, so the full library is ~340 MB text + ~190 MB vectors (float16 halves the projection) + FTS. Documented in §1.7. |

### 1.11 Phasing

| Phase | Deliverable | State |
|---|---|---|
| **0** | Vertical slice: schema, extraction, embedding, endpoints, "elsewhere in this book" in the sidebar. | ✅ Done, over **59 books / 23,920 chunks**. |
| **1** | `/api/reading/compare` reimplemented with real excerpts and deep links. | ✅ Done. The full index build is `python scripts/build_passage_index.py` with no arguments — resumable, and it carries existing vectors over. |
| **2** | Hybrid RRF + cross-encoder reranking; library-wide full-text search. | ✅ Done. Reranking is behind `PASSAGE_RERANK`, off by default. |
| **3** | Stance grouping; concept threads. | ✅ Done. |

**The one thing left from Phase 1 is compute, not code.** The index covers 59
of 618 books because that was the scope chosen for this pass. Everything —
endpoints, UI, fallbacks — behaves correctly on a partial index and gets better
as it grows:

```bash
python scripts/build_passage_index.py          # index the rest, ~50 min
python scripts/build_passage_index.py --status # what is in there now
```

---

## Part 2 — Reading experience

### 2.1 Missing features — ✅ All shipped

| Feature | State |
|---|---|
| **In-document search** | ✅ Shipped, both formats. |
| **PDF outline / TOC** | ✅ Shipped. |
| **Reading themes** | ✅ Shipped — five, incl. `auto`. |
| **EPUB typography** | ✅ Shipped — face, line height, margins. |
| **Bookmarks** | ✅ Shipped, as an annotation kind (Part 3). |
| **Fit width / fit page** | ✅ Shipped. |
| **Page thumbnails** | ✅ Shipped. Virtualised strip, toggled with `P`. |
| **EPUB locations index** | ✅ Shipped. Generated once, cached in `epub_locations`, exact "page X of Y" thereafter. |

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

**Page thumbnails.** Virtualised on scroll position rather than with an
observer per slot: every row is the same height, so the visible range is
`scrollTop / rowHeight` and 1,454 IntersectionObservers to compute a number
arithmetic already gives is a lot of machinery for nothing. The row height is
*measured* from a rendered row rather than hardcoded, because page aspect
ratios differ between documents and a wrong constant makes the scrollbar lie by
a factor that grows with the page count.

Windowed for the same reason as §2.2's `renderedRange` leak — a thumbnail is
still a canvas, and mounting all of them is that bug again in miniature:
smaller canvases, four times as many. Verified on a 31-page book: 12 thumbnails
mounted, following the current page.

The strip renders outside the reader's `<Document>`, so it passes the
`PDFDocumentProxy` to each `<Page>` directly rather than taking it from context.

**EPUB locations index.** Generated once in the background, posted to
`POST /api/books/{id}/locations`, and restored on every later open with
`locations.load()` — a parse rather than a walk. Until it lands the reader
keeps the spine ratio, which is coarse but not wrong.

**Two things this cost, both about not fighting the reader for the main thread
and not fighting it for ownership:**

* **The walk has to wait for the first paint.** Started on `book.ready` it
  races the initial render and the reader shows an empty page for the length of
  the walk. It is deferred until the first `relocated` event — i.e. until there
  is text on screen — and then yields a frame before starting.
* **A `setState` inside `getRendition` tears the rendition down.** Handing the
  book object to the locations hook with a bare `setState` re-rendered the
  reader from inside its own rendition callback; react-reader responded by
  rebuilding the rendition, which called the callback again. **The EPUB was
  being fetched three times per open.** Guarded through a ref, it is fetched
  once. This is §2.2's "EPUB navigation must have exactly one owner" in a
  second costume — the owner rule extends to anything that can re-render the
  reader, not just to navigation.

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

### 4.2 Improvements — ✅ Shipped

- **The model sees the selection and nothing else.** ✅ Done. The request
  carries `surrounding` — the prose around the selection, taken from its
  enclosing block — plus the book's author, year, categories and themes.
  Measured live: a 150-character selection ships with 1,100 characters of
  surrounding page text.

  The climb to find that block is the whole job, and got it wrong once:
  stopping at the first enclosing element returns the *selected paragraph*,
  which is nothing the model does not already have, because selecting a whole
  paragraph is the common case. It now climbs until an ancestor carries
  meaningfully more text than the selection — and stops at `body`, since
  walking past it reaches the Document node, whose `textContent` is null and
  wiped the result. Chapter title is still not sent; there is no reliable
  source for it in either reader yet.

- **No follow-up** and **nothing is saved** — ✅ Both closed, and they turned
  out to be *one* feature. What makes a follow-up answerable is the same thing
  that makes the exchange worth keeping: a frame that outlives the request.

  A **thread** is scoped to a passage. The selection, the surrounding prose and
  the retrieved context are pinned at creation and replayed into every turn, so
  "why?" refers to something the model can still see. Because that frame is
  stored rather than assembled per request, the conversation survives closing
  the reader.

  Four decisions worth recording:

  * **Ollama's `/api/chat`, not a hand-rolled transcript.** Replaying an
    exchange into `/api/generate` as one `"User: … Assistant: …"` string is the
    usual reason a follow-up answer starts hallucinating a new question — the
    model applies its own chat template to role-tagged turns, and a fake one
    fights it.
  * **The pinned frame rides in the system message**, so it is stated once and
    stays in front of the model instead of scrolling out of a 4k window behind
    the conversation. History is capped at 12 turns; the grounding is not.
  * **Only the title is editable.** Changing a thread's passage or context
    would leave every stored answer grounded in material no longer shown, which
    reads as the model having invented it.
  * **The assistant turn is written after the stream completes**, from the
    accumulated text. Per-token would rewrite a growing row on every token;
    before would leave an empty answer behind whenever generation failed —
    worse than no message, because it looks like an answer.

  `retrieve: true` at creation is the default: fixed context is the point, and
  re-retrieving per turn would change the model's evidence under the reader.

- **Ground every citation.** ✅ Now true for passages, not just books. With the
  chunk index the retrieved block carries a real page (`[1] Title — Author,
  p. 212`), so the model can attribute a claim to a place rather than to a
  book. That was the part §4.1 could not deliver and explicitly deferred here.

- **Model capability.** Still a judgement call rather than a build. `OLLAMA_MODEL`
  defaults to `qwen3.5:4b`; stance grouping (§1.9.3) is the feature that most
  rewards a larger model, and it is built to degrade rather than fail on a
  small one — a reply that is not clean JSON is scraped, and anything
  unassigned is shown as `unsorted`. Worth evaluating a larger model against
  stance specifically before concluding the feature is weak.

---

## Part 5 — Other — ✅ Shipped

- **Reading sessions.** ✅ A `reading_sessions` table, filled by a heartbeat
  from both readers, feeding pages/week, streaks and time-to-finish into the
  Dashboard.

  **The design point is that sessions are heartbeat-closed, not close-closed.**
  The obvious shape — open on mount, close on unmount — loses to the way people
  actually stop reading, which is closing the laptop. There is no unmount event
  for that, and a session left open reports a fourteen-hour reading day. So the
  reader beats every 60 s, each beat moves `ended_at` forward, and a beat
  arriving more than 15 minutes after the last starts a new session instead of
  extending an abandoned one. The worst case is losing the final interval.

  Beating pauses while the tab is hidden — otherwise a book left open in a
  background tab overnight logs the night as reading, which is the same bug in
  a different costume. Sessions under 30 seconds are excluded everywhere: those
  are page-flips, and counting them would pad the streak with every accidental
  click into a book. Paging backwards to re-read cannot produce negative pages.

- **Export** highlights, notes and LLM threads to Markdown. ✅
  `GET /api/export/markdown`, whole library or one book, with a download button
  on the book page. A formatter over what `/api/annotations` and `/api/threads`
  already return — it holds no knowledge those endpoints do not.

- **Duplicate resolution in the UI.** ✅ `/duplicates`, surfacing what
  `catalog/duplicate_detector.py` and the `duplicate_of` column have recorded
  since the pipeline shipped. It found **23 groups** on this library, including
  the Chip Huyen duplicate this document predicted — with three copies, not two.

  **Nothing there deletes a file, and the page says so.** Resolving a duplicate
  reassigns `duplicate_of` and changes which copy the library shows. Deciding
  which of two files on disk to destroy is the user's call to make in a file
  manager, and a wrong call is not recoverable from inside this app. A test
  asserts the module contains no deletion call at all.

  A group whose canonical book has left the catalog is still reported, flagged
  `orphaned` — otherwise its copies are marked as duplicates of an invisible
  record with no screen on which to unmark them.

- **OCR the 19 image-only books.** ✅ *Surfaced*, and runnable on demand;
  deliberately not run. The book page now says **"No text layer"** and names
  the fix, so a scanned book reads as a scanned book rather than as a broken
  reader — which is §1.10's ask. `scripts/ocr_books.py` does the work
  (`--list`, `--book <id>`, `--all`, `--reindex`), and it stays opt-in because
  rendering at 300 DPI and running tesseract over 19 books is hours of compute.
  The passage-index builder excludes them by `has_text`, so they are absent by
  decision rather than by accident.

---

## Roadmap — ✅ Complete

**Quick wins** — ✅ done. `context` into the compare prompt (§4.1) · PDF
outline · in-document search · reading themes · the `renderedRange` leak ·
selection toolbar · fit-width/fit-page · EPUB typography.

**Annotations** (Part 3) — ✅ done, storage through to UI.

**The passage index** (Part 1) — ✅ done, all four phases. The three inputs
this document sharpened for it all held up:

1. **The model switch (§1.4) was already done**, so Phase 0 started at chunking
   and the book and passage spaces match by construction. The query prefix is
   asymmetric and is handled by two functions rather than a flag.
2. **Anchor positionally, not by containment** (Part 3). Carried over intact,
   and pinned by a test named for the failure.
3. **Re-measure the relevance floors** (§1.4). Necessary, and the result was a
   genuine surprise — the chunk index's floors behave the opposite way round
   from the book-level ones. §1.8, finding 1.

**The rest of §4.2** — ✅ done. Passage-scoped threads and persistence, which
Part 1 made worth doing: the retrieved context pinned into a thread is now
citable to a page.

**Parts 2 and 5** — ✅ done.

### What is left

Three things, none of them blocked on code:

1. **Index the other 559 books.** One command, ~50 minutes. Everything behaves
   correctly on a partial index — book-level fallback, honest empty states —
   and improves as it grows.
2. **Evaluate a larger `OLLAMA_MODEL`**, against stance grouping specifically
   (§4.2).
3. **OCR the 19 scanned books**, if they matter to you. Hours of compute;
   `scripts/ocr_books.py --all --reindex`.

Worthwhile follow-ons, in rough order of value: concept threads across the
*catalog* ordered by publication year rather than within one book (§1.9.4);
a highlight used directly as a retrieval query, which Part 3 anticipated
(*"show me everything in the library related to what I just highlighted"*);
and an LLM entity pass to sharpen threads (approach 9 in §1.2).

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

Added 2026-08-19, while building Parts 1–5:

| Number | Method |
|---|---|
| PyMuPDF 1.5–2.9 ms/page | `pymupdf.open(...).get_text()` over four books, 2,625–4,239 pages each |
| 23,920 chunks over 59 books in 275 s | `python scripts/build_passage_index.py --limit 30`, run twice |
| ~94 chunks/s embedding | Same run: 23,897 chunks, batch 32, MPS, 1,378-char average chunk |
| Chunk avg 1,378 chars, ~400 chunks/book | `select avg(length(text)), count(*)/count(distinct book_id) from chunks` |
| Carry-over: 23,897 reused, 23 embedded, 16 s | Second `--limit 2` build against the 58-book index |
| Chunk score band: real 0.694–0.844, nonsense 0.609–0.642 | `chunk_matrix @ encode_query(q)` over the same 6 real / 4 nonsense queries as §1.4 |
| 50th/best: real 0.88–0.95, nonsense 0.89–0.95 | Same runs, `np.sort(scores)[::-1][49] / [0]` |
| Passage-to-passage: 2nd-best 0.867–0.923, 200th 0.689–0.716 | `encode_passage` on six chunks drawn from the index, ranked against it |
| 0.30 ms catalog / 0.008 ms single book | NumPy matmul + `argpartition`, N=23,920×384, 20 iterations |
| 35 MB resident, 18 MB on disk | `matrix.nbytes` at load; `ls -la data/chunk_vectors.npy` |
| Cross-book: 6 of 8 return passages, 2 ceiling 0.72–0.73 | `/api/reading/compare` on 8 chunks sampled across the index |
| Hallaq match at 79% | Passage panel, Library tab, on a fiqh passage about exemptions from fasting |
| BM25 reached 11.04 (rendered as 1104%) | `keyword` mode on the live index before the score fix |
| 23 duplicate groups | `GET /api/duplicates` on the live catalog |
| EPUB fetched 3× per open, then 1× | `read_network_requests` on `/api/books/{id}/file.epub`, before and after the ref guard |
| Prose floor drops 0–12% of candidates | `prose_score(chunk) < 200` over four books' chunk sets |

Re-measure after any model or hardware change; the float16 result in
particular is BLAS-dependent, and the **score bands and relevance floors are
model-specific** — see §1.4 and §1.8, which now hold two different sets of them
for the same model at two different granularities.
