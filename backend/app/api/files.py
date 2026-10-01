from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Request
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

@router.patch("/{file_id}",
              dependencies=[Depends(require_csrf), Depends(require_idempotency_key)])
def patch_file(file_id: UUID, payload: PatchFile, request: Request,
               actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    return env(request, service(request).patch(actor, file_id, payload, request.state.request_id))

@router.delete("/{file_id}",
               dependencies=[Depends(require_csrf), Depends(require_idempotency_key)])
def delete_file(file_id: UUID, request: Request,
                actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    return env(request, service(request).delete(actor, file_id, request.state.request_id))

@router.post("/{file_id}/restore",
             dependencies=[Depends(require_csrf), Depends(require_idempotency_key)])
def restore_file(file_id: UUID, request: Request,
                 actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    return env(request, service(request).restore(actor, file_id, request.state.request_id))
