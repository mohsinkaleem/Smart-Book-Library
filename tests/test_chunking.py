"""
Chunker invariants (§1.5).

The anchoring tests are the point of this file. Part 3 established that
containment-based anchoring picks the wrong occurrence of a repeated word, and
that the failure is invisible for chunks because a mislocated chunk still
returns prose — it just cites the wrong page. `test_repeated_phrase_*` pins the
positional behaviour by name so that stays true.
"""
import pytest

from catalog.chunking import (
    Chunk,
    MIN_PROSE_CHARS,
    chunk_document,
    make_anchor_text,
    split_segments,
)
from catalog.full_text import UNIT_SEPARATOR, DocumentText

SENTENCE = (
    "The historian is not a judge but a witness, and the distinction matters "
    "more than the profession usually admits when it recounts a settlement. "
)


def prose(n_sentences: int) -> str:
    """`n` sentences of sentence-like prose, long enough to clear the floors."""
    return (SENTENCE * n_sentences).strip()


def make_doc(pages: list[str], kind: str = "pdf", hrefs=None) -> DocumentText:
    """Assemble a document the way `full_text._assemble` does."""
    offsets, cursor = [], 0
    for page in pages:
        offsets.append(cursor)
        cursor += len(page) + len(UNIT_SEPARATOR)
    return DocumentText(
        text=UNIT_SEPARATOR.join(pages),
        kind=kind,
        unit_offsets=offsets,
        unit_hrefs=list(hrefs or []),
    )


# ── Segmentation ────────────────────────────────────────────────────────────

def test_splits_on_sentence_boundaries():
    segments = split_segments("One thing happened. Then another. And a third.")
    assert len(segments) == 3


def test_abbreviations_do_not_end_a_sentence():
    segments = split_segments("Dr. Khalidi wrote the reply. Prof. Stove disagreed.")
    assert len(segments) == 2


def test_paragraph_break_ends_a_segment():
    segments = split_segments("A clause without a stop\n\nand the next paragraph.")
    assert len(segments) == 2
    assert segments[0].ends_paragraph


def test_segments_tile_the_text_without_gaps():
    text = "First sentence here. Second one follows.\n\nThird begins a block."
    segments = split_segments(text)
    assert segments[0].start == 0
    assert segments[-1].end == len(text)
    for a, b in zip(segments, segments[1:]):
        assert a.end == b.start


# ── Sizing and overlap ──────────────────────────────────────────────────────

def test_chunks_respect_the_target_size():
    chunks = chunk_document(make_doc([prose(60)]), target=1500)
    assert chunks
    assert all(len(c.text) <= 1500 for c in chunks)


def test_chunks_overlap_so_a_straddling_thought_is_retrievable_twice():
    chunks = chunk_document(make_doc([prose(60)]), target=1500, overlap=250)
    assert len(chunks) > 2
    overlapping = sum(1 for a, b in zip(chunks, chunks[1:]) if b.char_start < a.char_end)
    assert overlapping >= len(chunks) - 2


def test_chunk_positions_always_advance():
    """
    The overlap step-back must never return to where the chunk began.

    Without the `start_i + 1` guard, a chunk whose final segment is longer than
    the overlap budget restarts at its own start and the loop never ends.
    """
    one_long_sentence = "word " * 400 + "."
    chunks = chunk_document(make_doc([one_long_sentence * 3]), target=1500, overlap=250)
    assert chunks
    for a, b in zip(chunks, chunks[1:]):
        assert b.char_start > a.char_start


def test_chunk_indices_are_contiguous_over_kept_passages():
    chunks = chunk_document(make_doc([prose(80)]))
    assert [c.chunk_idx for c in chunks] == list(range(len(chunks)))


def test_empty_document_yields_nothing():
    assert chunk_document(make_doc([])) == []
    assert chunk_document(make_doc(["   ", ""])) == []


# ── Anchoring — positional, never by containment ────────────────────────────

def test_pdf_chunks_carry_one_based_page_numbers():
    chunks = chunk_document(make_doc([prose(12), prose(12), prose(12)]))
    assert chunks[0].page_start == 1
    assert max(c.page_end for c in chunks) == 3
    assert all(c.spine_index is None for c in chunks)


