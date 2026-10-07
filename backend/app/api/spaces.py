from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request, Response
from app.core.security import (CurrentActor, current_actor, ensure_business_access,
                               require_csrf, require_idempotency_key)
from app.schemas.dto import CreateSpace
from app.services.space_service import SpaceService
router = APIRouter(prefix="/spaces", tags=["spaces"])

def env(request, data):
    return {"data": data, "request_id": str(request.state.request_id)}

def service(request):
    return SpaceService(request.app.state.resources)

def idempotent_response(request, response, current_service, data):
    if current_service.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return env(request, data)

@router.get("")
def list_spaces(request: Request, actor: Annotated[CurrentActor, Depends(current_actor)],
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                status: Literal["active", "disabled"] | None = None):
    ensure_business_access(actor)
    return env(request, service(request).list(actor, page, page_size, status))

@router.post("", status_code=201, dependencies=[Depends(require_csrf)])
def create_space(payload: CreateSpace, request: Request, response: Response,
                 actor: Annotated[CurrentActor, Depends(current_actor)],
                 idempotency_key: Annotated[str, Depends(require_idempotency_key)]):
    ensure_business_access(actor)
    current_service = service(request)
    data = current_service.create(actor, payload, request.state.request_id, idempotency_key)
    return idempotent_response(request, response, current_service, data)

@router.get("/{space_id}")
def get_space(space_id: UUID, request: Request,
              actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    return env(request, service(request).get(actor, space_id))

@router.get("/{space_id}/members")
def list_members(space_id: UUID, request: Request,
                 actor: Annotated[CurrentActor, Depends(current_actor)],
                 page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                 status: Literal["active", "removed"] | None = None):
    ensure_business_access(actor)
    return env(request, service(request).members(actor, space_id, page, page_size, status))

@router.put("/{space_id}/members/{user_id}", dependencies=[Depends(require_csrf)])
def put_member(space_id: UUID, user_id: UUID, request: Request, response: Response,
               actor: Annotated[CurrentActor, Depends(current_actor)],
               idempotency_key: Annotated[str, Depends(require_idempotency_key)]):
    ensure_business_access(actor)
    current_service = service(request)
    data = current_service.put_member(actor, space_id, user_id,
        request.state.request_id, idempotency_key)
    return idempotent_response(request, response, current_service, data)

@router.delete("/{space_id}/members/{user_id}", dependencies=[Depends(require_csrf)])
def remove_member(space_id: UUID, user_id: UUID, request: Request, response: Response,
                  actor: Annotated[CurrentActor, Depends(current_actor)],
                  idempotency_key: Annotated[str, Depends(require_idempotency_key)]):
    ensure_business_access(actor)
    current_service = service(request)
    data = current_service.remove_member(actor, space_id, user_id,
        request.state.request_id, idempotency_key)
    return idempotent_response(request, response, current_service, data)
