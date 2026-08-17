# 📚 Book Catalog Enrichment Pipeline

Builds an enriched metadata catalog from a local PDF/EPUB collection.

The pipeline's organising principle is that **a field may only be written
together with its source and confidence**, and **an external match must be
verified before it is applied** — not merely returned.

## How it works

```
┌─ COLLECT EVIDENCE ────────────────────────────────────────────┐
│  filename        → title guess, author guess, year, ISBN      │
│  embedded meta   → title, authors, publisher, language, ISBN  │
│  front matter    → title-page lines (positional), ISBN, pub   │
│  content sample  → prose past the TOC                         │
└───────────────────────────────┬───────────────────────────────┘
                                ▼
┌─ GENERATE CANDIDATES ─────────────────────────────────────────┐
│  ISBN lookups first, then field-scoped title/author queries    │
│  (`intitle:` / `title=`). BOTH providers are always queried.  │
└───────────────────────────────┬───────────────────────────────┘
                                ▼
┌─ VERIFY ──────────────────────────────────────────────────────┐
│  ISBN hit = 1.0, else weighted title/author/year similarity,  │
│  renormalised over the dimensions we have evidence for.       │
│    ≥ 0.75 → accept   0.45–0.75 → descriptive fields + review  │
│    < 0.45 → reject, and the rejection is recorded             │
│  Title-only evidence needs ≥ 0.85. Too little evidence to     │
│  score → no title search at all.                              │
└───────────────────────────────┬───────────────────────────────┘
                                ▼
┌─ MERGE ───────────────────────────────────────────────────────┐
│  Per field: highest (source rank × confidence) wins. Never    │
│  overwrite source == "user". Write field_sources alongside.   │
└───────────────────────────────────────────────────────────────┘
```

Source ranks (`catalog/models.py`): `user` 100 › `isbn_match` 90 ›
`api_verified` 80 › `file_meta` 60 › `front_matter` 50 › `filename` 40 ›
`api_partial` 30 › `analyzer` 20 › `llm` 15 › `derived` 10.

A borderline match may never write an identity field (title, authors, ISBNs,
year, publisher) or a cover — only description, page count and language.

## Quick start

```bash
pip install -r requirements.txt

python build_catalog.py --test              # 5 books, no API calls
python build_catalog.py                     # full run
python build_catalog.py --report            # quality report
python build_catalog.py --review            # what needs human confirmation
```

## Usage

```bash
# Scope
python build_catalog.py --only "Aisha.pdf" --only 757.pdf   # specific files (repeatable)
python build_catalog.py --max 20                            # first 20 books
python build_catalog.py --type epub                         # EPUBs only

# Stages
python build_catalog.py --no-api          # local extraction only
python build_catalog.py --no-ocr          # skip OCR of image-based PDFs
python build_catalog.py --llm             # Ollama summaries + borderline adjudication
python build_catalog.py --embed           # vector embeddings
python build_catalog.py --covers          # Playwright cover scraping

# Operations
python build_catalog.py --force           # ignore stage versions, redo everything
python build_catalog.py --workers 4       # parallel workers
python build_catalog.py --verify-sources  # probe each provider before running
python build_catalog.py --export-json     # write data/catalog.json (an export)
python build_catalog.py --export-csv
python build_catalog.py --changes         # filesystem vs catalog diff
python build_catalog.py --watch           # incremental folder watcher
python build_catalog.py --stats
python build_catalog.py --search "machine learning"
python build_catalog.py -v                # verbose
```

## Pipeline stages

Per book, in order. Each stage carries a version in `STAGE_VERSIONS`
(`config.py`); it re-runs only when that version is newer than the version
stored on the record, when the file's content hash changed, or under `--force`.

