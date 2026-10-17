"""
Route-layer tests.

Every case here corresponds to a defect that shipped: the SPA fallback served
arbitrary files, unknown `/api` paths returned the HTML shell with a 200, and
two ordinary query strings were 500s.
"""
import pytest


# ── SPA fallback containment ─────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/..%2f..%2fsecret.env",
    "/..%2f..%2f..%2f..%2f..%2f..%2f..%2fetc%2fpasswd",
    "/../../secret.env",
    "/%2e%2e%2f%2e%2e%2fsecret.env",
])
def test_spa_fallback_cannot_escape_dist(client, path):
    """Traversal must never serve a file from outside frontend/dist."""
    resp = client.get(path)
    assert resp.status_code in (200, 404)
    assert "GOOGLE_BOOKS_API_KEY" not in resp.text
    assert "root:" not in resp.text


def test_spa_fallback_serves_index_for_client_routes(client):
    resp = client.get("/books/book-one")
    assert resp.status_code == 200
    assert "<title>app</title>" in resp.text


def test_spa_fallback_serves_real_files(client):
    assert client.get("/favicon.ico").text == "icon"


# ── Unknown API paths are 404s, not the SPA shell ────────────────────────────

@pytest.mark.parametrize("path", ["/api/nope", "/api/books/x/y/z", "/covers/nope.jpg"])
def test_unknown_api_paths_404(client, path):
    resp = client.get(path)
    assert resp.status_code == 404
    assert "text/html" not in resp.headers.get("content-type", "")


# ── Query strings that used to 500 ───────────────────────────────────────────

@pytest.mark.parametrize("term", ["self-help", "AND", "OR", "*", '"', "NOT x", "a-b-c", "()"])
def test_search_filter_accepts_punctuation(client, term):
    assert client.get("/api/books", params={"search": term}).status_code == 200


def test_search_filter_actually_matches(client):
    resp = client.get("/api/books", params={"search": "self-help"})
    assert [b["id"] for b in resp.json()["items"]] == ["book-one"]


def test_search_endpoint_accepts_punctuation(client):
    for mode in ("text", "semantic", "hybrid"):
        resp = client.get("/api/search", params={"q": "self-help", "mode": mode})
        assert resp.status_code == 200, mode


def test_non_numeric_year_is_rejected_not_500(client):
    for endpoint in ("/api/filters", "/api/books", "/api/search"):
        resp = client.get(endpoint, params={"year_min": "abc"})
        assert resp.status_code == 422, endpoint


def test_numeric_year_filters(client):
    resp = client.get("/api/books", params={"year_min": 2010})
    assert [b["id"] for b in resp.json()["items"]] == ["book-two"]


# ── `missing` records stay hidden everywhere ─────────────────────────────────

def test_missing_books_are_hidden_from_list(client):
    ids = [b["id"] for b in client.get("/api/books").json()["items"]]
    assert "book-gone" not in ids


def test_stats_totals_match_the_library(client):
    """Three live books; `book-gone` is `missing` and counts nowhere."""
    total_listed = client.get("/api/books").json()["total"]
    assert client.get("/api/stats").json()["total_books"] == total_listed == 3


# ── PATCH ────────────────────────────────────────────────────────────────────

def test_patch_unknown_book_404s_without_orphaning_a_row(client, catalog_db):
    import sqlite3

    assert client.patch("/api/books/does-not-exist", json={"favorite": True}).status_code == 404

    conn = sqlite3.connect(str(catalog_db))
    rows = conn.execute("SELECT COUNT(*) FROM user_data").fetchone()[0]
    conn.close()
    assert rows == 0


def test_patch_updates_and_persists(client):
    resp = client.patch("/api/books/book-one", json={"favorite": True, "user_rating": 4})
    assert resp.status_code == 200
    assert resp.json()["favorite"] is True
    assert client.get("/api/books/book-one").json()["user_rating"] == 4


def test_patch_can_clear_a_rating(client):
    client.patch("/api/books/book-one", json={"user_rating": 4})
    client.patch("/api/books/book-one", json={"user_rating": None})
    assert client.get("/api/books/book-one").json()["user_rating"] is None


