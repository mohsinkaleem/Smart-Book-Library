"""
Full-document text extraction for the passage index.

Distinct from `pdf_extractor` / `epub_extractor`, which read the *front* of a
book for metadata and stop at `MAX_PAGES_TO_EXTRACT`. That cap is right for
them and fatal here: the whole point of Part 1 is that a reader who selects a
paragraph on page 340 is currently matched against 618 introductions.

Two things this module owns:

* **The text.** Written to ``data/text/{book_id}.txt`` rather than into a
  `books` column — 340 MB of prose in a row that every list query reads would
  make the catalog unusable. It is also the *only* copy: a `chunks` row stores
  the character span it occupies here and `read_span` reads it back, rather
  than keeping a second copy of every passage in the database. That second
  copy was 329 MB of a 670 MB catalog, and the overlap between chunks meant
  parts of it were stored twice over.
* **The offset map.** A parallel table saying which page (PDF) or spine item
  (EPUB) each character offset belongs to, cached in
  ``data/text/{book_id}.json``.

The offset map is the whole reason this is not just `"".join(pages)`. Anchoring
must be **positional**: a chunk's page is looked up from where it *starts in
the text*, never by searching the page for the chunk's opening words. Part 3
learned that the expensive way — a highlight anchored by containment lit up
every other occurrence of the same word on the page. A chunk anchored the same
way would mislocate for the same reason and far less visibly, because it still
returns text, just from the wrong place.

PyMuPDF does the PDF reading. pypdf, which the metadata pipeline uses, measures
11.6 ms/page here; over 186,969 pages that is ~36 min single-threaded, and it
is the bottleneck for the whole build. PyMuPDF is 10-20x faster on the same
pages. Note its AGPL licence.
"""
from __future__ import annotations

import bisect
import json
import logging
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import FULL_TEXT_MAX_PAGES, TEXT_DIR
from .text_utils import clean_page

logger = logging.getLogger(__name__)

# The separator between pages / spine items in the joined text. Two newlines,
# so the chunker's paragraph splitter treats a page boundary as a paragraph
# boundary — which it is, far more often than not.
UNIT_SEPARATOR = "\n\n"


@dataclass
class DocumentText:
    """
    One book's full text plus the map from character offset back to location.

    `unit_offsets[i]` is the offset at which unit *i* begins. For a PDF a unit
    is a page and `page_of` returns a 1-based page number, matching what
    `PdfReader.goToPage` takes. For an EPUB a unit is a spine item and
    `unit_hrefs[i]` is its href, which is what `rendition.display` takes.
    """

    text: str = ""
    kind: str = "pdf"                       # "pdf" | "epub"
    unit_offsets: list[int] = field(default_factory=list)
    unit_hrefs: list[str] = field(default_factory=list)

    @property
    def unit_count(self) -> int:
        return len(self.unit_offsets)

    def unit_of(self, offset: int) -> int:
        """
        The 0-based unit containing `offset`.

        `bisect_right - 1` is the positional lookup the module docstring is
        about: it answers "which page is this character on", not "which page
        contains text that looks like this".
        """
        if not self.unit_offsets:
            return 0
        return max(0, bisect.bisect_right(self.unit_offsets, offset) - 1)

    def page_of(self, offset: int) -> int:
        """1-based page number for a character offset (PDF)."""
        return self.unit_of(offset) + 1

    def href_of(self, offset: int) -> str:
        idx = self.unit_of(offset)
        return self.unit_hrefs[idx] if idx < len(self.unit_hrefs) else ""

    def to_meta(self) -> dict:
        return {
            "kind": self.kind,
            "unit_offsets": self.unit_offsets,
            "unit_hrefs": self.unit_hrefs,
            "chars": len(self.text),
        }


def _assemble(units: list[str], kind: str, hrefs: Optional[list[str]] = None) -> DocumentText:
    """
    Join cleaned units and record where each one starts.

    Empty units still take a slot. A blank page must not shift every later
    page number by one — which is exactly what filtering them out would do.
    """
    parts: list[str] = []
    offsets: list[int] = []
    cursor = 0
    for unit in units:
        offsets.append(cursor)
        parts.append(unit)
        cursor += len(unit) + len(UNIT_SEPARATOR)
    text = UNIT_SEPARATOR.join(parts)
    return DocumentText(
        text=text,
        kind=kind,
        unit_offsets=offsets,
        unit_hrefs=list(hrefs or []),
    )


def extract_pdf_full_text(file_path: Path) -> DocumentText:
    """Every page of a PDF, via PyMuPDF, with a page offset map."""
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - supplied by the `passages` extra
        logger.error(
            "pymupdf not installed — the passage index cannot read PDFs. "
            "Run: pip install 'books[passages]'"
        )
        return DocumentText(kind="pdf")

    pages: list[str] = []
    try:
        with pymupdf.open(str(file_path)) as doc:
            limit = FULL_TEXT_MAX_PAGES or doc.page_count
            for i in range(min(doc.page_count, limit)):
                try:
                    pages.append(clean_page(doc[i].get_text()))
                except Exception as e:
                    # One unreadable page must not cost the other 600. It keeps
                    # its slot so every later page number stays correct.
                    logger.debug(f"Page {i} of {file_path.name} failed: {e}")
                    pages.append("")
    except Exception as e:
        logger.warning(f"PyMuPDF could not open {file_path.name}: {e}")
        return DocumentText(kind="pdf")

    return _assemble(pages, "pdf")


