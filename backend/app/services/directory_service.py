from uuid import uuid4
from sqlalchemy.exc import IntegrityError
from app.core.database import transaction
from app.core.errors import BusinessError
from app.core.security import require_admin
from app.repositories.audit_repository import AuditRepository
from app.repositories.directory_repository import DirectoryRepository
from app.repositories.space_repository import SpaceRepository

class DirectoryService:
    def __init__(self, resources):
        self.engine = resources.engine
        self.directories = DirectoryRepository()
        self.spaces = SpaceRepository()
        self.audit = AuditRepository()

    @staticmethod
    def render(row):
        return {"directory_id": row["id"], "space_id": row["space_id"],
            "parent_id": row["parent_id"], "name": row["name"],
            "display_path": row.get("display_path") or row["path_key"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def list(self, actor, space_id, parent_id, page, page_size, tree=False):
        with self.engine.connect() as connection:
            if not self.spaces.authorize(connection, actor, space_id):
                raise BusinessError("NOT_FOUND", "空间不存在", 404)
            rows, total = self.directories.list(connection, space_id, parent_id,
                limit=10000 if tree else page_size, offset=0 if tree else (page-1)*page_size,
                tree=tree)
        items = [self.render(row) for row in rows]
        return {"items": items} if tree else {"items": items, "page": page,
            "page_size": page_size, "total": total}

    def get(self, actor, directory_id):
        with self.engine.connect() as connection:
            row = self.directories.by_id(connection, directory_id)
            if not row or not self.spaces.authorize(connection, actor, row["space_id"]):
                raise BusinessError("NOT_FOUND", "目录不存在", 404)
        return self.render(row)

    def create(self, actor, payload, request_id):
        require_admin(actor)
        try:
            with transaction(self.engine) as connection:
                if not self.spaces.authorize(connection, actor, payload.space_id, write=True):
                    raise BusinessError("NOT_FOUND", "空间不存在", 404)
                parent_path = "/"
                if payload.parent_id:
                    parent = self.directories.by_id(connection, payload.parent_id, for_update=True)
                    if not parent or parent["space_id"] != payload.space_id:
                        raise BusinessError("NOT_FOUND", "父目录不存在", 404)
                    parent_path = parent["path_key"]
                row = self.directories.create(connection, directory_id=uuid4(),
                    space_id=payload.space_id, parent_id=payload.parent_id, name=payload.name,
                    actor_id=actor.user_id, parent_path=parent_path)
                self.audit.append(connection, actor_id=actor.user_id, action="directory.created",
                    target_type="directory", target_id=row["id"], request_id=request_id)
        except IntegrityError:
            raise BusinessError("NAME_CONFLICT", "同级目录名称已存在", 409) from None
        return self.render(row)

    def rename(self, actor, directory_id, name, request_id):
        require_admin(actor)
        try:
            with transaction(self.engine) as connection:
                row = self.directories.by_id(connection, directory_id, for_update=True)
                if not row:
                    raise BusinessError("NOT_FOUND", "目录不存在", 404)
                row = self.directories.rename(connection, directory_id, name)
                self.audit.append(connection, actor_id=actor.user_id, action="directory.renamed",
                    target_type="directory", target_id=directory_id, request_id=request_id)
        except IntegrityError:
            raise BusinessError("NAME_CONFLICT", "同级目录名称已存在", 409) from None
        return self.render(row)
