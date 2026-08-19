"""
Building the passage index (§1.7).

Extract full text → chunk → embed → write. The output is three things that
must agree with each other or the index returns confident nonsense:

* ``chunks`` rows, whose ``id`` is the row index into the vector file;
* ``data/chunk_vectors.npy``, float16 on disk;
* one ``chunk_index_meta`` row stamping the model, dimension and chunk sizing.

**Why ids are assigned here and the vector file is rewritten whole.** The whole
value of `chunks.id == row index` is that a top-k result maps back to its text
with a single `WHERE id IN (...)`, with no join table and no per-row offset
bookkeeping. Keeping row indices stable across deletes would mean maintaining
a free list and a compaction pass, which buys nothing at this scale and gets
the mapping wrong exactly once, silently, in a way no test would catch. So the
builder owns the id space: it renumbers every chunk on every build.

**Rewriting the file does not mean re-embedding the library.** Vectors for
books that were not re-chunked are carried over from the previous file by
(book_id, chunk_idx), so adding one book costs one book's worth of embedding —
which is what makes `catalog.watcher`'s incremental updates affordable.

    float16 on disk, float32 in memory.
    Never matmul in float16: NumPy has no float16 BLAS path and upcasts
    elementwise on every query, which measures 32x *slower*, not faster.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

import numpy as np

from .chunking import Chunk, chunk_document
from .config import (
    CHUNK_OVERLAP_CHARS,
    CHUNK_TARGET_CHARS,
    CHUNK_VECTORS_FILE,
    EMBEDDING_BATCH_SIZE,
)
from .full_text import clear_cached, get_full_text
from .schema import ensure_schema

logger = logging.getLogger(__name__)

VECTOR_DTYPE = np.float16          # on disk
COMPUTE_DTYPE = np.float32         # in memory, always


@dataclass
class BuildResult:
    books_indexed: int = 0
    books_skipped: int = 0
    books_failed: int = 0
    chunks_written: int = 0
    chunks_reused: int = 0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "books_indexed": self.books_indexed,
            "books_skipped": self.books_skipped,
            "books_failed": self.books_failed,
            "chunks_written": self.chunks_written,
            "chunks_reused": self.chunks_reused,
            "seconds": round(self.seconds, 1),
            "errors": self.errors[:20],
        }


# ── Reading what is already there ───────────────────────────────────────────

def index_status(conn: sqlite3.Connection) -> dict:
    """What the index currently holds. Safe on a database that has never built one."""
    ensure_schema(conn)
    row = conn.execute(
        "SELECT model_id, dim, count, book_count, dtype, built_at, chunk_chars, chunk_overlap "
        "FROM chunk_index_meta WHERE id = 1"
    ).fetchone()
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    books = conn.execute("SELECT COUNT(DISTINCT book_id) FROM chunks").fetchone()[0]
    return {
        "built": bool(row) and CHUNK_VECTORS_FILE.exists(),
        "model_id": row[0] if row else "",
        "dim": row[1] if row else 0,
        "count": row[2] if row else 0,
        "book_count": row[3] if row else 0,
        "dtype": row[4] if row else "",
        "built_at": row[5] if row else "",
        "chunk_chars": row[6] if row else 0,
        "chunk_overlap": row[7] if row else 0,
        "chunks_in_db": chunks,
        "books_in_db": books,
        "vector_file": str(CHUNK_VECTORS_FILE),
        "vector_file_exists": CHUNK_VECTORS_FILE.exists(),
    }


def indexed_book_ids(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT DISTINCT book_id FROM chunks")}


def load_vectors() -> Optional[np.ndarray]:
    """
    The vector file as float32, or None when it is absent.

    `mmap_mode='r'` then `ascontiguousarray` reads the file without holding a
    second float16 copy, and the upcast happens exactly once.
    """
    if not CHUNK_VECTORS_FILE.exists():
        return None
    try:
        raw = np.load(CHUNK_VECTORS_FILE, mmap_mode="r")
        return np.ascontiguousarray(raw, dtype=COMPUTE_DTYPE)
    except Exception as e:
        logger.warning(f"Could not read {CHUNK_VECTORS_FILE}: {e}")
        return None


# ── Building ────────────────────────────────────────────────────────────────

def _candidate_books(conn: sqlite3.Connection, only: Optional[Iterable[str]]) -> list[tuple]:
    """
    Books eligible for indexing: present, with a text layer.

    The 19 books with no text layer are excluded here rather than failing
    later with an empty extraction. §1.10 wants them surfaced as "not indexed"
    in the UI, which is `books.ocr_required` — this is the other half of that
    honesty.
    """
    sql = (
        "SELECT id, file_path, file_type, title FROM books "
        "WHERE status != 'missing' AND has_text = 1 AND file_type IN ('pdf', 'epub')"
    )
    rows = conn.execute(sql).fetchall()
    if only is not None:
        wanted = set(only)
        rows = [r for r in rows if r[0] in wanted]
    return rows


def _chunk_one(book_id: str, file_path: str, file_type: str, force_text: bool) -> list[Chunk]:
    path = Path(file_path)
    if not path.exists():
        return []
    doc = get_full_text(book_id, path, file_type, force=force_text)
    if not doc.text.strip():
        return []
    return chunk_document(doc)


def _existing_vectors_by_key(
    conn: sqlite3.Connection, vectors: Optional[np.ndarray]
) -> dict[tuple[str, int], np.ndarray]:
    """
    Map (book_id, chunk_idx) → its current vector.

    Keyed on the *logical* identity of a chunk rather than its id, because the
    id is about to be reassigned. A row whose id falls outside the vector file
    is skipped: that means a previous build was interrupted between writing the
    rows and writing the file, and carrying a wrong vector forward would be
    worse than re-embedding the book.
    """
    if vectors is None:
        return {}
    out: dict[tuple[str, int], np.ndarray] = {}
    for cid, book_id, chunk_idx in conn.execute(
        "SELECT id, book_id, chunk_idx FROM chunks"
    ):
        if 0 <= cid < len(vectors):
            out[(book_id, chunk_idx)] = vectors[cid]
    return out


def build_index(
    conn: sqlite3.Connection,
    book_ids: Optional[Iterable[str]] = None,
    force: bool = False,
    force_text: bool = False,
    limit: Optional[int] = None,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> BuildResult:
    """
    Build or extend the passage index.

    `book_ids` restricts the build to those books — the vertical slice of
    §1.11 phase 0, and also what an incremental update passes. Books already
    indexed are left alone unless `force` is set, and their vectors are carried
    over rather than recomputed.
    """
    ensure_schema(conn)
    started = time.monotonic()
    result = BuildResult()

    from .embeddings import encode_passages, model_id

    model = model_id()
    meta = conn.execute("SELECT model_id FROM chunk_index_meta WHERE id = 1").fetchone()
    stored_model = meta[0] if meta else ""

    # A model change invalidates every vector in the file. Two models produce
    # vectors of the same shape whose cosine is noise, and the failure does not
    # raise — it just returns confident nonsense, which is why the stamp exists.
    model_changed = bool(stored_model) and stored_model != model
    if model_changed:
        logger.warning(
            f"Chunk index was built with {stored_model!r}, configured for {model!r}. "
            f"Re-embedding every chunk; vectors from two models cannot be mixed."
        )

    candidates = _candidate_books(conn, book_ids)
    already = indexed_book_ids(conn)
    rebuild_all = force or model_changed

    targets = [r for r in candidates if rebuild_all or r[0] not in already]
    if limit is not None:
        targets = targets[:limit]
    result.books_skipped = len(candidates) - len(targets)

    if not targets:
        logger.info("Passage index is already current; nothing to build")
        result.seconds = time.monotonic() - started
        return result

    old_vectors = None if model_changed else load_vectors()
    carried = _existing_vectors_by_key(conn, old_vectors)
    target_ids = {r[0] for r in targets}

    # ── Chunk the targets ───────────────────────────────────────────────────
    fresh: dict[str, list[Chunk]] = {}
    for i, (book_id, file_path, file_type, title) in enumerate(targets, start=1):
        if progress:
            progress(i, len(targets), title or file_path)
        try:
            if force_text:
                clear_cached(book_id)
            chunks = _chunk_one(book_id, file_path, file_type, force_text)
        except Exception as e:
            logger.warning(f"Chunking failed for {title or book_id}: {e}")
            result.books_failed += 1
            result.errors.append(f"{title or book_id}: {e}")
            continue
        if not chunks:
            result.books_failed += 1
            result.errors.append(f"{title or book_id}: no extractable text")
            continue
        fresh[book_id] = chunks
        result.books_indexed += 1

    # ── Carry over everything not rebuilt ───────────────────────────────────
    retained: dict[str, list[tuple[Chunk, Optional[np.ndarray]]]] = {}
    if not model_changed:
        rows = conn.execute(
            "SELECT book_id, chunk_idx, text, char_start, char_end, page_start, page_end, "
            "       spine_index, anchor_text, section "
            "FROM chunks WHERE book_id NOT IN ({}) ORDER BY book_id, chunk_idx".format(
                ",".join("?" * len(target_ids)) or "''"
            ),
            tuple(target_ids),
        ).fetchall()
        for r in rows:
            chunk = Chunk(
                chunk_idx=r[1], text=r[2], char_start=r[3], char_end=r[4],
                page_start=r[5], page_end=r[6], spine_index=r[7],
                anchor_text=r[8] or "", section=r[9] or "",
            )
            vec = carried.get((r[0], r[1]))
            retained.setdefault(r[0], []).append((chunk, vec))

    # ── Embed what has no vector ────────────────────────────────────────────
    pending: list[tuple[str, int, str]] = []
    for book_id, chunks in fresh.items():
        for chunk in chunks:
            pending.append((book_id, chunk.chunk_idx, chunk.text))
    for book_id, pairs in retained.items():
        for chunk, vec in pairs:
            if vec is None:
                pending.append((book_id, chunk.chunk_idx, chunk.text))

    new_vectors: dict[tuple[str, int], np.ndarray] = {}
    if pending:
        logger.info(f"Embedding {len(pending)} chunks with {model}")
        batch = max(16, EMBEDDING_BATCH_SIZE)
        for start in range(0, len(pending), batch * 8):
            window = pending[start:start + batch * 8]
            encoded = encode_passages([t for _, _, t in window], batch_size=batch)
            if encoded is None:
                raise RuntimeError(
                    "Embedding model unavailable; install the 'embed' extra "
                    "(pip install 'books[embed]') before building the passage index"
                )
            for (bid, idx, _), vec in zip(window, np.asarray(encoded)):
                new_vectors[(bid, idx)] = vec.astype(COMPUTE_DTYPE)
            logger.info(f"  {min(start + len(window), len(pending))}/{len(pending)}")

    # ── Assemble one id space and write it ──────────────────────────────────
    ordered: list[tuple[str, Chunk, np.ndarray]] = []
    for book_id in sorted(set(list(fresh) + list(retained))):
        if book_id in fresh:
            for chunk in fresh[book_id]:
                vec = new_vectors.get((book_id, chunk.chunk_idx))
                if vec is not None:
                    ordered.append((book_id, chunk, vec))
        else:
            for chunk, vec in retained[book_id]:
                resolved = vec if vec is not None else new_vectors.get((book_id, chunk.chunk_idx))
                if resolved is not None:
                    ordered.append((book_id, chunk, resolved))
                    result.chunks_reused += 1 if vec is not None else 0

    # A build in which every target failed must not be allowed to wipe an index
    # that was working a moment ago.
    if not ordered and result.books_failed:
        logger.error(
            f"All {result.books_failed} target books failed; leaving the existing index alone"
        )
        result.seconds = time.monotonic() - started
        return result

    result.chunks_written = len(ordered)
    _write_index(conn, ordered, model)

    result.seconds = time.monotonic() - started
    logger.info(
        f"Passage index: {result.chunks_written} chunks over "
        f"{result.books_indexed + len(retained)} books in {result.seconds:.0f}s"
    )
    return result


def _write_index(
    conn: sqlite3.Connection,
    ordered: list[tuple[str, Chunk, np.ndarray]],
    model: str,
) -> None:
    """
    Replace `chunks` and the vector file atomically enough to be safe.

    The vector file is written to a temporary path and moved into place *after*
    the transaction commits, so a crash leaves either the old pair or the new
    pair — never rows whose ids point into a file that does not contain them.
    """
    dim = int(ordered[0][2].shape[0]) if ordered else 0

    # `np.save` appends `.npy` unless the name already ends in it, so the temp
    # name has to keep that suffix last or the rename below looks for a file
    # numpy never wrote.
    tmp = CHUNK_VECTORS_FILE.with_name(CHUNK_VECTORS_FILE.name + ".tmp.npy")
    if ordered:
        matrix = np.vstack([vec for _, _, vec in ordered]).astype(VECTOR_DTYPE)
        CHUNK_VECTORS_FILE.parent.mkdir(parents=True, exist_ok=True)
        np.save(tmp, matrix)

    with conn:
        conn.execute("DELETE FROM chunks")
        conn.executemany(
            "INSERT INTO chunks (id, book_id, chunk_idx, text, char_start, char_end, "
            "                    page_start, page_end, spine_index, anchor_text, section) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    row_id, book_id, chunk.chunk_idx, chunk.text,
                    chunk.char_start, chunk.char_end,
                    chunk.page_start, chunk.page_end, chunk.spine_index,
                    chunk.anchor_text, chunk.section,
                )
                for row_id, (book_id, chunk, _) in enumerate(ordered)
            ],
        )
        conn.execute("DELETE FROM chunk_index_meta")
        conn.execute(
            "INSERT INTO chunk_index_meta "
            "(id, model_id, dim, count, book_count, dtype, built_at, chunk_chars, chunk_overlap) "
            "VALUES (1,?,?,?,?,?,?,?,?)",
            (
                model, dim, len(ordered), len({b for b, _, _ in ordered}),
                str(np.dtype(VECTOR_DTYPE)), datetime.now().isoformat(timespec="seconds"),
                CHUNK_TARGET_CHARS, CHUNK_OVERLAP_CHARS,
            ),
        )

    if ordered:
        tmp.replace(CHUNK_VECTORS_FILE)
    else:
        CHUNK_VECTORS_FILE.unlink(missing_ok=True)


def drop_index(conn: sqlite3.Connection) -> None:
    """Remove the index entirely. The cached text files are left alone."""
    ensure_schema(conn)
    with conn:
        conn.execute("DELETE FROM chunks")
        conn.execute("DELETE FROM chunk_index_meta")
    CHUNK_VECTORS_FILE.unlink(missing_ok=True)