def test_patch_rejects_unknown_fields(client):
    resp = client.patch("/api/books/book-one", json={"title": "Hacked"})
    assert resp.status_code == 422
    assert client.get("/api/books/book-one").json()["title"] != "Hacked"


def test_patch_rejects_bad_reading_status(client):
    assert client.patch(
        "/api/books/book-one", json={"reading_status": "banana"}
    ).status_code == 422


# ── 404s rather than empty-but-successful responses ──────────────────────────

def test_similar_on_unknown_book_404s(client):
    assert client.get("/api/books/nope/similar").status_code == 404


def test_book_file_missing_on_disk_404s(client):
    assert client.get("/api/books/book-one/file").status_code == 404


def test_unknown_book_404s(client):
    assert client.get("/api/books/nope").status_code == 404
    assert client.get("/api/reading/nope/text").status_code == 404


# ── Filters apply in every search mode ───────────────────────────────────────

@pytest.mark.parametrize("mode", ["text", "semantic", "hybrid"])
def test_tag_filter_is_not_ignored(client, mode):
    """`tag` had no branch in the Python filter copy used by semantic/hybrid."""
    resp = client.get("/api/search", params={"q": "book", "mode": mode, "tag": "no-such-tag"})
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.parametrize("mode", ["text", "semantic", "hybrid"])
def test_file_type_filter_applies(client, mode):
    resp = client.get("/api/search", params={"q": "book", "mode": mode, "file_type": "epub"})
    assert all(b["file_type"] == "epub" for b in resp.json()["items"])


def test_facets_exclude_missing_books(client):
    facets = client.get("/api/filters").json()
    assert facets["total_matching"] == 3
    assert {f["name"] for f in facets["file_types"]} == {"pdf", "epub"}


# ── Deleted endpoints stay deleted ───────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/api/books/book-one/text",
    "/api/stats/reading",
    "/api/review/fields",
    "/api/filters/categories",
    "/api/filters/themes",
    "/api/filters/authors",
    "/api/filters/languages",
    "/api/filters/years",
    "/api/filters/tags",
])
def test_removed_endpoints_are_gone(client, path):
    assert client.get(path).status_code == 404


def test_removed_user_patch_route_is_gone(client):
    # 405: the GET-only SPA fallback matches the path but not the method.
    assert client.patch(
        "/api/user/books/book-one", json={"favorite": True}
    ).status_code in (404, 405)


# ── Book text is searchable, and results say why they matched ────────────────

def test_book_text_is_indexed(client):
    """
    "Full-Text Search" used to mean full text over *metadata*: the extracted
    prose was stored and never indexed. `zoetrope` exists only in
    `text_excerpt`.
    """
    resp = client.get("/api/search", params={"q": "zoetrope", "mode": "text"})
    assert resp.status_code == 200
    assert [b["id"] for b in resp.json()["items"]] == ["book-one"]


def test_book_text_is_searchable_from_the_list_filter_too(client):
    """`?search=` on the list endpoint must agree with `/api/search`."""
    resp = client.get("/api/books", params={"search": "zoetrope"})
    assert [b["id"] for b in resp.json()["items"]] == ["book-one"]


def test_facet_counts_agree_with_text_matches(client):
    facets = client.get("/api/filters", params={"search": "zoetrope"}).json()
    assert facets["total_matching"] == 1


def test_results_carry_a_highlighted_snippet(client):
    from server.db import SNIPPET_CLOSE, SNIPPET_OPEN

    item = client.get(
        "/api/search", params={"q": "zoetrope", "mode": "text"}
    ).json()["items"][0]
    assert item["match_field"] == "text"
    assert SNIPPET_OPEN in item["snippet"] and SNIPPET_CLOSE in item["snippet"]
    # The delimiters wrap the matched term, not the whole snippet.
    assert "zoetrope" in item["snippet"].lower()


def test_metadata_still_outranks_body_text(client):
    """
    A title match must beat a passing mention in a long excerpt — the reason
    the two indexes are separate rather than one combined table.
    """
    items = client.get(
        "/api/search", params={"q": "machine learning", "mode": "text"}
    ).json()["items"]
    assert items[0]["id"] == "book-two"


