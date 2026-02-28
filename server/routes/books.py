"""Book CRUD and list routes."""
from typing import Optional
from fastapi import APIRouter, Request, Query
from fastapi.responses import FileResponse
from pathlib import Path

router = APIRouter(prefix="/api/books", tags=["books"])


@router.get("")
def list_books(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=200),
    sort: str = Query("title"),
    order: str = Query("asc"),
    file_type: Optional[str] = None,
    category: Optional[str] = None,
    theme: Optional[str] = None,
    language: Optional[str] = None,
    reading_status: Optional[str] = None,
    has_cover: Optional[bool] = None,
    has_description: Optional[bool] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    rating_min: Optional[int] = None,
    favorite: Optional[bool] = None,
    author: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
):
    db = request.app.state.db
    return db.get_books(
        page=page, per_page=per_page, sort=sort, order=order,
        file_type=file_type, category=category, theme=theme,
        language=language, reading_status=reading_status,
        has_cover=has_cover, has_description=has_description,
        year_min=year_min, year_max=year_max, rating_min=rating_min,
        favorite=favorite, author=author, tag=tag, search=search,
    )


@router.get("/{book_id}")
def get_book(book_id: str, request: Request):
    db = request.app.state.db
    book = db.get_book(book_id)
    if not book:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Book not found")
    # Check if embeddings exist
    emb_row = db.conn.execute(
        "SELECT 1 FROM embeddings WHERE book_id = ?", (book_id,)
    ).fetchone()
    book["has_embeddings"] = emb_row is not None
    return book


@router.get("/{book_id}/similar")
def get_similar(
    book_id: str,
    request: Request,
    limit: int = Query(8, ge=1, le=20),
    method: str = Query("combined"),
):
    similarity = request.app.state.similarity
    return similarity.find_similar(book_id, limit=limit, method=method)


@router.get("/{book_id}/text")
def get_book_text(book_id: str, request: Request):
    db = request.app.state.db
    book = db.get_book(book_id)
    if not book:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Book not found")
    return {"id": book_id, "title": book.get("title", ""), "text": book.get("text_excerpt", "")}


@router.patch("/{book_id}")
def update_book(book_id: str, request: Request, body: dict):
    db = request.app.state.db
    result = db.update_user_fields(book_id, body)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Book not found or no valid fields")
    return result


@router.get("/{book_id}/file")
def get_book_file(book_id: str, request: Request):
    """Serve the raw book file (PDF/EPUB) for in-browser reading."""
    from fastapi import HTTPException
    db = request.app.state.db
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    file_path = Path(book.get("file_path", ""))
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    media_types = {
        "pdf": "application/pdf",
        "epub": "application/epub+zip",
        "mobi": "application/x-mobipocket-ebook",
    }
    media_type = media_types.get(book.get("file_type", ""), "application/octet-stream")
    return FileResponse(
        str(file_path),
        media_type=media_type,
        filename=book.get("file_name", "book"),
    )
