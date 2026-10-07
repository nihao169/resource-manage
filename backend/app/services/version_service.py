from uuid import uuid4
from sqlalchemy import text
from app.core.errors import BusinessError
from app.repositories.audit_repository import AuditRepository
from app.repositories.file_repository import FileRepository
from app.repositories.idempotency_repository import IdempotencyRepository
from app.services.file_service import FileService, render_file, render_version

class VersionService:
    def __init__(self, resources):
        self.resources = resources
        self.engine = resources.engine
        self.files = FileRepository()
        self.audit = AuditRepository()
        self.idempotency = IdempotencyRepository()
        self.replayed = False

    def list(self, actor, file_id, page, page_size):
        FileService(self.resources).get(actor, file_id)
        with self.engine.connect() as connection:
            rows, total = self.files.versions(connection, file_id, limit=page_size,
                offset=(page-1)*page_size)
        return {"items": [render_version(row) for row in rows], "page": page,
            "page_size": page_size, "total": total}

    def get(self, actor, file_id, version_id):
        FileService(self.resources).get(actor, file_id)
        with self.engine.connect() as connection:
            row = self.files.version(connection, file_id, version_id)
        if not row:
            raise BusinessError("VERSION_NOT_FOUND", "版本不存在", 404)
        return render_version(row)

    def restore(self, actor, file_id, payload, request_id, idempotency_key):
        path = f"/api/files/{file_id}/versions/restore"
        with self.idempotency.locked_transaction(
                self.engine, actor.user_id, idempotency_key) as connection:
            file_row = self.files.visible(connection, actor, file_id, for_update=True)
            if not file_row:
                raise BusinessError("FILE_NOT_FOUND", "文件不存在", 404)
            if actor.role != "admin" and file_row["owner_id"] != actor.user_id:
                raise BusinessError("FORBIDDEN", "无权管理该文件", 403)
            claim = self.idempotency.claim(connection, actor_id=actor.user_id,
                key=idempotency_key, method="POST", path=path, payload=payload)
            if claim.replayed:
                self.replayed = True
                return claim.response_data
            if payload.expected_current_version_id and file_row["current_version_id"] != payload.expected_current_version_id:
                raise BusinessError("VERSION_CONFLICT", "当前版本已变化", 409)
            source = connection.execute(text("""
                SELECT v.*,o.status AS object_status FROM file_versions v
                  JOIN content_objects o ON o.id=v.content_object_id
                 WHERE v.file_id=:file AND v.id=:source FOR UPDATE OF o
            """), {"file": file_id, "source": payload.source_version_id}).mappings().first()
            if not source or source["object_status"] != "ready":
                raise BusinessError("VERSION_NOT_FOUND", "来源版本不存在", 404)
            space = connection.execute(text("SELECT * FROM spaces WHERE id=:id FOR UPDATE"),
                {"id": file_row["space_id"]}).mappings().one()
            available = space["quota_bytes"] - space["used_bytes"]
            if available < source["size"]:
                raise BusinessError("QUOTA_EXCEEDED", "空间剩余配额不足", 409,
                    {"required_bytes": source["size"], "available_bytes": available})
            version_id = uuid4()
            version_no = connection.execute(text(
                "SELECT COALESCE(max(version_no),0)+1 FROM file_versions WHERE file_id=:id"),
                {"id": file_id}).scalar_one()
            connection.execute(text("""
                INSERT INTO file_versions(id,file_id,version_no,version_note,original_name,extension,
                  content_object_id,size,sha256,mime,restored_from_version_id,created_by)
                VALUES (:id,:file,:no,:note,:name,:extension,:object,:size,:sha,:mime,:source,:actor)
            """), {"id": version_id, "file": file_id, "no": version_no,
                "note": payload.version_note, "name": source["original_name"],
                "extension": source["extension"], "object": source["content_object_id"],
                "size": source["size"], "sha": source["sha256"], "mime": source["mime"],
                "source": source["id"], "actor": actor.user_id})
            connection.execute(text("UPDATE content_objects SET reference_count=reference_count+1 WHERE id=:id"),
                {"id": source["content_object_id"]})
            connection.execute(text("UPDATE spaces SET used_bytes=used_bytes+:size WHERE id=:id"),
                {"id": file_row["space_id"], "size": source["size"]})
            connection.execute(text("UPDATE files SET current_version_id=:version WHERE id=:file"),
                {"version": version_id, "file": file_id})
            self.audit.append(connection, actor_id=actor.user_id, action="version.restored",
                target_type="file", target_id=file_id, request_id=request_id,
                detail={"source_version_id": str(source["id"]), "version_id": str(version_id)})
            file_data = render_file(self.files.visible(connection, actor, file_id))
            version_data = render_version(self.files.version(connection, file_id, version_id))
            data = {"upload_id": None, "file": file_data, "version": version_data}
            self.idempotency.complete(connection, claim, data, http_status=201,
                target_type="file", target_id=file_id)
        return data

