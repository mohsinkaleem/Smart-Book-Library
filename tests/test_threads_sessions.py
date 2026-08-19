"""
LLM threads (§4.2), reading sessions, export and duplicate resolution (Part 5).

The thread tests never reach Ollama: what is worth pinning here is the storage
and the frame, not the model's prose.
"""
from datetime import datetime, timedelta

import pytest


# ── Threads (§4.2) ──────────────────────────────────────────────────────────

def test_thread_pins_the_passage_and_survives_the_request(client):
    created = client.post("/api/threads", json={
        "book_id": "book-one",
        "passage": "The argument proceeds by counterexample.",
        "surrounding": "Chapter two opens with a claim.",
        "page": 42,
        "retrieve": False,
    }).json()

    assert created["passage"].startswith("The argument")
    assert created["page"] == 42
    # The title defaults to the passage so a list of threads is readable
    # before anyone renames one.
    assert created["title"]

    fetched = client.get(f"/api/threads/{created['id']}").json()
    assert fetched["passage"] == created["passage"]
    assert fetched["messages"] == []


def test_thread_creation_requires_a_real_book(client):
    r = client.post("/api/threads", json={"book_id": "nope", "passage": "x"})
    assert r.status_code == 404


def test_messages_accumulate_in_order(client):
    thread = client.post("/api/threads", json={
        "book_id": "book-one", "passage": "A claim.", "retrieve": False,
    }).json()
    db = client.app.state.db

    db.add_message(thread["id"], "user", "What does this mean?")
    db.add_message(thread["id"], "assistant", "It means this.")
    db.add_message(thread["id"], "user", "Why?")

    messages = client.get(f"/api/threads/{thread['id']}").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[-1]["content"] == "Why?"


def test_only_the_title_is_editable(client):
    """
    The passage and context are the thread's identity. Changing them would
    leave every stored answer grounded in material no longer shown, which
    reads as the model having invented it.
    """
    thread = client.post("/api/threads", json={
        "book_id": "book-one", "passage": "Original passage.", "retrieve": False,
    }).json()

    updated = client.patch(f"/api/threads/{thread['id']}", json={
        "title": "Renamed", "passage": "Something else entirely",
    }).json()

    assert updated["title"] == "Renamed"
    assert updated["passage"] == "Original passage."


def test_deleting_a_thread_takes_its_messages(client):
    thread = client.post("/api/threads", json={
        "book_id": "book-one", "passage": "A claim.", "retrieve": False,
    }).json()
    client.app.state.db.add_message(thread["id"], "user", "hello")

    assert client.delete(f"/api/threads/{thread['id']}").status_code == 204
    assert client.get(f"/api/threads/{thread['id']}").status_code == 404

    orphans = client.app.state.db.query(
        "SELECT COUNT(*) FROM llm_messages WHERE thread_id = ?", (thread["id"],)
    )[0][0]
    assert orphans == 0


def test_threads_list_filters_by_book(client):
    client.post("/api/threads", json={"book_id": "book-one", "passage": "one", "retrieve": False})
    client.post("/api/threads", json={"book_id": "book-two", "passage": "two", "retrieve": False})

    scoped = client.get("/api/threads?book_id=book-one").json()
    assert scoped["total"] == 1
    assert scoped["threads"][0]["book_id"] == "book-one"


def test_thread_system_prompt_states_the_passage_once():
    from server.llm_service import thread_system_prompt

    prompt = thread_system_prompt(
        passage="The settlement was never ratified.",
        book_title="A History",
        context="[1] Another Book\nSome retrieved prose.",
    )
    assert "The settlement was never ratified." in prompt
    assert "A History" in prompt
    assert "[1] Another Book" in prompt
    # Optional blocks are omitted, never rendered empty — the general form of
    # the §4.1 bug.
    bare = thread_system_prompt(passage="Just this.")
    assert "retrieved" not in bare.lower()