def extract_epub_full_text(file_path: Path) -> DocumentText:
    """
    Every spine item of an EPUB, in spine order, with an href map.

    Spine *order* is the point. `get_items_of_type` returns manifest order,
    which is arbitrary — chunk 0 would not be the beginning of the book and
    `spine_index` would not address anything the reader can navigate to.
    """
    try:
        from ebooklib import epub
    except ImportError:  # pragma: no cover
        logger.error("ebooklib not installed. Run: pip install ebooklib")
        return DocumentText(kind="epub")

    try:
        book = epub.read_epub(str(file_path), options={"ignore_ncx": True})
    except Exception as e:
        logger.warning(f"ebooklib could not open {file_path.name}: {e}")
        return DocumentText(kind="epub")

    from .epub_extractor import _extract_text_from_html, spine_documents

    items: list[tuple[str, str]] = []
    for item in spine_documents(book):
        try:
            text = clean_page(_extract_text_from_html(item.get_content() or b""))
        except Exception as e:
            logger.debug(f"Spine item {item.get_id()} of {file_path.name} failed: {e}")
            text = ""
        items.append((text, item.get_name() or ""))

    return _assemble([t for t, _ in items], "epub", [h for _, h in items])


def extract_full_text(file_path: Path, file_type: str) -> DocumentText:
    """Dispatch on file type. Unknown types yield an empty document."""
    if file_type == "pdf":
        return extract_pdf_full_text(file_path)
    if file_type == "epub":
        return extract_epub_full_text(file_path)
    return DocumentText(kind=file_type or "")


# ── On-disk cache ───────────────────────────────────────────────────────────

def text_path(book_id: str) -> Path:
    return TEXT_DIR / f"{book_id}.txt"


def meta_path(book_id: str) -> Path:
    return TEXT_DIR / f"{book_id}.json"


def load_cached(book_id: str) -> Optional[DocumentText]:
    """The cached extraction for a book, or None when it is absent or stale."""
    tp, mp = text_path(book_id), meta_path(book_id)
    if not tp.exists() or not mp.exists():
        return None
    try:
        meta = json.loads(mp.read_text(encoding="utf-8"))
        text = tp.read_text(encoding="utf-8")
    except (OSError, ValueError) as e:
        logger.debug(f"Cached text for {book_id} unreadable: {e}")
        return None
    # A truncated write leaves a text file that no longer matches its offset
    # map, and every page number derived from it would be wrong.
    if meta.get("chars") != len(text):
        logger.info(f"Cached text for {book_id} is stale; re-extracting")
        return None
    return DocumentText(
        text=text,
        kind=meta.get("kind", "pdf"),
        unit_offsets=meta.get("unit_offsets", []),
        unit_hrefs=meta.get("unit_hrefs", []),
    )


def save_cached(book_id: str, doc: DocumentText) -> None:
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    text_path(book_id).write_text(doc.text, encoding="utf-8")
    meta_path(book_id).write_text(json.dumps(doc.to_meta()), encoding="utf-8")


def clear_cached(book_id: str) -> None:
    for path in (text_path(book_id), meta_path(book_id)):
        path.unlink(missing_ok=True)


# ── Reading passages back out ───────────────────────────────────────────────
#
# A passage search touches a handful of books and then asks for ten spans out
# of them, so whole-book texts are worth holding briefly. Eight books is a few
# MB and covers a result page, its neighbours and a follow-up query.
TEXT_CACHE_BOOKS = 8

_text_cache: "OrderedDict[str, str]" = OrderedDict()
_text_cache_lock = threading.Lock()


def clear_text_cache() -> None:
    with _text_cache_lock:
        _text_cache.clear()


def book_text(
    book_id: str, file_path: Optional[Path] = None, file_type: str = ""
) -> str:
    """
    A book's extracted text, memoised across calls.

    `data/text` is a cache, not a store of record: when its file is gone and
    the book itself is still on disk, the text is extracted again rather than
    leaving every passage in that book unreadable.
    """
    with _text_cache_lock:
        if book_id in _text_cache:
            _text_cache.move_to_end(book_id)
            return _text_cache[book_id]

    doc = load_cached(book_id)
    if doc is None and file_path is not None and Path(file_path).exists():
        logger.info(f"Cached text for {book_id} is gone; re-extracting")
        doc = get_full_text(book_id, Path(file_path), file_type)
    text = doc.text if doc else ""

    with _text_cache_lock:
        _text_cache[book_id] = text
        _text_cache.move_to_end(book_id)
        while len(_text_cache) > TEXT_CACHE_BOOKS:
            _text_cache.popitem(last=False)
    return text


def read_span(
    book_id: str,
    char_start: Optional[int],
    char_end: Optional[int],
    file_path: Optional[Path] = None,
    file_type: str = "",
) -> str:
    """
    One chunk's text, read back from the book's extracted text by offset.

    `.strip()` because the chunker stores the span it cut and reports the
    stripped body; the two differ by the whitespace at a boundary.
    """
    if char_start is None or char_end is None:
        return ""
    text = book_text(book_id, file_path, file_type)
    if not text:
        return ""
    return text[char_start:char_end].strip()


def get_full_text(
    book_id: str, file_path: Path, file_type: str, force: bool = False
) -> DocumentText:
    """
    Cached full-text extraction.

    Extraction is the expensive half of the build (~12 min over this library at
    four workers, even with PyMuPDF), so re-chunking with different parameters
    should not pay for it twice.
    """
    if not force:
        cached = load_cached(book_id)
        if cached is not None:
            return cached
    doc = extract_full_text(Path(file_path), file_type)
    if doc.text:
        save_cached(book_id, doc)
    return doc
