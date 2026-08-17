"""Pipeline control routes."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..tasks import run_embedding_generation, run_pipeline_background, task_tracker

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class PipelineRunRequest(BaseModel):
    max_books: int = 0
    file_types: Optional[list[str]] = None
    llm: bool = False
    embed: bool = False
    force: bool = False


@router.get("/status")
def pipeline_status():
    task = task_tracker.get_task("pipeline")
    if not task:
        return {"status": "idle"}
    return task


@router.post("/run")
def run_pipeline(body: PipelineRunRequest, request: Request):
    if task_tracker.is_running("pipeline"):
        raise HTTPException(409, "Pipeline is already running")
    run_pipeline_background(
        request.app.state.db,
        request.app.state.similarity,
        max_books=body.max_books,
        file_types=body.file_types,
        llm=body.llm,
        embed=body.embed,
        force=body.force,
    )
    return {"status": "started"}


@router.post("/generate-embeddings")
def generate_embeddings(request: Request):
    if task_tracker.is_running("embeddings"):
        raise HTTPException(409, "Embedding generation is already running")
    run_embedding_generation(request.app.state.db, request.app.state.similarity)
    return {"status": "started"}


@router.get("/embedding-status")
def embedding_status():
    task = task_tracker.get_task("embeddings")
    if not task:
        return {"status": "idle"}
    return task


@router.get("/unprocessed")
def get_unprocessed(request: Request):
    """Count files on disk that are not in the catalog yet."""
    try:
        from catalog.config import PROJECT_ROOT
        from catalog.scanner import scan_all_directories

        db = request.app.state.db
        existing = {
            row["file_path"]
            for row in db.conn.execute("SELECT file_path FROM books").fetchall()
        }
        # `scan_all_directories` returns Paths; the old code called `.get()` on
        # them, raised AttributeError, and always reported zero.
        all_files = scan_all_directories()
        unprocessed = sum(
            1 for f in all_files if str(f.relative_to(PROJECT_ROOT)) not in existing
        )
        return {"unprocessed": unprocessed, "total_files": len(all_files)}
    except Exception as e:
        return {"unprocessed": 0, "total_files": 0, "error": str(e)}


@router.get("/report")
def quality_report(request: Request):
    """Catalog quality report: fill rates, provenance, confidence (M6)."""
    from catalog.reporting import build_report
    from catalog.store import CatalogStore

    return build_report(CatalogStore())
