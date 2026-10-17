#!/usr/bin/env python3
"""
Does cross-encoder reranking earn its place in passage search?

`PASSAGE_RERANK` has been off since it shipped, and the comment beside it
claimed "a large precision gain for ~50 ms" — a claim nobody had tested on
this index. This script produces the evidence: the same queries run with
reranking off and on, the top results of each, what it cost, and what it
changed. Judging whether the new order is *better* is a reading job, not a
metric; the script prints the two orderings side by side for that.

    .venv/bin/python scripts/eval_rerank.py            # full run
    .venv/bin/python scripts/eval_rerank.py --limit 5  # quicker

Writes JSON next to this file's output path for re-reading without re-running.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before `server.passages` is imported: it reads the flag at
# import time. Every "off" measurement passes `rerank=False` explicitly, so
# the flag being on here only means the model is *available*.
os.environ["PASSAGE_RERANK"] = "true"

# Roughly the shape of this library: half CS/ML, half Islamic studies,
# philosophy and history. Short topical phrases, natural-language questions,
# and proper nouns, because those three retrieve very differently.
QUERIES = [
    # Topical phrases
    "gradient descent convergence",
    "attention mechanism transformers",
    "consensus in distributed systems",
    "the problem of induction",
    "abrogation in quranic exegesis",
    "usury and islamic finance",
    "fall of the ottoman empire",
    "virtue ethics and character",
    # Natural-language questions
    "how does backpropagation actually work",
    "what makes a hash table collide",
    "why did the abbasid caliphate decline",
    "what is the difference between fiqh and sharia",
    "how should a muslim treat a neighbour",
    "what did kuhn mean by a paradigm shift",
    # Proper nouns
    "Ibn Taymiyyah",
    "Al-Ghazali",
    "Donald Knuth",
    "Thomas Kuhn",
]


def rss_mb() -> float:
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux kilobytes.
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10, help="results per query")
    ap.add_argument("--out", default="", help="where to write the JSON report")
    args = ap.parse_args()

    from server.db import BookDatabase
    from server.passages import PassageIndex
    from catalog.embeddings import encode_query

    db = BookDatabase()
    index = PassageIndex(db)
    index.load()
    if not index.available:
        print("No passage index. Run scripts/build_passage_index.py first.")
        return 1
    print(f"index: {index.chunk_count:,} chunks\n" if hasattr(index, "chunk_count") else "")

    before_mb = rss_mb()
    rows = []
    cold_ms = None

    for q in QUERIES:
        vec = encode_query(q)

        t0 = time.perf_counter()
        off = index.search(q, vec, limit=args.limit, mode="hybrid", rerank=False)
        off_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        on = index.search(q, vec, limit=args.limit, mode="hybrid", rerank=True)
        on_ms = (time.perf_counter() - t0) * 1000
        if cold_ms is None:
            cold_ms = on_ms       # first call carries the model load

        def card(h):
            return {
                "chunk_id": h.chunk_id, "book_id": h.book_id,
                "score": round(float(h.score), 4),
                "text": " ".join(h.text.split())[:400],
            }

        top3_off = [h.chunk_id for h in off[:3]]
        top3_on = [h.chunk_id for h in on[:3]]
        rows.append({
            "query": q,
            "off_ms": round(off_ms, 1),
            "on_ms": round(on_ms, 1),
            "top3_changed": top3_off != top3_on,
            "top1_changed": top3_off[:1] != top3_on[:1],
            "off": [card(h) for h in off[:3]],
            "on": [card(h) for h in on[:3]],
        })
        print(f"{'~' if rows[-1]['top3_changed'] else '='} {q}"
              f"   off {off_ms:6.0f}ms   on {on_ms:6.0f}ms")

    warm = [r["on_ms"] for r in rows[1:]]
    off_all = [r["off_ms"] for r in rows]
    summary = {
        "queries": len(rows),
        "top3_changed": sum(r["top3_changed"] for r in rows),
        "top1_changed": sum(r["top1_changed"] for r in rows),
        "off_median_ms": round(sorted(off_all)[len(off_all) // 2], 1),
        "on_cold_ms": round(cold_ms or 0, 1),
        "on_median_warm_ms": round(sorted(warm)[len(warm) // 2], 1) if warm else None,
        "rss_before_mb": round(before_mb, 1),
        "rss_after_mb": round(rss_mb(), 1),
    }
    print("\n" + json.dumps(summary, indent=2))

    out = Path(args.out) if args.out else Path("rerank_eval.json")
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(f"\nwrote {out}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