| Stage | Description |
|---|---|
| `scan` | Discover files, compute SHA1, capture size/mtime |
| `parse` | Filename → title, authors, publisher, year, ISBN, source ids |
| `extract` | PDF/EPUB metadata, cover, and text split into front matter / content sample / excerpt |
| `ocr` | OCR image-based PDFs (language chosen per book from the detected script) |
| `identify` | Harvest and validate ISBNs; read the title page positionally |
| `enrich` | Candidates from both providers → verification gate → provenance-aware merge |
| `analyze` | Categories (controlled vocabulary), themes, deterministic keywords, fallback summary |
| `llm` | Ollama summary, description, adjudication of borderline matches (optional) |
| `embed` | Vector embeddings of the content sample (optional) |

Closing stages run in a `finally` block, so an interrupted run still leaves a
consistent catalog: batched embedding → cover scraping → reading progress →
dedupe (over the whole catalog) → deletion reconciliation → save. A narrowed
run (`--only`, `--max`, `--type`) scopes the per-record closing stages to the
files it touched.

## Module map

```
catalog/
├── config.py              # every setting, env-overridable, loads .env
├── models.py              # BookRecord + set_field (provenance-aware writes)
├── schema.py              # canonical SQLite DDL, shared with the server
├── store.py               # CatalogStore — SQLite is the store of record
├── user_data.py           # ratings/tags/progress + pinned corrections
│
├── scanner.py             # file discovery, SHA1, basic record
├── title_parser.py        # filename → title/authors/publisher/year/ISBN
├── names.py               # is_person_name — one rejection predicate for all sources
├── isbn_extractor.py      # ISBN harvesting + check-digit validation, DOI/arXiv/IA ids
├── text_utils.py          # front matter vs content sample, title-page parsing, script/lang
├── pdf_extractor.py       # pypdf metadata, text, cover
├── epub_extractor.py      # ebooklib metadata, text, cover, calibre:isbn/dc:source
├── ocr_extractor.py       # pytesseract + pdf2image
│
├── evidence.py            # Evidence, Candidate, scoring, the verification gate
├── providers.py           # OpenLibrary + Google Books: session, retries, cache, rate limits
├── api_enricher.py        # orchestration: evidence → candidates → verify → merge
│
├── taxonomy.py            # canonical categories, alias map, subject filtering
├── theme_analyzer.py      # density-normalised categories/themes, deterministic keywords
├── llm_enricher.py        # Ollama: summaries, descriptions, match adjudication
├── embeddings.py          # sentence-transformers, batched
│
├── duplicate_detector.py  # content hash → trusted ISBN → corroborated fuzzy title
├── reading_tracker.py     # macOS Spotlight last-opened hints
├── cover_scraper.py       # Playwright cover fallback
├── watcher.py             # incremental folder watching
├── reporting.py           # quality report: fill rates, provenance, worst records
└── pipeline.py            # orchestrator: stage versions, workers, metrics
```

## Storage

`data/catalog.db` is the store of record — the pipeline writes it directly and
the web server reads it. `data/catalog.json` is produced only by
`--export-json`.

| Table | Contents |
|---|---|
| `books` | Everything the pipeline produces, including `field_sources`, `match_score`, `needs_review`, `review_reasons`, `rejected_candidates`, `stage_versions` |
| `user_data` | Ratings, tags, favourites, reading progress, pinned field corrections. **The pipeline never writes these** |
| `embeddings` | Content and metadata vectors |

Also on disk: `data/api_cache.json` (provider answers with an explicit status),
`data/covers/`, `data/processing_log.json`, `data/enrichment_report.json`.

## Record schema

- **File identity** — `id`, `content_sha1`, path, name, type, size, mtime, `status`
- **Bibliographic** — title, subtitle, authors, publisher, year, language, script, pages, ISBN-10/13, `source_ids`
- **Content** — description, summary, themes, `categories` (controlled), `subjects_raw` (external, searchable), keywords
- **Text** — `front_matter` (evidence, never embedded), `content_sample` (embedded and summarised), `text_excerpt` (reader preview)
- **Provenance** — `field_sources`, `match_score`, `needs_review`, `review_reasons`, `rejected_candidates`
- **Processing** — `has_text`, `ocr_required`, `api_sources`, `stage_versions`, `processing_errors`
- **User** *(in `user_data`)* — reading status, progress, rating, tags, favourite

