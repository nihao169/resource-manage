from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request
from app.core.security import (CurrentActor, current_actor, ensure_business_access,
                               require_csrf, require_idempotency_key)
from app.schemas.dto import CreateSpace
from app.services.space_service import SpaceService
router = APIRouter(prefix="/spaces", tags=["spaces"])

def env(request, data):
    return {"data": data, "request_id": str(request.state.request_id)}

def service(request):
    return SpaceService(request.app.state.resources)

@router.get("")
def list_spaces(request: Request, actor: Annotated[CurrentActor, Depends(current_actor)],
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                status: Literal["active", "disabled"] | None = None):
    ensure_business_access(actor)
    return env(request, service(request).list(actor, page, page_size, status))

@router.post("", status_code=201,
             dependencies=[Depends(require_csrf), Depends(require_idempotency_key)])
def create_space(payload: CreateSpace, request: Request,
                 actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    return env(request, service(request).create(actor, payload, request.state.request_id))

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

@router.put("/{space_id}/members/{user_id}",
            dependencies=[Depends(require_csrf), Depends(require_idempotency_key)])
def put_member(space_id: UUID, user_id: UUID, request: Request,
               actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    return env(request, service(request).put_member(actor, space_id, user_id, request.state.request_id))

@router.delete("/{space_id}/members/{user_id}",
               dependencies=[Depends(require_csrf), Depends(require_idempotency_key)])
def remove_member(space_id: UUID, user_id: UUID, request: Request,
                  actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    return env(request, service(request).remove_member(actor, space_id, user_id, request.state.request_id))
