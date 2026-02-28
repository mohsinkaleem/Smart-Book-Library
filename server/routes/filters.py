"""Filter facet routes."""
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/filters", tags=["filters"])


@router.get("")
def get_all_filters(request: Request):
    return request.app.state.db.get_filter_facets()


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
