# Enriching the Catalog

How to (re)build the book catalog, from a clean slate or by resuming a previous
run, and what each stage actually does.

## Prerequisites

**Always required**
- Python venv with `pip install -r requirements.txt` (core deps: `pypdf`,
  `ebooklib`, `beautifulsoup4`, `Pillow`, `requests`, `rapidfuzz`, `numpy`).
- Network access to `openlibrary.org` and `www.googleapis.com` (skip with
  `--no-api`).
- Book files under `epubs/` and/or `pdfs/`.

**Optional, per feature**
| Feature | Flag | Extra requirement |
|---|---|---|
| Embeddings / semantic search | `--embed` | `pip install sentence-transformers` (~2 GB, pulls in torch) |
| OCR for image-based PDFs | (on by default, skip with `--no-ocr`) | `pip install pytesseract pdf2image` + `brew install tesseract poppler` (plus language packs for non-English scripts) |
| LLM summaries + adjudication | `--llm` | `ollama serve` running locally with the model in `OLLAMA_MODEL` (default `qwen3.5:4b`) pulled — `ollama pull qwen3.5:4b` |
| Cover scraping | `--covers` | `pip install playwright` then `playwright install chromium` |
| Folder watching | `--watch` | `pip install watchdog` |
| Higher Google Books rate limit | — | `GOOGLE_BOOKS_API_KEY` in `.env` (optional but recommended for large libraries) |

Check what's actually available before a big run:
```
python build_catalog.py --verify-sources --plan
```

## Running from fresh (wipes everything)

This deletes the SQLite store, JSON export, API cache, covers, and logs, then
reprocesses every book from scratch (slow — re-downloads covers and re-queries
every API for every book).

```bash
rm -f data/catalog.db data/catalog.db-shm data/catalog.db-wal \
      data/catalog.json data/api_cache.json data/processing_log.json \
      data/enrichment_report.json
rm -rf data/covers data/text_excerpts
mkdir -p data/covers data/text_excerpts

python build_catalog.py --llm --embed
```

Drop `--llm --embed` for a faster, API-only pass; add `--covers` if you also
want cover scraping in the same run.

## Resuming a previous / interrupted run

Nothing needs to be deleted. The pipeline is resumable by default:

```bash
python build_catalog.py --llm --embed
```

Each book carries a per-stage version and a content hash in `data/catalog.db`.
A stage (`parse`, `extract`, `ocr`, `identify`, `enrich`, `analyze`, `llm`,
`embed`) only re-runs when:
- the book has no record yet,
- its file content changed since last time, or
- the stage's version in `catalog/config.py` (`STAGE_VERSIONS`) is newer than
  what's recorded, or
- the stage was *deferred* last time: a provider errored or throttled us and no
  match was accepted, OCR tools were missing, or Ollama was down / returned
  nothing. The run summary reports these as `deferred`.

So re-running the same command after a Ctrl+C, crash, or network timeout just
picks up the remaining/failed books — already-enriched ones are skipped. Use
`--plan` first to preview what would run without writing anything:

```bash
python build_catalog.py --llm --embed --plan
```

To force a full redo of everything (ignoring stage versions, but without
deleting data first):
```bash
python build_catalog.py --force --llm --embed
```

Useful narrowing flags while testing: `--test` (5 books, no API calls),
`--only "somefile.pdf"` (repeatable), `--max 20`, `--type epub`.

## What the pipeline does, stage by stage

1. **Scan** — walks `epubs/` and `pdfs/` for supported files.
2. **Parse / Extract** — pulls text, metadata, and front matter from each PDF/EPUB.
3. **OCR** (optional, default on) — runs Tesseract on image-only PDF pages.
4. **Identify** — harvests ISBNs from filename, front matter, and text.
5. **Enrich** (API) — queries OpenLibrary/Google Books, scores candidates
   against local evidence, and merges verified metadata (title, authors,
   publisher, year, categories, cover URL, etc.).
6. **Analyze** — maps subjects to a controlled taxonomy of categories/themes.
7. **LLM** (`--llm`) — Ollama-generated summaries and adjudication of
   borderline metadata matches.
8. **Embed** (`--embed`) — vector embeddings of a content sample for semantic
   search.
9. **Covers** (`--covers`) — Playwright scrape for books still missing a cover.
10. **Reading progress** (`--reading-progress`) — refreshes last-opened times
    from Spotlight (macOS only).
11. **Duplicate detection** — flags likely duplicate books.
12. **Save** — writes `data/catalog.db` (source of truth) and, with
    `--export-json`, `data/catalog.json`.
13. **Report** — writes `data/enrichment_report.json`; view with
    `python build_catalog.py --report`.

## After a run

```bash
python build_catalog.py --stats     # catalog statistics
python build_catalog.py --report    # quality report
python build_catalog.py --review    # records flagged for manual review
```
