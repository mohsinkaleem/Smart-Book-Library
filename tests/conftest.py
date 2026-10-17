"""Shared fixtures. The server ones build an app against a throwaway DB."""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def catalog_db(tmp_path, monkeypatch):
    """A temp `catalog.db` with a couple of books, wired into server.config."""
    from catalog.schema import ensure_schema
    import sqlite3

    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    books = [
        {
            "id": "book-one",
            "title": "Self-Help and Other Fictions",
            "authors": '["Ada Lovelace"]',
            "author_primary": "Ada Lovelace",
            "file_name": "one.pdf",
            "file_path": "pdfs/one.pdf",
            "file_type": "pdf",
            "language": "en",
            "publication_year": 1998,
            "description": "A book about self-help.",
            "status": "ok",
            "categories": '["Philosophy"]',
            "themes": '["ethics"]',
            "user_tags": '["favourites"]',
            # Indexed by `book_text_fts`, and by nothing at all before it
            # existed. `zoetrope` appears only here, so a hit on it proves the
            # text index is being searched rather than the metadata one.
            "text_excerpt": "A zoetrope spins in the corner of the study.",
            "front_matter": "Contents: On Method",
            "content_sample": "The argument proceeds by counterexample.",
        },
        {
            "id": "book-two",
            "title": "Machine Learning Systems",
            "authors": '["Grace Hopper"]',
            "author_primary": "Grace Hopper",
            "file_name": "two.epub",
            "file_path": "epubs/two.epub",
            "file_type": "epub",
            "language": "en",
            "publication_year": 2022,
            "description": "A book about machines.",
            "status": "ok",
            "categories": '["Technology"]',
            "themes": '["computing"]',
            "user_tags": "[]",
            "text_excerpt": "Gradient descent converges slowly on ill-conditioned problems.",
        },
        {
            # A second copy of `book-one`, flagged by the pipeline's duplicate
            # detector. The library shows the canonical record only, so this
            # one is absent from every listing, every facet count and the
            # dashboard total — and present on `/api/duplicates`, which is
            # where it can be resolved.
            "id": "book-one-again",
            "title": "The Art of Thinking",
            "authors": '["Ada Lovelace"]',
            "author_primary": "Ada Lovelace",
            "file_name": "one-copy.pdf",
            "file_path": "pdfs/one-copy.pdf",
            "file_type": "pdf",
            "language": "en",
            "publication_year": 1998,
            "description": "A book about self-help.",
            "status": "ok",
            "categories": '["Philosophy"]',
            "themes": '["ethics"]',
            "user_tags": "[]",
            "duplicate_of": "book-one",
        },
        {
            # Deleted from disk — every listing endpoint must hide this.
            "id": "book-gone",
            "title": "Vanished Volume",
            "authors": '["Nobody"]',
            "author_primary": "Nobody",
            "file_name": "gone.pdf",
            "file_path": "pdfs/gone.pdf",
            "file_type": "pdf",
            "language": "en",
            "publication_year": 1970,
            "status": "missing",
            "categories": "[]",
            "themes": "[]",
            "user_tags": "[]",
        },
        {
            # A language value that is not ISO-639-1. The live catalog holds
            # `po`, `sp` and `ge`; each used to be its own sidebar option.
            "id": "book-junk-lang",
            "title": "Untagged Tongue",
            "authors": '["Anon"]',
            "author_primary": "Anon",
            "file_name": "junk.pdf",
            "file_path": "pdfs/junk.pdf",
            "file_type": "pdf",
            "language": "po",
            "publication_year": 2001,
            "status": "ok",
            "categories": "[]",
            "themes": "[]",
            "user_tags": "[]",
        },
    ]
    for book in books:
        cols = ", ".join(book)
        placeholders = ", ".join("?" for _ in book)
        conn.execute(f"INSERT INTO books ({cols}) VALUES ({placeholders})", list(book.values()))
    conn.commit()
    conn.close()

    monkeypatch.setattr("server.config.DB_PATH", db_path)
    return db_path


@pytest.fixture
def client(catalog_db, tmp_path, monkeypatch):
    """A TestClient over the real app, pointed at the temp DB."""
    from fastapi.testclient import TestClient

    import server.app as app_module

    # A dist dir with one real file, so the SPA fallback is exercised.
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>")
    (dist / "favicon.ico").write_text("icon")

    # A secret next to the project root, to prove traversal cannot reach it.
    (tmp_path / "secret.env").write_text("GOOGLE_BOOKS_API_KEY=do-not-serve-me")

    monkeypatch.setattr(app_module, "DB_PATH", catalog_db)
    monkeypatch.setattr(app_module, "FRONTEND_DIST", dist)
    monkeypatch.setattr(app_module, "COVERS_DIR", tmp_path / "covers")

    with TestClient(app_module.create_app()) as test_client:
        yield test_client
