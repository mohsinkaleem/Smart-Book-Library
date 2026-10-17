#!/usr/bin/env python3
"""
Re-measure the passage relevance floors against the current index.

The §1.4 protocol the constants in `server/passages.py` were set with: real
queries against nonsense ones, recording where each band's top score lands,
then reading off the floor that rejects the most nonsense without costing a
real query a single hit. A floor is a property of the score distribution, so
it has to be re-run whenever that distribution moves — a bigger index, a
different model, or a change to what text is embedded.

    .venv/bin/python scripts/calibrate_floors.py

Prints the two bands, what each candidate floor would cost, and the
passage-to-passage band that `MIN_SIMILAR_PASSAGE_SCORE` covers.
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Real subjects, in the proportions this library actually holds.
REAL = [
    "gradient descent convergence",
    "attention mechanism transformers",
    "consensus in distributed systems",
    "how does backpropagation actually work",
    "what makes a hash table collide",
    "the problem of induction",
    "how does the author define modernity",
    "abrogation in quranic exegesis",
    "usury and islamic finance",
    "why did the abbasid caliphate decline",
    "what is the difference between fiqh and sharia",
    "what did kuhn mean by a paradigm shift",
]

# Plausible English, absent subject matter. The point is not gibberish — a
# floor that only rejects keyboard mashing is not doing any work.
NONSENSE = [
    "zebra husbandry in antarctica",
    "competitive pineapple sculpting leagues",
    "submarine beekeeping regulations",
    "the tax treatment of unicorn breeding",
    "lunar surfing championship rules",
    "how to tune a harpsichord for cats",
    "municipal policy on dragon parking",
    "the nutritional content of moon rocks",
    "igloo air conditioning maintenance",
    "professional cloud juggling techniques",
]

CANDIDATE_FLOORS = [0.62, 0.65, 0.68, 0.71, 0.74, 0.77, 0.80]


def main() -> int:
    from server.db import BookDatabase
    from server.passages import PassageIndex
    from catalog.embeddings import encode_query, encode_passage

    db = BookDatabase()
    index = PassageIndex(db)
    index.load()
    if not index.available:
        print("No usable passage index.")
        return 1

    def top_scores(queries):
        out = {}
        for q in queries:
            # No floor at all: this measures the distribution, it does not
            # apply a judgement to it.
            hits = index.search(q, encode_query(q), limit=50, mode="semantic",
                                rerank=False, min_score=0.0, relative_floor=0.0)
            out[q] = [float(h.score) for h in hits]
        return out

    real = top_scores(REAL)
    nonsense = top_scores(NONSENSE)

    def band(d):
        tops = [s[0] for s in d.values() if s]
        return (min(tops), max(tops)) if tops else (0.0, 0.0)

    print(f"index: {len(index.matrix):,} vectors\n")
    rl, rh = band(real)
    nl, nh = band(nonsense)
    print(f"  real queries    top score {rl:.3f} - {rh:.3f}")
    print(f"  nonsense        top score {nl:.3f} - {nh:.3f}")
    print(f"  gap             {rl - nh:+.3f}\n")

    print("  floor   nonsense surviving   real queries losing hits   real hits lost")
    for floor in CANDIDATE_FLOORS:
        survived = sum(1 for s in nonsense.values() if s and s[0] >= floor)
        starved = sum(1 for s in real.values() if not [x for x in s if x >= floor])
        lost = sum(len([x for x in s if x < floor]) for s in real.values())
        print(f"  {floor:.2f}    {survived:2d} of {len(NONSENSE)}             "
              f"{starved:2d} of {len(REAL)}                  {lost}")

    # Passage-to-passage: a 1,500-character query is a different distribution.
    print("\n  passage-to-passage (MIN_SIMILAR_PASSAGE_SCORE)")
    random.seed(1511)
    # chunk_id is the row index into the matrix (see dense_search).
    ids = random.sample(range(len(index.matrix)), 8)
    rows = index.get_chunks(ids)
    seconds, two_hundredths = [], []
    for cid in ids:
        row = rows.get(cid)
        if not row:
            continue
        text = row["text"]
        hits = index.search(text, encode_passage(text), limit=200, mode="semantic",
                            rerank=False, min_score=0.0, relative_floor=0.0)
        scores = [float(h.score) for h in hits if h.chunk_id != cid]
        if len(scores) >= 2:
            seconds.append(scores[0])
            two_hundredths.append(scores[min(len(scores), 199) - 1])
    if seconds:
        print(f"    best non-self  {min(seconds):.3f} - {max(seconds):.3f}")
        print(f"    200th          {min(two_hundredths):.3f} - {max(two_hundredths):.3f}")

    Path("floor_calibration.json").write_text(json.dumps(
        {"real": real, "nonsense": nonsense}, indent=1))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