# ── Reading sessions (Part 5) ───────────────────────────────────────────────

def test_heartbeat_opens_then_extends_one_session(client):
    first = client.post("/api/sessions/heartbeat", json={"book_id": "book-one", "page": 10}).json()
    second = client.post("/api/sessions/heartbeat", json={"book_id": "book-one", "page": 18}).json()

    assert first["id"] == second["id"], "a second beat must extend, not open a new session"
    assert second["start_page"] == 10
    assert second["end_page"] == 18
    assert second["pages"] == 8


def test_heartbeat_after_a_long_gap_starts_a_new_session(client):
    """
    The heartbeat design exists because there is no reliable "closed the
    laptop" event. A beat arriving hours later must not be treated as one
    long session.
    """
    from catalog.reading_sessions import SESSION_GAP_SECONDS

    first = client.post("/api/sessions/heartbeat", json={"book_id": "book-one", "page": 1}).json()

    stale = (datetime.now() - timedelta(seconds=SESSION_GAP_SECONDS + 60)).isoformat(timespec="seconds")
    db = client.app.state.db
    db.conn.execute(
        "UPDATE reading_sessions SET started_at = ?, ended_at = ? WHERE id = ?",
        (stale, stale, first["id"]),
    )
    db.conn.commit()

    second = client.post("/api/sessions/heartbeat", json={"book_id": "book-one", "page": 2}).json()
    assert second["id"] != first["id"]


def test_paging_backwards_does_not_produce_negative_pages(client):
    client.post("/api/sessions/heartbeat", json={"book_id": "book-one", "page": 100})
    session = client.post("/api/sessions/heartbeat", json={"book_id": "book-one", "page": 40}).json()
    assert session["pages"] >= 0


def test_heartbeat_requires_a_real_book(client):
    assert client.post("/api/sessions/heartbeat", json={"book_id": "nope"}).status_code == 404


def test_session_stats_ignore_page_flips(client):
    """Sessions under the floor are not reading and must not pad the streak."""
    from catalog.reading_sessions import MIN_SESSION_SECONDS

    client.post("/api/sessions/heartbeat", json={"book_id": "book-one", "page": 1})
    stats = client.get("/api/sessions/stats").json()
    assert stats["sessions"] == 0, "a zero-second session is a click, not a session"

    db = client.app.state.db
    db.conn.execute("UPDATE reading_sessions SET seconds = ?, pages = 30",
                    (MIN_SESSION_SECONDS + 600,))
    db.conn.commit()

    stats = client.get("/api/sessions/stats").json()
    assert stats["sessions"] == 1
    assert stats["total_pages"] == 30
    assert stats["current_streak"] == 1
    assert stats["daily"]


def test_streak_survives_a_day_that_is_not_over_yet(client):
    """A streak that last saw activity yesterday is still live — today is young."""
    from catalog.reading_sessions import _streak

    today = datetime.now().date()
    yesterday = (today - timedelta(days=1)).isoformat()
    day_before = (today - timedelta(days=2)).isoformat()

    assert _streak([day_before, yesterday]) == 2
    assert _streak([(today - timedelta(days=5)).isoformat()]) == 0


# ── EPUB locations (§2.1) ───────────────────────────────────────────────────

def test_locations_are_absent_until_generated_then_cached(client):
    missing = client.get("/api/books/book-two/locations").json()
    assert missing["generated"] is False

    client.post("/api/books/book-two/locations",
                json={"locations": '["epubcfi(/6/2)","epubcfi(/6/4)"]', "total": 2, "chars": 1024})

    cached = client.get("/api/books/book-two/locations").json()
    assert cached["generated"] is True
    assert cached["total"] == 2


def test_storing_locations_requires_a_real_book(client):
    r = client.post("/api/books/nope/locations", json={"locations": "[]", "total": 0})
    assert r.status_code == 404


# ── Export (Part 5) ─────────────────────────────────────────────────────────

