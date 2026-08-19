"""
Background task management for pipeline runs.

The "Run pipeline" button never worked: `tasks.py` called
`pipeline.run(max_books=…)` against a `run(self)` signature, so every
invocation raised TypeError, was swallowed by a bare `except`, and surfaced as
a generic failed task. Options now reach
`PipelineConfig`, and the pipeline reports real per-book progress.

There is also no catalog.json → SQLite sync any more: the pipeline writes
SQLite directly (S1).
"""
import logging
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class TaskTracker:
    """In-memory tracker for background tasks."""

    def __init__(self):
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start_task(self, task_id: str, total: int = 0, message: str = ""):
        with self._lock:
            self._tasks[task_id] = {
                "status": "running",
                "progress": 0,
                "total": total,
                "message": message,
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "error": None,
            }

    def update_progress(self, task_id: str, progress: int, message: str = "", total: int = None):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["progress"] = progress
            if total is not None:
                task["total"] = total
            if message:
                task["message"] = message

    def complete_task(self, task_id: str, message: str = "", result: dict = None):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["status"] = "completed"
            task["completed_at"] = datetime.now().isoformat()
            if message:
                task["message"] = message
            if result:
                task["result"] = result

    def fail_task(self, task_id: str, error: str):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["status"] = "failed"
            task["error"] = error
            task["completed_at"] = datetime.now().isoformat()

    def get_task(self, task_id: str) -> Optional[dict]:
        with self._lock:
            return dict(self._tasks.get(task_id, {}))

    def is_running(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            return task is not None and task["status"] == "running"


task_tracker = TaskTracker()


def run_pipeline_background(
    db,
    similarity_engine,
    max_books: int = 0,
    file_types: Optional[list] = None,
    llm: bool = False,
    embed: bool = False,
    force: bool = False,
):
    """Run the catalog pipeline in a background thread."""

    def _run():
        try:
            from catalog.pipeline import Pipeline, PipelineConfig

            task_tracker.start_task("pipeline", message="Starting pipeline...")

            def _progress(done: int, total: int, name: str):
                task_tracker.update_progress(
                    "pipeline", done, f"{done}/{total} — {name[:60]}", total=total
                )

            config = PipelineConfig(
                max_books=max_books or None,
                file_types=set(file_types) if file_types else None,
                llm_enrich=llm,
                embed=embed,
                force_reprocess=force,
                progress_callback=_progress,
            )
            stats = Pipeline(config).run()

            task_tracker.update_progress("pipeline", stats.get("files_processed", 0),
                                         "Reloading embeddings...")
            similarity_engine.load_embeddings()

            summary = (
                f"Processed {stats['files_processed']}, skipped {stats['files_skipped']}, "
                f"{stats['api_accepted']} verified, {stats['needs_review']} need review"
            )
            task_tracker.complete_task("pipeline", summary, result=stats)
        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            task_tracker.fail_task("pipeline", str(e))

    threading.Thread(target=_run, daemon=True).start()


def run_embedding_generation(db, similarity_engine, force: bool = False):
    """
    Generate embeddings for records that lack a *current* one.

    "Current" means built by the configured model. This used to test only for
    presence, so switching `EMBEDDING_MODEL` left every book looking done
    while its vectors belonged to the previous model's space.
    """

    def _run():
        try:
            import numpy as np
            from catalog.embeddings import generate_embeddings, model_id
            from catalog.store import CatalogStore

            task_tracker.start_task("embeddings", message="Generating embeddings...")
            store = CatalogStore()
            try:
                records = store.all_records()
                task_tracker.update_progress("embeddings", 0, "Loading model...", total=len(records))

                model = model_id()
                count = 0
                for i, record in enumerate(records):
                    if force or not store.has_embedding(record.id, model=model):
                        generate_embeddings(record, force=force)
                        if record.embedding or record.metadata_embedding:
                            content = (np.array(record.embedding, dtype=np.float32).tobytes()
                                       if record.embedding else None)
                            meta = (np.array(record.metadata_embedding, dtype=np.float32).tobytes()
                                    if record.metadata_embedding else None)
                            store.store_embedding(record.id, content, meta, model=model)
                            count += 1
                    task_tracker.update_progress(
                        "embeddings", i + 1, f"Processing {i + 1}/{len(records)}"
                    )
            finally:
                store.close()

            similarity_engine.load_embeddings()
            task_tracker.complete_task("embeddings", f"Generated {count} embeddings")
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}", exc_info=True)
            task_tracker.fail_task("embeddings", str(e))

    threading.Thread(target=_run, daemon=True).start()
