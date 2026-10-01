from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request
from app.core.security import CurrentActor, current_actor, ensure_business_access, require_admin
from app.repositories.audit_repository import AuditRepository
router = APIRouter(prefix="/audit", tags=["audit"])

@router.get("")
def audit(request: Request, actor: Annotated[CurrentActor, Depends(current_actor)],
          page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
          actor_id: UUID | None = None, action: str | None = Query(None, max_length=64),
          target_type: str | None = Query(None, max_length=32), target_id: UUID | None = None,
          result: Literal["success", "denied", "failed"] | None = None):
    ensure_business_access(actor)
    require_admin(actor)
    with request.app.state.resources.engine.connect() as connection:
        rows, total = AuditRepository().list(connection, limit=page_size,
            offset=(page-1)*page_size, actor_id=actor_id, action=action,
            target_type=target_type, target_id=target_id, result=result)
    items = [{"event_id": row["id"], "actor": None if row["actor_id"] is None else
        {"id": row["actor_id"], "username": row["username"], "display_name": row["display_name"]},
        "action": row["action"], "target_type": row["target_type"], "target_id": row["target_id"],
        "request_id": row["request_id"], "result": row["result"], "detail": row["detail"],
        "created_at": row["created_at"]} for row in rows]
    return {"data": {"items": items, "page": page, "page_size": page_size, "total": total},
        "request_id": str(request.state.request_id)}

