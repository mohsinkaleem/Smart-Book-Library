"""Book CRUD and list routes."""
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from ..config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PROJECT_ROOT
from .params import Filters
from .schemas import UserFieldsUpdate

router = APIRouter(prefix="/api/books", tags=["books"])

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "epub": "application/epub+zip",
    "mobi": "application/x-mobipocket-ebook",
}


@router.get("")
def list_books(
    request: Request,
    filters: Filters,
    page: int = Query(1, ge=1),
    per_page: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    sort: str = Query("title"),
    order: str = Query("asc"),
):
    db = request.app.state.db
    return db.get_books(page=page, per_page=per_page, sort=sort, order=order,
                        **filters.as_dict())


@router.get("/continue-reading")
def continue_reading(request: Request, limit: int = Query(8, ge=1, le=24)):
    """
    Books opened but not finished, most recently opened first.

    Declared before `/{book_id}`: FastAPI matches routes in registration
    order, so the other way round this path would be read as a book id.
    """
    return request.app.state.db.get_continue_reading(limit=limit)


@router.get("/{book_id}")
def get_book(book_id: str, request: Request):
    db = request.app.state.db
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    book["has_embeddings"] = db.has_embedding(book_id)
    return book


@router.get("/{book_id}/similar")
def get_similar(
    book_id: str,
    request: Request,
    limit: int = Query(8, ge=1, le=20),
    method: str = Query("combined"),
):
    # `find_similar` returns [] for an unknown id, which used to surface as
    # `200 []` — indistinguishable from "no similar books".
    if not request.app.state.db.get_book(book_id):
        raise HTTPException(status_code=404, detail="Book not found")
    return request.app.state.similarity.find_similar(book_id, limit=limit, method=method)


@router.patch("/{book_id}")
def update_book(book_id: str, body: UserFieldsUpdate, request: Request):
    db = request.app.state.db
    fields = body.changed_fields()
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = db.update_user_fields(book_id, fields)
    if not result:
        raise HTTPException(status_code=404, detail="Book not found")
    return result


@router.get("/{book_id}/file")
@router.get("/{book_id}/file.epub")
def get_book_file(book_id: str, request: Request):
    """
    Serve the raw book file (PDF/EPUB) for in-browser reading.

    The `.epub` alias exists because epub.js decides how to open a book from
    the URL's extension: with none, it assumes an *unpacked* EPUB directory
    and goes looking for `META-INF/container.xml` next to the URL — which is
    why the EPUB reader only ever showed "Error loading book".
    """
    db = request.app.state.db
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # `file_path` is stored relative to the project root (`pdfs/…`). Left
    # relative, `FileResponse` resolved it against whatever directory uvicorn
    # happened to be started from, so "Read Book" 404'd unless the server was
    # launched from the repo root.
    stored = (book.get("file_path") or "").strip()
    if not stored:
        raise HTTPException(status_code=404, detail="File not found on disk")
    file_path = (PROJECT_ROOT / stored).resolve()
    try:
        file_path.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="File not found on disk")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        str(file_path),
        media_type=MEDIA_TYPES.get(book.get("file_type", ""), "application/octet-stream"),
        filename=book.get("file_name", "book"),
    )
