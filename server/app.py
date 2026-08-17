"""
FastAPI application for the Smart Book Library.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from .config import DB_PATH, COVERS_DIR, FRONTEND_DIST
from .db import BookDatabase
from .similarity import SimilarityEngine
from .search import SearchEngine

from .routes import books, search, filters, stats, reading, pipeline, review

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

VERSION = "1.1.0"

# Covers are content-addressed by the pipeline and 18 MB of them were
# re-requested on every hard refresh. `StaticFiles` already emits `etag` and
# `last-modified` and answers conditional requests with a 304 — it just never
# said how long a client may skip asking.
COVER_CACHE_CONTROL = "public, max-age=604800"  # one week


class CachedStaticFiles(StaticFiles):
    """`StaticFiles` with a `Cache-Control` header on every response."""

    def __init__(self, *args, cache_control: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_control = cache_control

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.setdefault("Cache-Control", self.cache_control)
        return response


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
        version=VERSION,
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

    @app.get("/api/health", tags=["ops"])
    def health(request: Request):
        """
        Liveness plus the three facts worth knowing before blaming the UI:
        whether the catalog opened, whether embeddings loaded (semantic and
        hybrid search are inert without them), and whether Ollama answered.
        """
        db = request.app.state.db
        similarity = request.app.state.similarity
        return {
            "status": "ok",
            "version": VERSION,
            "books": db.get_book_count(),
            "embeddings_loaded": bool(similarity.has_embeddings),
            "database": str(DB_PATH),
        }

    # API routes
    app.include_router(books.router)
    app.include_router(search.router)
    app.include_router(filters.router)
    app.include_router(stats.router)
    app.include_router(reading.router)
    app.include_router(pipeline.router)
    app.include_router(review.router)

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception):
        """
        Return JSON for unhandled errors, as `docs/API.md` promises.

        Starlette's default is a plain-text `Internal Server Error` body,
        which the frontend's `res.json()` then chokes on.
        """
        logger.exception(f"Unhandled error on {request.method} {request.url.path}")
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    # Static files: covers
    if COVERS_DIR.exists():
        app.mount(
            "/covers",
            CachedStaticFiles(directory=str(COVERS_DIR), cache_control=COVER_CACHE_CONTROL),
            name="covers",
        )

    # Serve frontend build if it exists
    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

        dist_root = FRONTEND_DIST.resolve()
        index_html = dist_root / "index.html"

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """
            SPA fallback — serve index.html for all non-API routes.

            `full_path` is attacker-controlled and used to be joined onto
            `FRONTEND_DIST` with no containment check, so URL-encoded `../`
            segments (which survive Starlette's normalisation) served any file
            the process could read — `.env`, `data/catalog.db`, `/etc/passwd`.
            Resolve first, then require the result to sit inside the dist dir.
            """
            # Unknown API paths are 404s, not the SPA shell. Returning
            # index.html with a 200 turned every typo'd endpoint into
            # "Unexpected token '<'" on the client.
            if full_path == "api" or full_path.startswith(("api/", "covers/")):
                raise HTTPException(status_code=404, detail="Not found")

            try:
                candidate = (dist_root / full_path).resolve()
                candidate.relative_to(dist_root)
            except (ValueError, OSError):
                return FileResponse(str(index_html))

            if candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(str(index_html))
    else:
        @app.get("/")
        def root():
            return {"message": "Smart Book Library API", "docs": "/docs"}

    return app


app = create_app()
