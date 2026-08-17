"""Filter facet routes – reactive facets scoped to current search + filters."""
from fastapi import APIRouter, Request

from .params import Filters

router = APIRouter(prefix="/api/filters", tags=["filters"])


@router.get("")
def get_all_filters(request: Request, filters: Filters):
    """
    Every facet dimension in one response.

    There were also six per-dimension endpoints here (`/categories`,
    `/themes`, `/authors`, `/languages`, `/years`, `/tags`). Nothing called
    them, and each ran the full `get_filter_facets()` — about seven aggregate
    queries — only to return a single key of the result.
    """
    return request.app.state.db.get_filter_facets(**filters.as_dict())
