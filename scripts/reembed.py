"""
Re-embed every book with the configured EMBEDDING_MODEL.

Needed after a model switch: vectors from two models share a shape and mean
nothing together, so the whole catalog has to move at once. Batched — encoding
one record at a time is 10-50x slower than a batch of them.

    python scripts/reembed.py [--force]
"""
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from catalog.config import EMBEDDING_BATCH_SIZE
from catalog.embeddings import embed_records, model_id
from catalog.store import CatalogStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("reembed")

BATCH = max(16, EMBEDDING_BATCH_SIZE)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="re-embed even books already stamped with this model")
    args = parser.parse_args()

    model = model_id()
    store = CatalogStore()
    try:
        records = [r for r in store.all_records() if r.status != "missing"]
        todo = [r for r in records
                if args.force or not store.has_embedding(r.id, model=model)]
        log.info(f"model={model}  books={len(records)}  to embed={len(todo)}")
        if not todo:
            return 0

        started = time.monotonic()
        done = 0
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            embed_records(batch, force=True)
            for record in batch:
                if not (record.embedding or record.metadata_embedding):
                    continue
                content = (np.array(record.embedding, dtype=np.float32).tobytes()
                           if record.embedding else None)
                meta = (np.array(record.metadata_embedding, dtype=np.float32).tobytes()
                        if record.metadata_embedding else None)
                store.store_embedding(record.id, content, meta, model=model)
                done += 1
            elapsed = time.monotonic() - started
            log.info(f"{min(i + BATCH, len(todo))}/{len(todo)}  "
                     f"stored={done}  {elapsed:.0f}s")

        log.info(f"done: {done} embeddings in {time.monotonic() - started:.0f}s")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