## How it handles the hard cases

**Messy filenames.** Identifiers are extracted before the title is cleaned, so
an ISBN in the name is used rather than deleted. An `Author - Title` split needs
real whitespace around the dash, and which side is the author is decided by
`is_person_name`, not by position — so both orders work and
`Abu-Dhar-Al-Gifari-Struggle-for-Equality.pdf` is not read as author "Abu".

**Tool strings.** `/Producer` is never consulted for authorship, and every
author candidate from every source passes one rejection predicate, so
"Adobe InDesign CS5.5 (7.5)" cannot become an author and then poison a query.

**Thin evidence.** `Aisha.pdf`, `757.pdf` and `1658134075976.pdf` carry almost
nothing. Rather than accept whatever a search returns for a one-word query, the
pipeline requires an ISBN or a usable title before searching at all, and flags
the record otherwise.

**Front matter that lies.** Title pages carry journal headers, glyph junk and
adverts for the publisher's *other* books. Implausible lines are rejected; a
line echoing the filename wins ties; and an ISBN match that contradicts a strong
title page is downgraded to a review flag rather than silently trusted.

**Image-based PDFs.** Detected when extraction yields under 100 characters, then
OCR'd with a language pack chosen from the detected script.

**Duplicates.** Grouped by content hash, then by *trusted* ISBN (a low-confidence
identifier may not establish identity), then by fuzzy title corroborated by
author, year or page count. The canonical copy wins on metadata completeness,
text availability and size.

## Configuration

Everything lives in `catalog/config.py` and every setting accepts an environment
override:

```bash
OCR_LANGUAGE=eng+ara python build_catalog.py
MATCH_ACCEPT_THRESHOLD=0.8 python build_catalog.py
```

A `.env` file at the project root is loaded automatically (and is gitignored) —
the place for `GOOGLE_BOOKS_API_KEY`:

```
GOOGLE_BOOKS_API_KEY=your-key-here
```

Google Books' anonymous quota is small and per-IP, so bulk runs earn `429`s; the
pipeline throttles that host, backs off after a 429, and keeps going on
OpenLibrary alone. A key removes the problem.

Notable knobs: `MATCH_ACCEPT_THRESHOLD` (0.75), `MATCH_PARTIAL_THRESHOLD`
(0.45), `MAX_WORKERS` (4), `API_RATE_LIMIT_PER_SECOND`,
`API_NEGATIVE_CACHE_TTL_DAYS` (30), `DUPLICATE_TITLE_THRESHOLD` (90),
`OLLAMA_MODEL` (`qwen3.5:4b`), `EMBEDDING_MODEL`.

## Observability

The run summary reports per-source `attempted / ok / not_found / error /
throttled / cached` and shouts when a source's error rate crosses 20% — the
original catalog had OpenLibrary contributing **zero** records for months
without a single log line.

```bash
python build_catalog.py --verify-sources    # probe providers up front
python build_catalog.py --report            # fill rates, per-field provenance, worst records
python build_catalog.py --review            # the review queue on the command line
```

## Review queue

Records the gate could not confirm surface at `/review` in the web app and
through `/api/review`. A correction made there is pinned as `source: "user"`,
`confidence: 1.0`, stored in `user_data.field_overrides`, and re-applied after
every future run — including a full rebuild.

## Tests

```bash
./.venv/bin/python -m unittest discover -s tests
```

Covers the pathological filenames, the junk-author strings, the gate's
accept/partial/reject bands, ISBN harvesting and the controlled vocabulary.

## Web application

This catalog powers the web app described in the root
[`README.md`](../README.md): multi-mode search (text, semantic, hybrid), a
reactive filter sidebar, book pages with similar-book recommendations, an
LLM-assisted reading view, a statistics dashboard, and the review queue.
