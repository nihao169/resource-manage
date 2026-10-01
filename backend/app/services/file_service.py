from app.core.database import transaction
from app.core.errors import BusinessError
from app.repositories.audit_repository import AuditRepository
from app.repositories.file_repository import FileRepository

def render_version(row):
    return {"version_id": row["version_id"] if "version_id" in row else row["id"],
        "file_id": row["id"] if "version_id" in row else row["file_id"],
        "version_no": row["version_no"], "version_note": row["version_note"],
        "original_name": row["original_name"], "extension": row["extension"],
        "mime": row["mime"], "size": row["size"], "sha256": row["sha256"],
        "retained_until": row["retained_until"], "legal_hold": row["legal_hold"],
        "restored_from_version_id": row["restored_from_version_id"],
        "uploader": {"id": row["uploader_id"] if "uploader_id" in row else row["created_by"],
            "username": row["uploader_username"] if "uploader_username" in row else row["username"],
            "display_name": row["uploader_display_name"] if "uploader_display_name" in row else row["display_name"]},
        "created_at": row["version_created_at"] if "version_created_at" in row else row["created_at"]}

def render_file(row):
    deleted_by = None
    if row["deleted_by"]:
        deleted_by = {"id": row["deleted_by"], "username": row["deleted_username"],
            "display_name": row["deleted_display_name"]}
    return {"file_id": row["id"], "space_id": row["space_id"],
        "directory_id": row["directory_id"],
        "directory_path": "/" if row["directory_id"] is None else "/" + (row["directory_name"] or ""),
        "owner": {"id": row["owner_id"], "username": row["owner_username"],
            "display_name": row["owner_display_name"]}, "name": row["name"],
        "description": row["description"], "current_version": render_version(row),
        "status": row["status"], "tags": [], "metadata_values": [],
        "deleted_at": row["deleted_at"], "deleted_by": deleted_by,
        "created_at": row["created_at"], "updated_at": row["updated_at"]}

class FileService:
    def __init__(self, resources):
        self.engine = resources.engine
        self.files = FileRepository()
        self.audit = AuditRepository()

    def list(self, actor, query, *, status="active"):
        if status == "deleted" and query.owner_id not in (None, actor.user_id) and actor.role != "admin":
            raise BusinessError("FORBIDDEN", "只能查看自己的回收站", 403)
        with self.engine.connect() as connection:
            rows, total = self.files.list(connection, actor, status=status,
                space_id=query.space_id, directory_id=query.directory_id, root=query.root,
                owner_id=(actor.user_id if status == "deleted" and actor.role != "admin" else query.owner_id),
                uploader_id=query.uploader_id, mime=query.mime, extensions=query.extension,
                q=query.q, limit=query.page_size, offset=query.offset, sort=query.sort)
        return {"items": [render_file(row) for row in rows], "page": query.page,
            "page_size": query.page_size, "total": total}

    def get(self, actor, file_id, *, include_deleted=False):
        with self.engine.connect() as connection:
            row = self.files.visible(connection, actor, file_id, include_deleted=include_deleted)
        if not row:
            raise BusinessError("FILE_NOT_FOUND", "文件不存在", 404)
        if row["status"] == "deleted" and actor.role != "admin" and row["owner_id"] != actor.user_id:
            raise BusinessError("FILE_NOT_FOUND", "文件不存在", 404)
        return render_file(row)

    def _managed(self, actor, row):
        if actor.role != "admin" and row["owner_id"] != actor.user_id:
            raise BusinessError("FORBIDDEN", "无权管理该文件", 403)

    def patch(self, actor, file_id, payload, request_id):
        with transaction(self.engine) as connection:
            row = self.files.visible(connection, actor, file_id, for_update=True)
            if not row:
                raise BusinessError("FILE_NOT_FOUND", "文件不存在", 404)
            self._managed(actor, row)
            self.files.patch(connection, file_id, name=payload.name, description=payload.description)
            self.audit.append(connection, actor_id=actor.user_id, action="file.updated",
                target_type="file", target_id=file_id, request_id=request_id)
        return self.get(actor, file_id)

    def delete(self, actor, file_id, request_id):
        with transaction(self.engine) as connection:
            row = self.files.visible(connection, actor, file_id, include_deleted=True, for_update=True)
            if not row:
                raise BusinessError("FILE_NOT_FOUND", "文件不存在", 404)
            self._managed(actor, row)
            if row["status"] == "active":
                self.files.soft_delete(connection, file_id, actor.user_id)
                self.audit.append(connection, actor_id=actor.user_id, action="file.deleted",
                    target_type="file", target_id=file_id, request_id=request_id)
        return {"file_id": file_id, "status": "deleted"}

    def restore(self, actor, file_id, request_id):
        with transaction(self.engine) as connection:
            row = self.files.visible(connection, actor, file_id, include_deleted=True, for_update=True)
            if not row:
                raise BusinessError("FILE_NOT_FOUND", "文件不存在", 404)
            self._managed(actor, row)
            if row["status"] == "deleted":
                self.files.restore(connection, file_id)
                self.audit.append(connection, actor_id=actor.user_id, action="file.restored",
                    target_type="file", target_id=file_id, request_id=request_id)
        return self.get(actor, file_id)