def test_snippets_survive_hybrid_ranking(client):
    """`_page` hydrates from `get_books_by_ids`, which drops the FTS columns."""
    items = client.get(
        "/api/search", params={"q": "zoetrope", "mode": "hybrid"}
    ).json()["items"]
    assert items and items[0]["snippet"]


# ── Default search mode ──────────────────────────────────────────────────────

def test_search_defaults_to_hybrid(client):
    """Server, UI and README used to disagree; `hybrid` is the answer."""
    items = client.get("/api/search", params={"q": "machine"}).json()["items"]
    assert items and all(b["match_type"] == "hybrid" for b in items)


# ── Reading progress and reader position ─────────────────────────────────────

def test_reader_position_round_trips(client):
    """
    `progress_percent` was in the schema, in `USER_FIELDS`, in the TS type and
    offered as `sort=last_opened` — and nothing ever wrote it.
    """
    resp = client.patch("/api/books/book-two", json={
        "progress_percent": 42.5,
        "reader_position": "epubcfi(/6/14[chap05]!/4/2/14/1:0)",
        "last_opened": "2026-08-17T10:00:00Z",
    })
    assert resp.status_code == 200

    book = client.get("/api/books/book-two").json()
    assert book["progress_percent"] == 42.5
    assert book["reader_position"].startswith("epubcfi(")
    assert book["last_opened"] == "2026-08-17T10:00:00Z"


def test_reader_position_is_length_bounded(client):
    resp = client.patch("/api/books/book-one", json={"reader_position": "x" * 2001})
    assert resp.status_code == 422


def test_continue_reading_lists_opened_unfinished_books(client):
    assert client.get("/api/books/continue-reading").json() == []

    client.patch("/api/books/book-two", json={
        "last_opened": "2026-08-17T10:00:00Z",
        "progress_percent": 30,
        "reading_status": "in_progress",
    })
    shelf = client.get("/api/books/continue-reading").json()
    assert [b["id"] for b in shelf] == ["book-two"]

    # Finishing it takes it off the shelf.
    client.patch("/api/books/book-two", json={"reading_status": "finished"})
    assert client.get("/api/books/continue-reading").json() == []


def test_continue_reading_is_not_shadowed_by_the_book_id_route(client):
    """Registered before `/{book_id}`, or the path is read as an id and 404s."""
    assert client.get("/api/books/continue-reading").status_code == 200


# ── Language normalisation ───────────────────────────────────────────────────

def test_junk_language_codes_are_bucketed_as_unknown(client):
    facets = client.get("/api/filters").json()
    names = {f["name"] for f in facets["languages"]}
    assert "po" not in names
    assert "unknown" in names
    assert "en" in names


def test_unknown_language_filter_matches_the_raw_values(client):
    resp = client.get("/api/books", params={"language": "unknown"})
    assert [b["id"] for b in resp.json()["items"]] == ["book-junk-lang"]


def test_unknown_language_sorts_last(client):
    languages = client.get("/api/filters").json()["languages"]
    assert languages[-1]["name"] == "unknown"


# ── Stats ────────────────────────────────────────────────────────────────────

def test_stats_counts_duplicates(client):
    """`duplicate_of` was computed, stored, indexed — and never surfaced."""
    assert client.get("/api/stats").json()["duplicates"] == 1


# ── Boolean filters are symmetric ────────────────────────────────────────────

@pytest.mark.parametrize("mode", ["text", "semantic", "hybrid"])
def test_has_description_false_is_honoured(client, mode):
    """
    `has_cover=false` worked on the list endpoint and was ignored by the
    search one — the two filter implementations had drifted.
    """
    ids = {
        b["id"]
        for b in client.get(
            "/api/search", params={"q": "a", "mode": mode, "has_description": "false"}
        ).json()["items"]
    }
    assert "book-one" not in ids and "book-two" not in ids


def test_has_description_false_on_the_list_endpoint(client):
    ids = {b["id"] for b in client.get(
        "/api/books", params={"has_description": "false"}
    ).json()["items"]}
    assert ids == {"book-junk-lang"}


# ── Operations ───────────────────────────────────────────────────────────────