def test_markdown_export_carries_highlights_notes_and_threads(client):
    client.post("/api/annotations", json={
        "book_id": "book-one", "kind": "highlight", "page": 12,
        "text": "A sentence worth keeping.", "note": "why this matters",
    })
    client.post("/api/annotations", json={
        "book_id": "book-one", "kind": "bookmark", "page": 40,
    })
    thread = client.post("/api/threads", json={
        "book_id": "book-one", "passage": "The pinned passage.", "retrieve": False,
        "title": "On method",
    }).json()
    db = client.app.state.db
    db.add_message(thread["id"], "user", "What is the claim?")
    db.add_message(thread["id"], "assistant", "That method precedes result.")

    body = client.get("/api/export/markdown").text

    assert "Self-Help and Other Fictions" in body
    assert "> A sentence worth keeping." in body
    assert "why this matters" in body
    assert "### Bookmarks" in body
    assert "On method" in body
    assert "That method precedes result." in body


def test_markdown_export_can_be_scoped_to_one_book(client):
    client.post("/api/annotations", json={
        "book_id": "book-one", "kind": "highlight", "text": "From book one.",
    })
    client.post("/api/annotations", json={
        "book_id": "book-two", "kind": "highlight", "text": "From book two.",
    })

    body = client.get("/api/export/markdown?book_id=book-one").text
    assert "From book one." in body
    assert "From book two." not in body


def test_export_of_an_empty_library_is_still_valid_markdown(client):
    body = client.get("/api/export/markdown").text
    assert body.startswith("# ")
    assert "Nothing to export" in body


def test_export_sets_a_download_filename(client):
    client.post("/api/annotations", json={"book_id": "book-one", "text": "x" * 20})
    r = client.get("/api/export/markdown?book_id=book-one")
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["content-type"].startswith("text/markdown")


def test_export_rejects_an_unknown_book(client):
    assert client.get("/api/export/markdown?book_id=nope").status_code == 404


# ── Duplicates (Part 5) ─────────────────────────────────────────────────────

def test_duplicates_are_grouped_under_their_canonical_book(client):
    """`book-two` is flagged `duplicate_of: book-one` by the fixture."""
    groups = client.get("/api/duplicates").json()["groups"]
    assert len(groups) == 1
    assert groups[0]["canonical"]["id"] == "book-one"
    assert [c["id"] for c in groups[0]["copies"]] == ["book-two"]


def test_keeping_a_copy_makes_it_canonical_and_leaves_one_group(client):
    client.post("/api/duplicates/book-two/keep")

    groups = client.get("/api/duplicates").json()["groups"]
    assert len(groups) == 1
    assert groups[0]["canonical"]["id"] == "book-two"
    assert [c["id"] for c in groups[0]["copies"]] == ["book-one"]

    # The new canonical must not point at anything, or the group is a cycle.
    assert client.get("/api/books/book-two").json()["duplicate_of"] in (None, "")


def test_dismissing_removes_the_mark_and_keeps_both_books(client):
    client.delete("/api/duplicates/book-two")

    assert client.get("/api/duplicates").json()["groups"] == []
    assert client.get("/api/books/book-two").status_code == 200
    assert client.get("/api/books/book-one").status_code == 200


def test_duplicate_actions_reject_unknown_books(client):
    assert client.post("/api/duplicates/nope/keep").status_code == 404
    assert client.delete("/api/duplicates/nope").status_code == 404


def test_nothing_here_deletes_a_file(client, tmp_path):
    """
    Resolving a duplicate must never touch the disk. Deciding which of two
    files to destroy is the user's call, and a wrong one is unrecoverable
    from inside this app.
    """
    import server.routes.duplicates as module
    source = module.__loader__.get_source(module.__name__)
    for forbidden in ("unlink", "os.remove", "shutil.rmtree", "rmtree"):
        assert forbidden not in source