def test_epub_chunks_carry_spine_index_and_anchor_text():
    chunks = chunk_document(
        make_doc([prose(12), prose(12)], kind="epub", hrefs=["a.html", "b.html"])
    )
    assert all(c.page_start is None for c in chunks)
    assert {c.spine_index for c in chunks} == {0, 1}
    assert all(c.anchor_text and len(c.anchor_text) <= 60 for c in chunks)


def test_repeated_phrase_is_anchored_by_position_not_containment():
    """
    The Part 3 lesson, applied to chunks.

    `namedtuple` appears on page 1 and page 3. A chunk drawn from page 3 must
    report page 3 — matching on "which page contains this text" would return
    the first hit, and nothing downstream would look wrong.
    """
    needle = "The namedtuple factory returns a subclass with named fields."
    pages = [needle + " " + prose(10), prose(10), needle + " " + prose(10)]
    doc = make_doc(pages)
    chunks = chunk_document(doc)

    third = doc.text.rfind(needle)
    assert third > doc.unit_offsets[2] - len(needle)

    covering = [c for c in chunks if c.char_start <= third < c.char_end]
    assert covering, "expected a chunk covering the third occurrence"
    for chunk in covering:
        assert chunk.page_end == 3, "the third occurrence is on page 3, not page 1"


def test_anchor_offsets_agree_with_the_document_offset_map():
    doc = make_doc([prose(10), prose(10), prose(10), prose(10)])
    for chunk in chunk_document(doc):
        assert chunk.page_start == doc.page_of(chunk.char_start)
        assert doc.text[chunk.char_start:chunk.char_end].strip() == chunk.text


# ── Gating ──────────────────────────────────────────────────────────────────

def test_copyright_boilerplate_is_kept_out_of_the_index():
    boilerplate = (
        "Copyright 2019 by the publisher. All rights reserved. ISBN 978-0-00-000000-0. "
        "No part of this book may be reproduced without permission of the publisher. "
        "Printed in the United States of America. First published 2019. "
        "Library of Congress cataloguing in publication data available. "
    ) * 3
    chunks = chunk_document(make_doc([boilerplate, prose(20)]))
    assert chunks
    assert all("All rights reserved" not in c.text for c in chunks)


def test_table_of_contents_is_dropped_by_the_prose_floor():
    toc = "\n".join(f"Chapter {i} .......... {i * 12}" for i in range(1, 40))
    chunks = chunk_document(make_doc([toc, prose(20)]))
    assert chunks
    assert all(".........." not in c.text for c in chunks)


def test_reference_material_survives_the_prose_floor():
    """
    A book of commands has a low prose score on every page. Dropping it out of
    the index entirely is worse than indexing its code blocks, so the filter
    stands down when it would take most of a book.
    """
    commands = "\n".join(f"git reset --hard HEAD~{i}" for i in range(300))
    chunks = chunk_document(make_doc([commands]))

    assert all(chunk_prose_is_low(c) for c in chunks), "premise: this text has no prose"
    assert chunks, "a reference book must not vanish from the index"


def chunk_prose_is_low(chunk: Chunk) -> bool:
    from catalog.text_utils import prose_score
    return prose_score(chunk.text) < MIN_PROSE_CHARS


def test_short_tail_is_dropped():
    chunks = chunk_document(make_doc([prose(20), "Fin."]), min_chars=200)
    assert all(len(c.text) >= 200 for c in chunks)


# ── Sections and anchors ────────────────────────────────────────────────────

def test_chunks_are_labelled_with_the_preceding_heading():
    doc = make_doc(["Chapter 4: The Settlement\n\n" + prose(20)])
    chunks = chunk_document(doc)
    assert chunks
    assert chunks[0].section.startswith("Chapter 4")


def test_anchor_text_collapses_whitespace():
    assert make_anchor_text("  the   quick\nbrown  fox  ") == "the quick brown fox"


@pytest.mark.parametrize("kind", ["pdf", "epub"])
def test_anchor_text_is_the_head_of_the_chunk(kind):
    chunks = chunk_document(make_doc([prose(30)], kind=kind, hrefs=["a.html"]))
    for chunk in chunks:
        assert chunk.text.startswith(chunk.anchor_text[:20])
