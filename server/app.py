"""
FastAPI application for the Smart Book Library.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import DB_PATH, COVERS_DIR, FRONTEND_DIST
from .db import BookDatabase
from .similarity import SimilarityEngine
from .search import SearchEngine

from .routes import books, search, filters, stats, reading, pipeline, user, review

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: open DB, load embeddings. Shutdown: close DB."""
    logger.info("Starting Smart Book Library server...")

    # Database
    db = BookDatabase(DB_PATH)
    app.state.db = db
    logger.info(f"Database opened: {db.get_book_count()} books")

    # Similarity engine
    similarity = SimilarityEngine(db)
    similarity.load_embeddings()
    app.state.similarity = similarity

    # Search engine
    app.state.search_engine = SearchEngine(db, similarity)

    logger.info("Server ready")
    yield

    # Shutdown
    db.close()
    logger.info("Server shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Smart Book Library",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:8000", "http://127.0.0.1:5173", "http://127.0.0.1:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(books.router)
    app.include_router(search.router)
    app.include_router(filters.router)
    app.include_router(stats.router)
    app.include_router(reading.router)
    app.include_router(pipeline.router)
    app.include_router(user.router)
    app.include_router(review.router)

    # Static files: covers
    if COVERS_DIR.exists():
        app.mount("/covers", StaticFiles(directory=str(COVERS_DIR)), name="covers")

    # Serve frontend build if it exists
    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """SPA fallback — serve index.html for all non-API routes."""
            file_path = FRONTEND_DIST / full_path
            if file_path.exists() and file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(FRONTEND_DIST / "index.html"))
    else:
        @app.get("/")
        def root():
            return {"message": "Smart Book Library API", "docs": "/docs"}

    return app


app = create_app()
