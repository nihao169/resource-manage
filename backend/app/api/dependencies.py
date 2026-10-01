from typing import Annotated, Literal
from uuid import UUID
from fastapi import Query
from app.schemas.dto import FileQuery

def file_query(
    space_id: UUID | None = None,
    directory_id: UUID | None = None,
    root: bool = False,
    owner_id: UUID | None = None,
    uploader_id: UUID | None = None,
    mime: Annotated[str | None, Query(max_length=127)] = None,
    extension: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    sort: Literal["updated_at_desc", "created_at_desc", "name_asc"] = "updated_at_desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> FileQuery:
    return FileQuery(space_id=space_id, directory_id=directory_id, root=root,
        owner_id=owner_id, uploader_id=uploader_id, mime=mime,
        extension=extension or [], q=q, sort=sort, page=page, page_size=page_size)
