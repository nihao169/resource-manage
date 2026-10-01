from sqlalchemy.exc import IntegrityError
from app.core.database import transaction
from app.core.errors import BusinessError
from app.core.security import require_admin
from app.repositories.audit_repository import AuditRepository
from app.repositories.space_repository import SpaceRepository
from app.repositories.user_repository import UserRepository

class SpaceService:
    def __init__(self, resources):
        self.engine = resources.engine
        self.spaces = SpaceRepository()
        self.users = UserRepository()
        self.audit = AuditRepository()

    @staticmethod
    def render(row):
        return {"space_id": row["id"], "name": row["name"], "quota_bytes": row["quota_bytes"],
            "used_bytes": row["used_bytes"], "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def list(self, actor, page, page_size, status=None):
        if status is not None and actor.role != "admin":
            raise BusinessError("FORBIDDEN", "无权按空间状态筛选", 403)
        with self.engine.connect() as connection:
            rows, total = self.spaces.list(connection, actor, limit=page_size,
                offset=(page-1)*page_size, status=status)
        return {"items": [self.render(row) for row in rows], "page": page,
            "page_size": page_size, "total": total}

    def get(self, actor, space_id):
        with self.engine.connect() as connection:
            row = self.spaces.authorize(connection, actor, space_id)
        if not row:
            raise BusinessError("NOT_FOUND", "空间不存在", 404)
        return self.render(row)

    def create(self, actor, payload, request_id):
        require_admin(actor)
        try:
            with transaction(self.engine) as connection:
                row = self.spaces.create(connection, name=payload.name,
                    quota_bytes=payload.quota_bytes, actor_id=actor.user_id)
                self.audit.append(connection, actor_id=actor.user_id, action="space.created",
                    target_type="space", target_id=row["id"], request_id=request_id)
        except IntegrityError:
            raise BusinessError("NAME_CONFLICT", "空间名称已存在", 409) from None
        return self.render(row)

    def members(self, actor, space_id, page, page_size, status=None):
        require_admin(actor)
        with self.engine.connect() as connection:
            if not self.spaces.authorize(connection, actor, space_id):
                raise BusinessError("NOT_FOUND", "空间不存在", 404)
            rows, total = self.spaces.members(connection, space_id, limit=page_size,
                offset=(page-1)*page_size, status=status)
        items = [{"space_id": row["space_id"], "user": {"id": row["uid"],
            "username": row["username"], "display_name": row["display_name"]},
            "status": row["status"], "created_at": row["created_at"],
            "updated_at": row["updated_at"]} for row in rows]
        return {"items": items, "page": page, "page_size": page_size, "total": total}

    def put_member(self, actor, space_id, user_id, request_id):
        require_admin(actor)
        with transaction(self.engine) as connection:
            if not self.spaces.authorize(connection, actor, space_id) or not self.users.by_id(connection, user_id):
                raise BusinessError("NOT_FOUND", "空间或用户不存在", 404)
            row = self.spaces.put_member(connection, space_id, user_id)
            user = self.users.by_id(connection, user_id)
            self.audit.append(connection, actor_id=actor.user_id, action="space.member_added",
                target_type="space", target_id=space_id, request_id=request_id,
                detail={"user_id": str(user_id)})
        return {"space_id": space_id, "user": {"id": user["id"], "username": user["username"],
            "display_name": user["display_name"]}, "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def remove_member(self, actor, space_id, user_id, request_id):
        require_admin(actor)
        with transaction(self.engine) as connection:
            row = self.spaces.remove_member(connection, space_id, user_id)
            if not row:
                raise BusinessError("NOT_FOUND", "成员不存在", 404)
            self.audit.append(connection, actor_id=actor.user_id, action="space.member_removed",
                target_type="space", target_id=space_id, request_id=request_id,
                detail={"user_id": str(user_id)})
        return {"space_id": space_id, "user_id": user_id, "removed": True}
