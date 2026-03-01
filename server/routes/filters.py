"""Filter facet routes – reactive facets scoped to current search + filters."""
from typing import Optional
from fastapi import APIRouter, Request, Query

router = APIRouter(prefix="/api/filters", tags=["filters"])


def _collect_filter_params(
    search: Optional[str] = None,
    file_type: Optional[str] = None,
    category: Optional[str] = None,
    theme: Optional[str] = None,
    language: Optional[str] = None,
    reading_status: Optional[str] = None,
    favorite: Optional[str] = None,
    has_cover: Optional[str] = None,
    has_description: Optional[str] = None,
    year_min: Optional[str] = None,
    year_max: Optional[str] = None,
    author: Optional[str] = None,
    tag: Optional[str] = None,
) -> dict:
    """Gather non-empty filter params into a dict."""
    params = {}
    if search:
        params["search"] = search
    if file_type:
        params["file_type"] = file_type
    if category:
        params["category"] = category
    if theme:
        params["theme"] = theme
    if language:
        params["language"] = language
    if reading_status:
        params["reading_status"] = reading_status
    if favorite and favorite.lower() in ("true", "1"):
        params["favorite"] = True
    if has_cover and has_cover.lower() in ("true", "1"):
        params["has_cover"] = True
    if has_description and has_description.lower() in ("true", "1"):
        params["has_description"] = True
    if year_min:
        params["year_min"] = year_min
    if year_max:
        params["year_max"] = year_max
    if author:
        params["author"] = author
    if tag:
        params["tag"] = tag
    return params


@router.get("")
def get_all_filters(
    request: Request,
    search: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    theme: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
    reading_status: Optional[str] = Query(None),
    favorite: Optional[str] = Query(None),
    has_cover: Optional[str] = Query(None),
    has_description: Optional[str] = Query(None),
    year_min: Optional[str] = Query(None),
    year_max: Optional[str] = Query(None),
    author: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
):
    params = _collect_filter_params(
        search=search, file_type=file_type, category=category,
        theme=theme, language=language, reading_status=reading_status,
        favorite=favorite, has_cover=has_cover, has_description=has_description,
        year_min=year_min, year_max=year_max, author=author, tag=tag,
    )
    return request.app.state.db.get_filter_facets(**params)


@router.get("/categories")
def get_categories(request: Request):
    facets = request.app.state.db.get_filter_facets()
    return facets["categories"]


@router.get("/themes")
def get_themes(request: Request):
    facets = request.app.state.db.get_filter_facets()
    return facets["themes"]


@router.get("/authors")
def get_authors(request: Request):
    facets = request.app.state.db.get_filter_facets()
    return facets["authors"]


@router.get("/languages")
def get_languages(request: Request):
    facets = request.app.state.db.get_filter_facets()
    return facets["languages"]


@router.get("/years")
def get_years(request: Request):
    facets = request.app.state.db.get_filter_facets()
    return facets["years"]


@router.get("/tags")
def get_tags(request: Request):
    facets = request.app.state.db.get_filter_facets()
    return facets["tags"]
