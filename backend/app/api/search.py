from typing import Annotated
from fastapi import APIRouter, Depends, Request
from app.api.dependencies import file_query
from app.core.security import CurrentActor, current_actor, ensure_business_access
from app.schemas.dto import FileQuery
from app.services.search_service import SearchService
router = APIRouter(prefix="/search", tags=["search"])

@router.get("")
def search(request: Request, actor: Annotated[CurrentActor, Depends(current_actor)],
           query: Annotated[FileQuery, Depends(file_query)]):
    ensure_business_access(actor)
    if not query.q:
        from app.core.errors import BusinessError
        raise BusinessError("VALIDATION_ERROR", "搜索关键词不能为空", 422)
    data = SearchService(request.app.state.resources).search(actor, query)
    return {"data": data, "request_id": str(request.state.request_id)}

