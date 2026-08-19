"""
Passage chunking for the index (§1.5).

Target 1,500 characters (~375 tokens), 250-character overlap. Sized to sit
comfortably under bge's 512-token limit while still holding a complete
argument, with enough overlap that a thought straddling a boundary stays
retrievable from both sides.

**Split on structure first, length second.** A chunk that ends mid-clause
embeds badly, so boundaries are chosen in this order:

1. a paragraph break, when one falls in the back quarter of the chunk;
2. a sentence boundary otherwise;
3. a word boundary, only when a single "sentence" is itself longer than the
   target — which in practice means the extractor produced a wall of text with
   no punctuation, such as an index or a table.

**Anchoring is positional.** Every chunk carries the character span it occupies
in the book's extracted text, and its page (or spine item) is looked up *from
that offset*. Nothing here searches the document for the chunk's text. Part 3
established why: a PDF text run is a positioning artefact, so the obvious
"find the passage in the page" rule matches the wrong occurrence of a repeated
word — visibly for a highlight, invisibly for a chunk, which still returns
prose and simply cites the wrong page.

Boilerplate is gated out. `is_mostly_boilerplate` already exists for this, and
an index full of copyright pages makes unrelated books look similar to each
other — the exact failure `embeddings._content_text` warns about, which would
otherwise be reintroduced at 400x the row count.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from typing import Optional

from .config import (
    CHUNK_ANCHOR_CHARS,
    CHUNK_MIN_CHARS,
    CHUNK_OVERLAP_CHARS,
    CHUNK_TARGET_CHARS,
)
from .full_text import DocumentText
from .text_utils import is_mostly_boilerplate, prose_score

# End of sentence: terminal punctuation, optional closing quote or bracket,
# then whitespace. The lookbehind excludes the common abbreviations that
# otherwise cut a sentence in half on every "Dr." and "e.g.".
_SENTENCE_END = re.compile(
    r"""(?<!\b[A-Z])          # not a single initial: "J. Smith"
        (?<!\bMr)(?<!\bMrs)(?<!\bMs)(?<!\bDr)(?<!\bSt)(?<!\bProf)
        (?<!\bvol)(?<!\bed)(?<!\bpp)(?<!\bcf)(?<!\bal)(?<!\bibid)
        (?<!\be\.g)(?<!\bi\.e)
        [.!?]["'’”)\]]*
        (?=\s)""",
    re.VERBOSE,
)

# A blank line: paragraph break within a unit, and the separator between units.
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")

# Heading-ish lines, used only to label a chunk with the section it sits in.
# Deliberately conservative — a wrong section label is worse than none, and
# nothing downstream depends on it being present.
_NUMBERED_HEADING = re.compile(
    r"^\s*(chapter|part|section|book|appendix|prologue|epilogue|introduction|conclusion)"
    r"\b[\s:.—-]*(?:[ivxlcdm]+|\d+)?\b.{0,60}$",
    re.IGNORECASE,
)

# How far back a paragraph break may sit and still be preferred over the
# sentence boundary. Below this the chunk would be too short to be worth the
# tidier edge.
_PARAGRAPH_PREFERENCE = 0.75

# A chunk must contain at least this many characters of sentence-like prose
# (`prose_score`, which returns 0 outright for anything with a dot-leader table
# of contents). Measured over four books, this drops 0-12% of candidates and
# what it drops is exactly right: contents pages, copyright pages, endnote
# lists, index tails.
MIN_PROSE_CHARS = 200

# ...but not every book is prose. A command reference or a code cookbook has a
# low prose score on every page, and dropping it out of the index entirely is a
# far worse answer than indexing its code blocks. When the prose filter would
# take more of a book than this, the book is reference material rather than
# boilerplate and every chunk is kept.
MAX_PROSE_DROP_RATIO = 0.6


@dataclass
class Segment:
    """One sentence, with its span and whether a paragraph ends at it."""

    start: int
    end: int
    ends_paragraph: bool = False

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass
class Chunk:
    """One indexable passage, anchored back into the document."""

    chunk_idx: int
    text: str
    char_start: int
    char_end: int
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    spine_index: Optional[int] = None
    anchor_text: str = ""
    section: str = ""


def split_segments(text: str) -> list[Segment]:
    """
    Split `text` into sentence-sized segments carrying their offsets.

    Paragraph breaks always end a segment, so a chunk boundary can prefer one
    without a second pass over the text.
    """
    if not text:
        return []

    breaks = {m.start() for m in _PARAGRAPH_BREAK.finditer(text)}
    break_starts = sorted(breaks)

    cuts: list[int] = []
    for m in _SENTENCE_END.finditer(text):
        cuts.append(m.end())
    for b in break_starts:
        cuts.append(b)
    cuts = sorted(set(c for c in cuts if 0 < c < len(text)))

    segments: list[Segment] = []
    cursor = 0
    for cut in cuts + [len(text)]:
        if cut <= cursor:
            continue
        chunk = text[cursor:cut]
        if not chunk.strip():
            cursor = cut
            continue
        # A segment ends a paragraph when a blank line begins at its edge.
        ends_para = cut in breaks or cut >= len(text)
        segments.append(Segment(cursor, cut, ends_para))
        cursor = cut

    return segments


def _split_long_segment(text: str, seg: Segment, target: int) -> list[Segment]:
    """
    Break a segment longer than `target` at word boundaries.

    Last resort: this only fires when the extractor produced text with no
    sentence punctuation — an index, a bibliography, a table flattened into a
    paragraph. Splitting mid-word would be worse than splitting mid-clause.
    """
    pieces: list[Segment] = []
    start = seg.start
    while start < seg.end:
        end = min(start + target, seg.end)
        if end < seg.end:
            space = text.rfind(" ", start + target // 2, end)
            if space > start:
                end = space + 1
        pieces.append(Segment(start, end, ends_paragraph=(end == seg.end and seg.ends_paragraph)))
        start = end
    return pieces


def _heading_index(text: str) -> tuple[list[int], list[str]]:
    """
    Offsets and titles of heading-like lines, for labelling chunks by section.

    A heading is a short line that does not end in sentence punctuation and
    either names a structural division or is set in title/upper case.
    """
    offsets: list[int] = []
    titles: list[str] = []
    pos = 0
    for line in text.split("\n"):
        stripped = line.strip()
        start = pos
        pos += len(line) + 1
        if not (3 <= len(stripped) <= 80):
            continue
        if stripped[-1] in ".,;:":
            continue
        letters = [c for c in stripped if c.isalpha()]
        if len(letters) < 3:
            continue
        is_structural = bool(_NUMBERED_HEADING.match(stripped))
        is_shouted = sum(1 for c in letters if c.isupper()) >= len(letters) * 0.8
        if not (is_structural or is_shouted):
            continue
        offsets.append(start)
        titles.append(" ".join(stripped.split()))
    return offsets, titles


def _section_at(offsets: list[int], titles: list[str], offset: int) -> str:
    """The most recent heading at or before `offset` — positional, as ever."""
    if not offsets:
        return ""
    i = bisect.bisect_right(offsets, offset) - 1
    return titles[i] if i >= 0 else ""


def make_anchor_text(text: str) -> str:
    """
    The leading characters of a chunk, whitespace collapsed.

    Same role and same length as `annotations.make_anchor_text`: the needle an
    EPUB reader searches for in a re-rendered document, because generating a
    true CFI offline is painful and `spine_index` alone only gets you to the
    right chapter.
    """
    return " ".join((text or "").split())[:CHUNK_ANCHOR_CHARS]


def chunk_document(
    doc: DocumentText,
    target: int = CHUNK_TARGET_CHARS,
    overlap: int = CHUNK_OVERLAP_CHARS,
    min_chars: int = CHUNK_MIN_CHARS,
    skip_boilerplate: bool = True,
) -> list[Chunk]:
    """
    Chunk one extracted document into anchored passages.

    Returns chunks in reading order with `chunk_idx` contiguous from 0. A
    dropped chunk (too short, or boilerplate) does not leave a gap in the
    numbering — `chunk_idx` addresses the *kept* passages, since that is what
    "the next passage in this book" has to mean for the reader.
    """
    text = doc.text
    if not text.strip():
        return []

    raw_segments = split_segments(text)
    segments: list[Segment] = []
    for seg in raw_segments:
        if seg.length > target:
            segments.extend(_split_long_segment(text, seg, target))
        else:
            segments.append(seg)
    if not segments:
        return []

    head_offsets, head_titles = _heading_index(text)

    candidates: list[Chunk] = []
    i = 0
    while i < len(segments):
        start_i = i
        end_i = i
        length = 0
        last_para_i = -1
        while end_i < len(segments) and length + segments[end_i].length <= target:
            length += segments[end_i].length
            if segments[end_i].ends_paragraph:
                last_para_i = end_i
            end_i += 1
        if end_i == start_i:
            # One segment alone exceeds the target even after word-splitting.
            end_i = start_i + 1

        # Structure over length: back off to a paragraph edge when one sits in
        # the back quarter of what we accumulated.
        if last_para_i >= start_i and last_para_i < end_i - 1:
            kept = segments[last_para_i].end - segments[start_i].start
            if kept >= target * _PARAGRAPH_PREFERENCE:
                end_i = last_para_i + 1

        char_start = segments[start_i].start
        char_end = segments[end_i - 1].end
        body = text[char_start:char_end].strip()

        if len(body) >= min_chars and not (skip_boilerplate and is_mostly_boilerplate(body)):
            # Offsets, not a text search: `unit_of` bisects the offset map.
            start_unit = doc.unit_of(char_start)
            end_unit = doc.unit_of(max(char_start, char_end - 1))
            candidates.append(
                Chunk(
                    chunk_idx=0,   # assigned after the prose filter, below
                    text=body,
                    char_start=char_start,
                    char_end=char_end,
                    page_start=start_unit + 1 if doc.kind == "pdf" else None,
                    page_end=end_unit + 1 if doc.kind == "pdf" else None,
                    spine_index=start_unit if doc.kind == "epub" else None,
                    anchor_text=make_anchor_text(body),
                    section=_section_at(head_offsets, head_titles, char_start),
                )
            )

        if end_i >= len(segments):
            break

        # Step back over trailing segments to build the overlap, but never past
        # the segment after this chunk's own start — without that guard a chunk
        # whose last segment is longer than the overlap would restart in the
        # same place forever.
        next_i = end_i
        back = 0
        while next_i - 1 > start_i and back + segments[next_i - 1].length <= overlap:
            next_i -= 1
            back += segments[next_i].length
        i = max(next_i, start_i + 1)

    return _apply_prose_filter(candidates, skip_boilerplate)


def _apply_prose_filter(candidates: list[Chunk], enabled: bool) -> list[Chunk]:
    """
    Drop chunks with too little sentence-like prose, then number what remains.

    Numbering happens here rather than during packing so `chunk_idx` is
    contiguous over the *kept* passages — "the next passage in this book" has
    to mean the next one a reader can actually be shown.
    """
    if not candidates:
        return []

    kept = candidates
    if enabled:
        prose = [c for c in candidates if prose_score(c.text) >= MIN_PROSE_CHARS]
        dropped = len(candidates) - len(prose)
        if prose and dropped <= len(candidates) * MAX_PROSE_DROP_RATIO:
            kept = prose

    for idx, chunk in enumerate(kept):
        chunk.chunk_idx = idx
    return kept
