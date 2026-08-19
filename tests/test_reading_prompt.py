"""
The prompt builder, and the bug it existed to hide.

`_build_prompt` has always accepted a `context` argument that only the
"compare" template interpolates — and the route called it without one, so
every Compare request sent a prompt ending in a bare `Related:` followed by
nothing at all.
"""
import pytest

from server.llm_service import PROMPT_MAX_CHARS, _build_prompt, _clip
from server.routes.reading import RETRIEVAL_ACTIONS, _book_meta, _context_block


# ── the live bug ─────────────────────────────────────────────────────────────

def test_compare_carries_the_retrieved_context():
    prompt = _build_prompt("the passage", "compare", "Some Book", context="[1] Other Book\nprose")
    assert "[1] Other Book" in prompt
    assert "prose" in prompt


def test_compare_without_context_has_no_dangling_heading():
    """The regression: a heading with nothing under it, on every request."""
    prompt = _build_prompt("the passage", "compare", "Some Book")
    assert not prompt.rstrip().endswith(":")
    assert "Related material from the library" not in prompt
    assert "the passage" in prompt


def test_related_grounds_itself_only_when_something_was_retrieved():
    grounded = _build_prompt("p", "related", context="[1] Book\ntext")
    assert "citing sources by title" in grounded

    ungrounded = _build_prompt("p", "related")
    assert "citing sources by title" not in ungrounded
    assert "Related material" not in ungrounded


# ── the surrounding-text and metadata frame ──────────────────────────────────

def test_book_metadata_reaches_the_prompt():
    prompt = _build_prompt("p", "explain", "Title", book_meta="Ada Lovelace · 1998 · Philosophy")
    assert "Ada Lovelace · 1998 · Philosophy" in prompt


def test_surrounding_text_is_marked_as_background():
    prompt = _build_prompt("p", "explain", surrounding="the rest of the page")
    assert "the rest of the page" in prompt
    assert "background only" in prompt


def test_empty_optional_blocks_are_omitted_entirely():
    prompt = _build_prompt("p", "explain")
    assert "About the book" not in prompt
    assert "Surrounding text" not in prompt


@pytest.mark.parametrize("action", ["explain", "summarize", "compare", "critique", "related"])
def test_every_action_includes_the_passage(action):
    assert "SELECTED-PASSAGE" in _build_prompt("SELECTED-PASSAGE", action, "Book")


def test_an_unknown_action_still_produces_a_prompt():
    assert "p" in _build_prompt("p", "nonsense")


# ── budget ───────────────────────────────────────────────────────────────────

def test_the_prompt_is_capped():
    """A 4B model truncates from the front, dropping the instruction and
    keeping the retrieved noise — so cap before sending, not after."""
    prompt = _build_prompt("p", "compare", context="x " * 20_000)
    assert len(prompt) <= PROMPT_MAX_CHARS + 8


def test_clip_marks_what_it_removed():
    assert _clip("one two three four", 9).endswith("[…]")
    assert _clip("short", 100) == "short"


def test_surrounding_text_cannot_crowd_out_the_passage():
    prompt = _build_prompt("PASSAGE-MARKER", "explain", surrounding="w " * 5000)
    assert "PASSAGE-MARKER" in prompt


# ── the context block the route assembles ────────────────────────────────────

def test_context_block_is_numbered_and_attributed():
    block = _context_block([
        {"title": "Book A", "author": "Ada", "excerpt": "first"},
        {"title": "Book B", "author": "", "excerpt": "second"},
    ])
    assert "[1] Book A — Ada" in block
    assert "[2] Book B" in block
    assert "— " not in block.split("\n")[2]      # no dangling dash without an author


def test_context_block_skips_matches_with_no_excerpt():
    block = _context_block([{"title": "Empty", "author": "", "excerpt": "   "}])
    assert block == ""


def test_retrieval_is_scoped_to_the_actions_that_use_it():
    """Retrieval for "explain" would cost a matmul and dilute the prompt."""
    assert RETRIEVAL_ACTIONS == {"compare", "related"}


def test_book_meta_is_assembled_from_json_columns():
    meta = _book_meta({
        "author_primary": "Ada Lovelace",
        "publication_year": 1998,
        "categories": '["Philosophy"]',
        "themes": '["ethics"]',
    })
    assert meta == "Ada Lovelace · 1998 · Philosophy · ethics"


def test_book_meta_of_a_bare_record_is_empty():
    assert _book_meta({}) == ""


# ── the route ────────────────────────────────────────────────────────────────

def test_compare_endpoint_returns_matches_shape(client):
    """No embeddings in the fixture DB, so this proves the contract, not ranking."""
    res = client.post("/api/reading/compare", json={"text": "some prose", "book_id": "book-one"})
    assert res.status_code == 200
    assert "matches" in res.json()
