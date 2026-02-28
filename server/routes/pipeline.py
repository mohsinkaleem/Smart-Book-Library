"""Pipeline control routes."""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from ..tasks import task_tracker, run_pipeline_background, run_embedding_generation

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class PipelineRunRequest(BaseModel):
    max_books: int = 0
    file_types: Optional[list[str]] = None


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
    db = request.app.state.db
    similarity = request.app.state.similarity
    run_pipeline_background(db, similarity, max_books=body.max_books, file_types=body.file_types)
    return {"status": "started"}


@router.post("/generate-embeddings")
def generate_embeddings(request: Request):
    if task_tracker.is_running("embeddings"):
        raise HTTPException(409, "Embedding generation is already running")
    db = request.app.state.db
    similarity = request.app.state.similarity
    run_embedding_generation(db, similarity)
    return {"status": "started"}


@router.get("/embedding-status")
def embedding_status():
    task = task_tracker.get_task("embeddings")
    if not task:
        return {"status": "idle"}
    return task


@router.get("/unprocessed")
def get_unprocessed(request: Request):
    """Count files not yet in catalog."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    try:
        from catalog.scanner import scan_all_directories
        from catalog.config import SUPPORTED_EXTENSIONS
        db = request.app.state.db

        all_files = scan_all_directories()
        existing = set()
        rows = db.conn.execute("SELECT file_path FROM books").fetchall()
        for r in rows:
            existing.add(r["file_path"])

        new_count = sum(1 for f in all_files if f.get("file_path", "") not in existing)
        return {"unprocessed": new_count, "total_files": len(all_files)}
    except Exception as e:
        return {"unprocessed": 0, "total_files": 0, "error": str(e)}
