"""
Annotations: storage, the HTTP surface, and the two things that are easy to
get wrong — validation of `kind`, and surviving a rebuild that changes book ids.
"""
import sqlite3

import pytest

from catalog.annotations import (
    create_annotation,
    delete_annotation,
    list_annotations,
    make_anchor_text,
    relink_orphans,
    update_annotation,
)


# ── the store ────────────────────────────────────────────────────────────────

@pytest.fixture
def conn(catalog_db):
    connection = sqlite3.connect(str(catalog_db))
    yield connection
    connection.close()


def test_create_returns_the_stored_row(conn):
    ann = create_annotation(conn, "book-one", kind="highlight", text="a passage", page=12)
    assert ann["book_id"] == "book-one"
    assert ann["kind"] == "highlight"
    assert ann["page"] == 12
    assert ann["created_at"] and ann["updated_at"]


def test_file_path_is_recorded_so_a_rebuild_can_relink(conn):
    ann = create_annotation(conn, "book-one", text="x")
    assert ann["file_path"] == "pdfs/one.pdf"


def test_anchor_text_defaults_to_the_head_of_the_selection(conn):
    ann = create_annotation(conn, "book-one", text="  The argument   proceeds by counterexample. ")
    assert ann["anchor_text"] == "The argument proceeds by counterexample."


def test_anchor_text_is_capped(conn):
    ann = create_annotation(conn, "book-one", text="word " * 200)
    assert len(ann["anchor_text"]) <= 60


def test_unknown_kind_is_rejected(conn):
    assert create_annotation(conn, "book-one", kind="scribble") is None


def test_unknown_book_is_rejected(conn):
    assert create_annotation(conn, "no-such-book") is None


def test_list_is_scoped_by_book_and_kind(conn):
    create_annotation(conn, "book-one", kind="highlight", text="h", page=2)
    create_annotation(conn, "book-one", kind="bookmark", text="b", page=3)
    create_annotation(conn, "book-two", kind="highlight", text="other")

    assert len(list_annotations(conn, book_id="book-one")) == 2
    assert len(list_annotations(conn, book_id="book-one", kind="bookmark")) == 1
    assert len(list_annotations(conn)) == 3


def test_list_is_ordered_by_position_not_insertion(conn):
    create_annotation(conn, "book-one", text="late", page=90)
    create_annotation(conn, "book-one", text="early", page=3)
    pages = [a["page"] for a in list_annotations(conn, book_id="book-one")]
    assert pages == [3, 90]


def test_epub_annotations_sort_after_paged_ones_by_cfi(conn):
    """`page` is NULL for EPUBs and `cfi` empty for PDFs; one ORDER BY covers both."""
    create_annotation(conn, "book-two", text="ch3", cfi="epubcfi(/6/8)")
    create_annotation(conn, "book-two", text="ch1", cfi="epubcfi(/6/2)")
    cfis = [a["cfi"] for a in list_annotations(conn, book_id="book-two")]
    assert cfis == ["epubcfi(/6/2)", "epubcfi(/6/8)"]


def test_update_patches_only_editable_fields(conn):
    ann = create_annotation(conn, "book-one", text="original", page=5)
    updated = update_annotation(
        conn, ann["id"], {"note": "my thought", "book_id": "book-two", "id": "hijacked"}
    )
    assert updated["note"] == "my thought"
    assert updated["book_id"] == "book-one"     # not reassignable
    assert updated["id"] == ann["id"]


def test_update_rejects_an_unknown_kind(conn):
    ann = create_annotation(conn, "book-one", text="x")
    assert update_annotation(conn, ann["id"], {"kind": "scribble"}) is None


def test_update_of_a_missing_annotation_is_none(conn):
    assert update_annotation(conn, "nope", {"note": "x"}) is None


def test_delete(conn):
    ann = create_annotation(conn, "book-one", text="x")
    assert delete_annotation(conn, ann["id"]) is True
    assert delete_annotation(conn, ann["id"]) is False
    assert list_annotations(conn, book_id="book-one") == []


def test_relink_follows_the_file_path_when_a_rebuild_changes_the_id(conn):
    """
    Book ids are content hashes, so re-encoding a PDF orphans its highlights.
    The path is what survived.
    """
    ann = create_annotation(conn, "book-one", text="keep me", page=7)
    conn.execute("UPDATE books SET id = 'book-one-rebuilt' WHERE id = 'book-one'")
    conn.commit()

    assert relink_orphans(conn) == 1
    survivors = list_annotations(conn, book_id="book-one-rebuilt")
    assert [a["id"] for a in survivors] == [ann["id"]]
    assert survivors[0]["text"] == "keep me"


def test_relink_leaves_live_annotations_alone(conn):
    create_annotation(conn, "book-one", text="x")
    assert relink_orphans(conn) == 0


def test_helpers_do_not_change_the_connection_row_factory(conn):
    """`catalog.store` reads tuples by index off this same connection."""
    create_annotation(conn, "book-one", text="x")
    list_annotations(conn, book_id="book-one")
    row = conn.execute("SELECT id FROM books LIMIT 1").fetchone()
    assert isinstance(row, tuple)


# ── the HTTP surface ─────────────────────────────────────────────────────────

def test_post_then_get(client):
    created = client.post("/api/annotations", json={
        "book_id": "book-one", "kind": "highlight",
        "text": "a passage", "page": 12, "color": "green",
    })
    assert created.status_code == 201
    ann = created.json()
    assert ann["color"] == "green"

    listed = client.get("/api/annotations?book_id=book-one")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def test_post_for_an_unknown_book_is_404(client):
    res = client.post("/api/annotations", json={"book_id": "nope", "text": "x"})
    assert res.status_code == 404


def test_post_with_an_unknown_kind_is_422(client):
    res = client.post("/api/annotations", json={"book_id": "book-one", "kind": "scribble"})
    assert res.status_code == 422


def test_list_with_an_unknown_kind_is_422(client):
    assert client.get("/api/annotations?kind=scribble").status_code == 422


def test_patch_and_delete(client):
    ann = client.post("/api/annotations", json={
        "book_id": "book-one", "text": "x", "page": 3,
    }).json()

    patched = client.patch(f"/api/annotations/{ann['id']}", json={"note": "later thought"})
    assert patched.status_code == 200
    assert patched.json()["note"] == "later thought"

    assert client.delete(f"/api/annotations/{ann['id']}").status_code == 204
    assert client.delete(f"/api/annotations/{ann['id']}").status_code == 404


def test_patch_of_a_missing_annotation_is_404(client):
    assert client.patch("/api/annotations/nope", json={"note": "x"}).status_code == 404


def test_page_zero_is_rejected(client):
    """Pages are 1-indexed everywhere in the readers."""
    res = client.post("/api/annotations", json={"book_id": "book-one", "page": 0})
    assert res.status_code == 422


def test_oversized_text_is_truncated_not_rejected(client):
    ann = client.post("/api/annotations", json={
        "book_id": "book-one", "text": "z" * 20_000,
    }).json()
    assert len(ann["text"]) == 8000
