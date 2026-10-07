from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Request, Response
from app.api.dependencies import file_query
from app.core.security import (CurrentActor, current_actor, ensure_business_access,
                               require_csrf, require_idempotency_key)
from app.schemas.dto import FileQuery, PatchFile
from app.services.file_service import FileService
router = APIRouter(prefix="/files", tags=["files"])
recycle_router = APIRouter(prefix="/recycle-bin/files", tags=["files"])

def env(request, data):
    return {"data": data, "request_id": str(request.state.request_id)}

def service(request):
    return FileService(request.app.state.resources)

def idempotent_response(request, response, current_service, data):
    if current_service.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return env(request, data)

@router.get("")
def list_files(request: Request, actor: Annotated[CurrentActor, Depends(current_actor)],
               query: Annotated[FileQuery, Depends(file_query)]):
    ensure_business_access(actor)
    return env(request, service(request).list(actor, query))

@recycle_router.get("")
def recycle_bin(request: Request, actor: Annotated[CurrentActor, Depends(current_actor)],
                query: Annotated[FileQuery, Depends(file_query)]):
    ensure_business_access(actor)
    return env(request, service(request).list(actor, query, status="deleted"))

@router.get("/{file_id}")
def get_file(file_id: UUID, request: Request,
             actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    return env(request, service(request).get(actor, file_id, include_deleted=True))

@router.patch("/{file_id}", dependencies=[Depends(require_csrf)])
def patch_file(file_id: UUID, payload: PatchFile, request: Request, response: Response,
               actor: Annotated[CurrentActor, Depends(current_actor)],
               idempotency_key: Annotated[str, Depends(require_idempotency_key)]):
    ensure_business_access(actor)
    current_service = service(request)
    data = current_service.patch(actor, file_id, payload,
        request.state.request_id, idempotency_key)
    return idempotent_response(request, response, current_service, data)

@router.delete("/{file_id}", dependencies=[Depends(require_csrf)])
def delete_file(file_id: UUID, request: Request, response: Response,
                actor: Annotated[CurrentActor, Depends(current_actor)],
                idempotency_key: Annotated[str, Depends(require_idempotency_key)]):
    ensure_business_access(actor)
    current_service = service(request)
    data = current_service.delete(actor, file_id, request.state.request_id, idempotency_key)
    return idempotent_response(request, response, current_service, data)

@router.post("/{file_id}/restore", dependencies=[Depends(require_csrf)])
def restore_file(file_id: UUID, request: Request, response: Response,
                 actor: Annotated[CurrentActor, Depends(current_actor)],
                 idempotency_key: Annotated[str, Depends(require_idempotency_key)]):
    ensure_business_access(actor)
    current_service = service(request)
    data = current_service.restore(actor, file_id, request.state.request_id, idempotency_key)
    return idempotent_response(request, response, current_service, data)
