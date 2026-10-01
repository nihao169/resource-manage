from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request
from app.core.security import CurrentActor, current_actor, ensure_business_access
from app.services.admin_service import AdminService
router = APIRouter(prefix="/admin", tags=["admin"])

def env(request, data):
    return {"data": data, "request_id": str(request.state.request_id)}

@router.get("/components")
def components(request: Request, actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    return env(request, AdminService(request.app.state.resources).components(actor))

@router.get("/settings")
def settings(request: Request, actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    return env(request, AdminService(request.app.state.resources).settings(actor))

@router.get("/backups")
def backups(request: Request, actor: Annotated[CurrentActor, Depends(current_actor)],
            page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
            status: Literal["running", "completed", "failed"] | None = None):
    ensure_business_access(actor)
    return env(request, AdminService(request.app.state.resources).backups(
        actor, page, page_size, status))

@router.get("/backups/{backup_run_id}")
def backup(backup_run_id: UUID, request: Request,
           actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    return env(request, AdminService(request.app.state.resources).backup(actor, backup_run_id))