def test_health_reports_the_catalog(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    # `book-gone` is `missing`, `book-one-again` is a hidden duplicate —
    # health reports what the library lists, so all three figures agree.
    assert body["books"] == 3
    assert body["version"]
    assert "embeddings_loaded" in body


def test_llm_status_reports_the_configured_model(client, monkeypatch):
    """The panel gates its buttons on this; it used to be a bare boolean."""
    import server.llm_service as llm

    monkeypatch.setattr(llm, "_status_cache", (0.0, {}))
    monkeypatch.setattr(llm, "_probe", lambda: {"available": False, "reason": "refused"})

    body = client.get("/api/reading/llm-status").json()
    assert body["available"] is False
    assert body["reason"] == "refused"
    assert body["model"] == llm.OLLAMA_MODEL
    assert body["base_url"] == llm.OLLAMA_BASE_URL


# ── Review queue ordering ────────────────────────────────────────────────────

@pytest.fixture
def flagged_books(catalog_db):
    """
    Three flagged records whose `match_score` ordering disagrees with how
    certain their identities actually are.
    """
    import json
    import sqlite3

    def sources(**fields):
        return json.dumps({
            name: {"source": src, "confidence": conf}
            for name, (src, conf) in fields.items()
        })

    rows = [
        # Perfect embedded metadata, no provider match: NULL score used to put
        # this at the very head of the queue.
        ("flag-file-meta", "Understanding Salafism", '["A Real Author"]', "9780000000002",
         None, sources(title=("file_meta", 0.7), authors=("file_meta", 0.7),
                       isbn_13=("file_meta", 0.9))),
        # A filename guess with a borderline match applied to nothing.
        ("flag-filename", "Some Book Name", "[]", "",
         0.61, sources(title=("filename", 0.4))),
        # Nothing at all could be established.
        ("flag-untitled", "", "[]", "", None, "{}"),
    ]
    conn = sqlite3.connect(str(catalog_db))
    for book_id, title, authors, isbn, score, field_sources in rows:
        conn.execute(
            """INSERT INTO books (id, title, authors, isbn_13, match_score, field_sources,
                                  file_name, file_path, file_type, status, needs_review,
                                  categories, themes, user_tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pdf', 'ok', 1, '[]', '[]', '[]')""",
            (book_id, title, authors, isbn, score, field_sources,
             f"{book_id}.pdf", f"pdfs/{book_id}.pdf"),
        )
    conn.commit()
    conn.close()
    return [r[0] for r in rows]


def test_review_queue_is_ordered_by_identity_not_match_score(client, flagged_books):
    """
    `match_score` scores an API candidate, so it is NULL for a record
    identified from the file's own metadata. Ordering on it put the best
    record in the queue at the top of the "worst first" list.
    """
    items = client.get("/api/review/queue").json()["items"]
    order = [i["id"] for i in items]

    assert order.index("flag-untitled") < order.index("flag-filename")
    assert order.index("flag-filename") < order.index("flag-file-meta")

    by_id = {i["id"]: i for i in items}
    assert by_id["flag-untitled"]["identity_confidence"] == 0.0
    assert by_id["flag-file-meta"]["identity_confidence"] > by_id["flag-filename"]["identity_confidence"]
    # The candidate score is still reported, it just no longer sets the order.
    assert by_id["flag-filename"]["match_score"] == 0.61
    assert by_id["flag-file-meta"]["match_score"] is None


def test_review_queue_paginates_without_dropping_or_repeating(client, flagged_books):
    """The page is fetched by id after ranking, so the slicing must still be exact."""
    first = client.get("/api/review/queue?page=1&per_page=2").json()
    second = client.get("/api/review/queue?page=2&per_page=2").json()

    assert first["total"] == second["total"] == 3
    assert first["pages"] == 2
    seen = [i["id"] for i in first["items"]] + [i["id"] for i in second["items"]]
    assert len(seen) == len(set(seen)) == 3


def test_identity_confidence_is_on_every_book(client):
    """Derived on the row mapper, so the ordinary book payload carries it too."""
    book = client.get("/api/books/book-one").json()
    assert "identity_confidence" in book
    assert 0.0 <= book["identity_confidence"] <= 1.0

