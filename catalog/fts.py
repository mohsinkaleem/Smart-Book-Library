"""
The one FTS5 query builder.

There used to be two: a permissive one in `server/db.py` that passed user
input to `MATCH` almost untouched, and the strict one here. They drifted, and
the server used the unsafe one — `?search=self-help` and `?search=AND` both
returned 500 because FTS5 read the punctuation and the bare `AND` as operators.

Both the pipeline store and the web server now call this.
"""
import re

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def fts_query(query: str, prefix: bool = False) -> str:
    """
    Turn user input into a safe FTS5 MATCH expression.

    Every token is quoted, so `AND`, `-`, `*`, `"` and column filters like
    `title:` are treated as literal text rather than as operators the user did
    not mean to type (and cannot use to probe the index).

    With `prefix=True`, tokens longer than two characters also get FTS5's
    prefix operator, which is what autocomplete and the search box want.

    Returns `""` when the input holds no searchable token. Callers must treat
    that as "matches nothing" — an empty expression is a syntax error in
    FTS5, not a wildcard.
    """
    tokens = _TOKEN_RE.findall(query or "")
    if not tokens:
        return ""
    if prefix:
        return " ".join(f'"{t}"*' if len(t) > 2 else f'"{t}"' for t in tokens)
    return " ".join(f'"{t}"' for t in tokens)
