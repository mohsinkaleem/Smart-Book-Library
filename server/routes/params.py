"""
One declaration of the book filter query parameters.

`books.list_books`, `search.search_books` and `filters.get_all_filters` each
re-declared the same ~14 optional parameters, with types that had drifted
apart: `favorite` was `bool` in two of them and `str` in the third, and
`year_min`/`year_max` were `str` on the filters endpoint — which is why
`GET /api/filters?year_min=abc` reached `int()` in the DB layer and 500'd
instead of being rejected as a 422.
"""
from dataclasses import asdict, dataclass
from typing import Annotated, Optional

from fastapi import Depends, Query


@dataclass(frozen=True)
class BookFilters:
    """The filter set shared by list, search and facet endpoints."""

    search: Optional[str] = None
    file_type: Optional[str] = None
    category: Optional[str] = None
    theme: Optional[str] = None
    language: Optional[str] = None
    reading_status: Optional[str] = None
    favorite: Optional[bool] = None
    has_cover: Optional[bool] = None
    has_description: Optional[bool] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    rating_min: Optional[int] = None
    author: Optional[str] = None
    tag: Optional[str] = None

    def as_dict(self, include_search: bool = True) -> dict:
        """Non-empty filters only, ready to splat into the DB layer."""
        out = {k: v for k, v in asdict(self).items() if v is not None and v != ""}
        if not include_search:
            out.pop("search", None)
        return out


def book_filters(
    search: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    theme: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
    reading_status: Optional[str] = Query(None),
    favorite: Optional[bool] = Query(None),
    has_cover: Optional[bool] = Query(None),
    has_description: Optional[bool] = Query(None),
    year_min: Optional[int] = Query(None),
    year_max: Optional[int] = Query(None),
    rating_min: Optional[int] = Query(None),
    author: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
) -> BookFilters:
    return BookFilters(
        search=search, file_type=file_type, category=category, theme=theme,
        language=language, reading_status=reading_status, favorite=favorite,
        has_cover=has_cover, has_description=has_description,
        year_min=year_min, year_max=year_max, rating_min=rating_min,
        author=author, tag=tag,
    )


Filters = Annotated[BookFilters, Depends(book_filters)]
