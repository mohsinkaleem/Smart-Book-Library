"""
Background task management for pipeline runs.
"""
import logging
import threading
import time
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

    def update_progress(self, task_id: str, progress: int, message: str = ""):
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["progress"] = progress
                if message:
                    self._tasks[task_id]["message"] = message

    def complete_task(self, task_id: str, message: str = ""):
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "completed"
                self._tasks[task_id]["completed_at"] = datetime.now().isoformat()
                if message:
                    self._tasks[task_id]["message"] = message

    def fail_task(self, task_id: str, error: str):
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "failed"
                self._tasks[task_id]["error"] = error
                self._tasks[task_id]["completed_at"] = datetime.now().isoformat()

    def get_task(self, task_id: str) -> Optional[dict]:
        with self._lock:
            return self._tasks.get(task_id, {}).copy()

    def is_running(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            return task is not None and task["status"] == "running"


# Global tracker
task_tracker = TaskTracker()


def run_pipeline_background(db, similarity_engine, max_books: int = 0, file_types: Optional[list] = None):
    """Run the catalog pipeline in a background thread."""
    import sys
    sys.path.insert(0, str(db.db_path.parent.parent))

    def _run():
        try:
            from catalog.pipeline import Pipeline, PipelineConfig

            task_tracker.start_task("pipeline", message="Starting pipeline...")

            config = PipelineConfig()
            if file_types:
                config.file_types = file_types

            pipeline = Pipeline(config)

            task_tracker.update_progress("pipeline", 0, "Running pipeline...")
            pipeline.run(max_books=max_books)

            # Sync back to SQLite
            task_tracker.update_progress("pipeline", 0, "Syncing to SQLite...")
            _sync_catalog_to_sqlite(db)

            # Reload embeddings
            task_tracker.update_progress("pipeline", 0, "Reloading embeddings...")
            similarity_engine.load_embeddings()

            task_tracker.complete_task("pipeline", "Pipeline completed successfully")
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            task_tracker.fail_task("pipeline", str(e))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def run_embedding_generation(db, similarity_engine):
    """Generate embeddings in a background thread."""
    def _run():
        try:
            from catalog.database import CatalogDatabase
            from catalog.embeddings import generate_embeddings

            task_tracker.start_task("embeddings", message="Generating embeddings...")
            catalog = CatalogDatabase()
            records = catalog.all_records()

            import numpy as np
            count = 0
            for i, record in enumerate(records):
                if not record.embedding or not record.metadata_embedding:
                    generate_embeddings(record)
                    if record.embedding or record.metadata_embedding:
                        content_emb = np.array(record.embedding, dtype=np.float32).tobytes() if record.embedding else None
                        metadata_emb = np.array(record.metadata_embedding, dtype=np.float32).tobytes() if record.metadata_embedding else None
                        db.store_embedding(record.id, content_emb, metadata_emb)
                        count += 1
                task_tracker.update_progress("embeddings", i + 1, f"Processing {i+1}/{len(records)}")

            catalog.save()
            similarity_engine.load_embeddings()
            task_tracker.complete_task("embeddings", f"Generated {count} new embeddings")
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            task_tracker.fail_task("embeddings", str(e))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def _sync_catalog_to_sqlite(db):
    """Re-import catalog.json into SQLite after pipeline run."""
    from catalog.database import CatalogDatabase
    import numpy as np

    catalog = CatalogDatabase()
    records = catalog.all_records()
    for record in records:
        db.upsert_book(record.to_dict())
        if record.embedding or record.metadata_embedding:
            content_emb = np.array(record.embedding, dtype=np.float32).tobytes() if record.embedding else None
            metadata_emb = np.array(record.metadata_embedding, dtype=np.float32).tobytes() if record.metadata_embedding else None
            db.store_embedding(record.id, content_emb, metadata_emb)
    logger.info(f"Synced {len(records)} records from catalog.json to SQLite")
