"""
Request bodies shared across routes.

There used to be two write paths for the same six columns: an untyped
`PATCH /api/books/{id}` taking a bare `dict`, and a typed
`PATCH /api/user/books/{id}` nothing called. One typed path remains.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

ReadingStatus = Literal["not_started", "in_progress", "finished", "abandoned"]


class UserFieldsUpdate(BaseModel):
    """
    The user-owned fields a client may write.

    Anything else in the body is rejected rather than silently dropped —
    `docs/API.md` claimed this endpoint "accepts any book field name", and it
    quietly ignored everything outside this set.
    """

    model_config = {"extra": "forbid"}

    reading_status: Optional[ReadingStatus] = None
    progress_percent: Optional[float] = Field(default=None, ge=0, le=100)
    # An EPUB CFI or a PDF page number, written by whichever reader has the
    # book open and interpreted by nothing else. Bounded so a runaway client
    # cannot park a megabyte in the row.
    reader_position: Optional[str] = Field(default=None, max_length=2000)
    user_rating: Optional[float] = Field(default=None, ge=0, le=5)
    user_tags: Optional[list[str]] = None
    favorite: Optional[bool] = None
    last_opened: Optional[str] = None

    def changed_fields(self) -> dict:
        """
        Only the fields the client actually sent.

        `exclude_unset` rather than `exclude_none`, so an explicit
        `{"user_rating": null}` still clears the rating instead of being
        dropped as "not provided".
        """
        return self.model_dump(exclude_unset=True)
