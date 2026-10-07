from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request, Response
from app.core.security import (CurrentActor, current_actor, ensure_business_access,
                               require_csrf, require_idempotency_key)
from app.schemas.dto import RestoreVersion
from app.services.version_service import VersionService
router = APIRouter(tags=["versions"])

def env(request, data):
    return {"data": data, "request_id": str(request.state.request_id)}

@router.get("/files/{file_id}/versions")
def list_versions(file_id: UUID, request: Request,
                  actor: Annotated[CurrentActor, Depends(current_actor)],
                  page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    ensure_business_access(actor)
    return env(request, VersionService(request.app.state.resources).list(actor, file_id, page, page_size))

@router.post("/files/{file_id}/versions/restore", status_code=201,
             dependencies=[Depends(require_csrf)])
def restore_version(file_id: UUID, payload: RestoreVersion, request: Request,
                    response: Response,
                    actor: Annotated[CurrentActor, Depends(current_actor)],
                    idempotency_key: Annotated[str, Depends(require_idempotency_key)]):
    ensure_business_access(actor)
    current_service = VersionService(request.app.state.resources)
    data = current_service.restore(actor, file_id, payload,
        request.state.request_id, idempotency_key)
    if current_service.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return env(request, data)

@router.get("/files/{file_id}/versions/{version_id}")
def get_version(file_id: UUID, version_id: UUID, request: Request,
                actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    return env(request, VersionService(request.app.state.resources).get(actor, file_id, version_id))
