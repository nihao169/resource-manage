from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request, Response
from app.core.security import (CurrentActor, current_actor, ensure_business_access,
                               require_csrf, require_idempotency_key)
from app.schemas.dto import CreateDirectory, PatchDirectory
from app.services.directory_service import DirectoryService
router = APIRouter(prefix="/directories", tags=["directories"])

def env(request, data):
    return {"data": data, "request_id": str(request.state.request_id)}

def service(request):
    return DirectoryService(request.app.state.resources)

def idempotent_response(request, response, current_service, data):
    if current_service.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return env(request, data)

@router.get("")
def list_directories(request: Request, space_id: UUID,
                     actor: Annotated[CurrentActor, Depends(current_actor)],
                     parent_id: UUID | None = None, page: int = Query(1, ge=1),
                     page_size: int = Query(50, ge=1, le=200)):
    ensure_business_access(actor)
    return env(request, service(request).list(actor, space_id, parent_id, page, page_size))

@router.get("/tree")
def directory_tree(request: Request, space_id: UUID,
                   actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    return env(request, service(request).list(actor, space_id, None, 1, 10000, tree=True))

@router.post("", status_code=201, dependencies=[Depends(require_csrf)])
def create_directory(payload: CreateDirectory, request: Request, response: Response,
                     actor: Annotated[CurrentActor, Depends(current_actor)],
                     idempotency_key: Annotated[str, Depends(require_idempotency_key)]):
    ensure_business_access(actor)
    current_service = service(request)
    data = current_service.create(actor, payload, request.state.request_id, idempotency_key)
    return idempotent_response(request, response, current_service, data)

@router.get("/{directory_id}")
def get_directory(directory_id: UUID, request: Request,
                  actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    return env(request, service(request).get(actor, directory_id))

@router.patch("/{directory_id}", dependencies=[Depends(require_csrf)])
def patch_directory(directory_id: UUID, payload: PatchDirectory, request: Request,
                    response: Response,
                    actor: Annotated[CurrentActor, Depends(current_actor)],
                    idempotency_key: Annotated[str, Depends(require_idempotency_key)]):
    ensure_business_access(actor)
    current_service = service(request)
    data = current_service.rename(actor, directory_id, payload.name,
        request.state.request_id, idempotency_key)
    return idempotent_response(request, response, current_service, data)
