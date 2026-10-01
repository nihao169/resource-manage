"""Database half of the B/C upload, download and cleanup contract.

Every method uses the caller's pinned connection and deliberately never commits it.
"""
from datetime import datetime, timezone
import json
from pathlib import PurePath
from uuid import UUID, uuid4
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from fastapi.encoders import jsonable_encoder

from app.core.errors import BusinessError
from app.repositories.content_object_repository import ContentObjectRepository
from app.repositories.file_repository import FILE_SELECT, FileRepository
from app.repositories.space_repository import SpaceRepository
from app.repositories.upload_repository import UploadRepository
from app.services.contracts import ActorSession, VerifiedContent
from app.services.file_service import render_file, render_version

def _value(source, name, default=None):
    return source.get(name, default) if isinstance(source, dict) else getattr(source, name, default)

class DatabaseContractService:
    def __init__(self):
        self.spaces = SpaceRepository()
        self.uploads = UploadRepository()
        self.objects = ContentObjectRepository()
        self.files = FileRepository()

    def _actor_row(self, connection, actor: ActorSession):
        row = connection.execute(text("""
            SELECT u.*,s.revoked_at,s.expires_at FROM users u
              JOIN refresh_sessions s ON s.user_id=u.id
             WHERE u.id=:user AND s.id=:session
        """), {"user": actor.user_id, "session": actor.session_id}).mappings().first()
        if not row or row["status"] != "active" or row["revoked_at"] is not None \
                or row["expires_at"] <= datetime.now(timezone.utc):
            raise BusinessError("UNAUTHENTICATED", "会话已失效", 401)
        return row

    def authorize_upload(self, connection, actor: ActorSession, payload):
        user = self._actor_row(connection, actor)
        actor_view = type("Actor", (), {"user_id": actor.user_id, "role": user["role"]})()
        space_id = _value(payload, "space_id")
        space = self.spaces.authorize(connection, actor_view, space_id, write=True)
        if not space:
            raise BusinessError("NOT_FOUND", "空间不存在", 404)
        directory_id = _value(payload, "directory_id")
        if directory_id and not connection.execute(text("""
            SELECT 1 FROM directories WHERE id=:id AND space_id=:space AND status='active'
        """), {"id": directory_id, "space": space_id}).scalar():
            raise BusinessError("NOT_FOUND", "目录不存在", 404)
        target = _value(payload, "target_file_id")
        if target:
            file_row = connection.execute(text("""
                SELECT * FROM files WHERE id=:id AND space_id=:space AND status='active'
            """), {"id": target, "space": space_id}).mappings().first()
            if not file_row:
                raise BusinessError("FILE_NOT_FOUND", "目标文件不存在", 404)
            if user["role"] != "admin" and file_row["owner_id"] != actor.user_id:
                raise BusinessError("FORBIDDEN", "无权发布该文件的新版本", 403)
        max_bytes = int(connection.execute(text(
            "SELECT value #>> '{}' FROM system_settings WHERE key='max_file_bytes'"
        )).scalar_one())
        size = _value(payload, "expected_size")
        if size > max_bytes:
            raise BusinessError("FILE_TOO_LARGE", "文件超过系统限制", 413,
                {"max_file_bytes": max_bytes})
        return {"space_id": space_id, "directory_id": directory_id,
            "target_file_id": target, "available_bytes": space["quota_bytes"] - space["used_bytes"]}

    def create_upload_record(self, connection, actor: ActorSession, payload):
        self.authorize_upload(connection, actor, payload)
        size = _value(payload, "expected_size")
        setting = connection.execute(text("""
            SELECT key,value #>> '{}' AS value FROM system_settings
             WHERE key IN ('multipart_threshold_bytes','part_size_bytes')
        """)).mappings().all()
        config = {row["key"]: int(row["value"]) for row in setting}
        part_size = _value(payload, "part_size", config["part_size_bytes"])
        part_count = max(1, (size + part_size - 1) // part_size)
        values = {"user_id": actor.user_id, "space_id": _value(payload, "space_id"),
            "directory_id": _value(payload, "directory_id"),
            "target_file_id": _value(payload, "target_file_id"),
            "mode": "new_version" if _value(payload, "target_file_id") else "new_file",
            "original_name": _value(payload, "original_name"),
            "description": _value(payload, "description", ""),
            "version_note": _value(payload, "version_note", ""),
            "tag_ids": _value(payload, "tag_ids", []),
            "metadata_values": _value(payload, "metadata_values", []),
            "expected_size": size, "expected_sha256": _value(payload, "expected_sha256"),
            "mime": _value(payload, "mime"),
            "storage_method": "multipart" if size > config["multipart_threshold_bytes"] else "single",
            "part_size": part_size, "part_count": part_count,
            "temp_object_key": _value(payload, "temp_object_key", f"sessions/{uuid4()}"),
            "idempotency_key": _value(payload, "idempotency_key"),
            "request_hash": _value(payload, "request_hash"), "batch_id": _value(payload, "batch_id")}
        return self.uploads.create(connection, values)

    def confirm_part(self, connection, upload_id: UUID, part):
        upload = self.uploads.by_id(connection, upload_id, for_update=True)
        if not upload:
            raise BusinessError("UPLOAD_NOT_FOUND", "上传会话不存在", 404)
        if upload["status"] == "committed":
            raise BusinessError("UPLOAD_ALREADY_COMMITTED", "上传已经提交", 409)
        if upload["expires_at"] <= datetime.now(timezone.utc):
            raise BusinessError("UPLOAD_EXPIRED", "上传会话已过期", 410)
        try:
            result = self.uploads.confirm_part(connection, upload_id,
                part_no=_value(part, "part_no"), size=_value(part, "size"),
                etag=_value(part, "etag"), checksum=_value(part, "checksum"))
        except IntegrityError:
            raise BusinessError("PART_MISMATCH", "分片与已确认记录不一致", 409) from None
        connection.execute(text("UPDATE uploads SET status='uploading' WHERE id=:id AND status='created'"),
            {"id": upload_id})
        confirmed = connection.execute(text(
            "SELECT count(*) FROM upload_parts WHERE upload_id=:id AND status='confirmed'"),
            {"id": upload_id}).scalar_one()
        return {"part": result, "complete": confirmed == upload["part_count"]}

    def get_upload_resume(self, connection, actor: ActorSession, upload_id: UUID):
        self._actor_row(connection, actor)
        upload = self.uploads.by_id(connection, upload_id)
        if not upload or (upload["user_id"] != actor.user_id):
            raise BusinessError("UPLOAD_NOT_FOUND", "上传会话不存在", 404)
        parts = self.uploads.parts(connection, upload_id)
        return {"upload": upload, "confirmed_parts": parts,
            "confirmed_bytes": sum(row["size"] for row in parts)}

    def prepare_content_record(self, connection, content):
        return self.objects.prepare(connection, sha256=_value(content, "sha256"),
            size=_value(content, "size"), object_key=_value(content, "object_key"),
            producer_upload_id=_value(content, "producer_upload_id"))

    def mark_object_ready(self, connection, content: VerifiedContent):
        row = self.objects.mark_ready(connection, content.object_id,
            sha256=content.sha256, size=content.size)
        if not row:
            raise BusinessError("CONSISTENCY_ERROR", "内容对象状态不一致", 409)
        return row

    def commit_upload(self, connection, actor: ActorSession, upload_id: UUID,
                      content: VerifiedContent, idempotency_id: UUID, request_id: UUID):
        user = self._actor_row(connection, actor)
        upload = self.uploads.by_id(connection, upload_id, for_update=True)
        if not upload or upload["user_id"] != actor.user_id:
            raise BusinessError("UPLOAD_NOT_FOUND", "上传会话不存在", 404)
        if upload["status"] == "committed":
            return upload["result_snapshot"]
        if upload["expires_at"] <= datetime.now(timezone.utc):
            raise BusinessError("UPLOAD_EXPIRED", "上传会话已过期", 410)
        obj = self.objects.by_id(connection, content.object_id, for_update=True)
        if not obj or obj["status"] != "ready" or obj["size"] != content.size or obj["sha256"] != content.sha256:
            raise BusinessError("CONSISTENCY_ERROR", "内容对象尚未就绪", 409)
        space = connection.execute(text("SELECT * FROM spaces WHERE id=:id FOR UPDATE"),
            {"id": upload["space_id"]}).mappings().one()
        if space["status"] != "active":
            raise BusinessError("FORBIDDEN", "空间当前不可写", 403)
        available = space["quota_bytes"] - space["used_bytes"]
        if available < content.size:
            raise BusinessError("QUOTA_EXCEEDED", "空间剩余配额不足", 409,
                {"required_bytes": content.size, "available_bytes": available})
        if upload["mode"] == "new_file":
            file_id, version_no = uuid4(), 1
            connection.execute(text("""
                INSERT INTO files(id,space_id,directory_id,owner_id,name,description,creation_request_id)
                VALUES (:id,:space,:directory,:owner,:name,:description,:request)
            """), {"id": file_id, "space": upload["space_id"], "directory": upload["directory_id"],
                "owner": actor.user_id, "name": upload["original_name"],
                "description": upload["description"], "request": idempotency_id})
        else:
            file_id = upload["target_file_id"]
            target = connection.execute(text("SELECT * FROM files WHERE id=:id FOR UPDATE"),
                {"id": file_id}).mappings().first()
            if not target or target["status"] != "active" or target["space_id"] != upload["space_id"]:
                raise BusinessError("FILE_NOT_FOUND", "目标文件不存在", 404)
            if user["role"] != "admin" and target["owner_id"] != actor.user_id:
                raise BusinessError("FORBIDDEN", "无权发布该文件的新版本", 403)
            version_no = connection.execute(text(
                "SELECT COALESCE(max(version_no),0)+1 FROM file_versions WHERE file_id=:id"),
                {"id": file_id}).scalar_one()
        version_id = uuid4()
        extension = PurePath(upload["original_name"]).suffix.lower().lstrip(".")[:32]
        connection.execute(text("""
            INSERT INTO file_versions(id,file_id,version_no,version_note,original_name,extension,
              content_object_id,size,sha256,mime,created_by,creation_request_id)
            VALUES (:id,:file,:number,:note,:name,:extension,:object,:size,:sha,:mime,:actor,:request)
        """), {"id": version_id, "file": file_id, "number": version_no,
            "note": upload["version_note"], "name": upload["original_name"], "extension": extension,
            "object": obj["id"], "size": content.size, "sha": content.sha256,
            "mime": content.mime, "actor": actor.user_id, "request": idempotency_id})
        connection.execute(text("UPDATE files SET current_version_id=:version WHERE id=:file"),
            {"version": version_id, "file": file_id})
        connection.execute(text("UPDATE content_objects SET reference_count=reference_count+1 WHERE id=:id"),
            {"id": obj["id"]})
        connection.execute(text("UPDATE spaces SET used_bytes=used_bytes+:size WHERE id=:id"),
            {"id": upload["space_id"], "size": content.size})
        row = connection.execute(text(FILE_SELECT + " WHERE f.id=:id"), {"id": file_id}).mappings().one()
        result = {"upload_id": upload_id, "file": render_file(row), "version": render_version(row)}
        snapshot = jsonable_encoder(result)
        connection.execute(text("""
            UPDATE uploads SET status='committed',checkpoint='committed',result_file_id=:file,
              result_version_id=:version,result_snapshot=CAST(:snapshot AS jsonb) WHERE id=:upload
        """), {"file": file_id, "version": version_id,
            "snapshot": json.dumps(snapshot, ensure_ascii=False), "upload": upload_id})
        connection.execute(text("""
            UPDATE idempotency_requests SET status='completed',http_status=200,
              response_data=CAST(:data AS jsonb),
              result_target_type='file',result_target_id=:file,completed_at=now() WHERE id=:id
        """), {"data": json.dumps(snapshot, ensure_ascii=False), "file": file_id,
            "id": idempotency_id})
        connection.execute(text("""
            INSERT INTO audit_events(actor_id,action,target_type,target_id,request_id,result,detail)
            VALUES (:actor,'upload.committed','file',:file,:request,'success',CAST(:detail AS jsonb))
        """), {"actor": actor.user_id, "file": file_id, "request": request_id,
            "detail": json.dumps({"upload_id": str(upload_id), "version_id": str(version_id)})})
        return result

    def authorize_download(self, connection, actor: ActorSession, file_id: UUID, version_id: UUID):
        user = self._actor_row(connection, actor)
        row = connection.execute(text("""
            SELECT f.status AS file_status,f.space_id,v.*,o.bucket,o.object_key,o.status AS object_status
              FROM files f JOIN file_versions v ON v.file_id=f.id
              JOIN content_objects o ON o.id=v.content_object_id
             WHERE f.id=:file AND v.id=:version AND
               (:admin OR EXISTS(SELECT 1 FROM space_members sm WHERE sm.space_id=f.space_id
                 AND sm.user_id=:user AND sm.status='active'))
        """), {"file": file_id, "version": version_id, "admin": user["role"] == "admin",
            "user": actor.user_id}).mappings().first()
        if not row or row["file_status"] != "active" or row["object_status"] != "ready":
            raise BusinessError("VERSION_NOT_FOUND", "版本不存在", 404)
        return row

    def detach_file(self, connection, actor: ActorSession, file_id: UUID, confirmation):
        self._actor_row(connection, actor)
        file_row = connection.execute(text("SELECT * FROM files WHERE id=:id FOR UPDATE"),
            {"id": file_id}).mappings().first()
        if not file_row or file_row["status"] != "deleted":
            raise BusinessError("FILE_NOT_FOUND", "待清理文件不存在", 404)
        versions = connection.execute(text("""
            SELECT v.*,o.bucket,o.object_key,o.reference_count FROM file_versions v
              JOIN content_objects o ON o.id=v.content_object_id WHERE v.file_id=:id
        """), {"id": file_id}).mappings().all()
        if any(row["legal_hold"] or (row["retained_until"] and row["retained_until"] > datetime.now(timezone.utc))
               for row in versions):
            raise BusinessError("RETENTION_BLOCKED", "文件仍处于保留期", 409)
        attempt_id = uuid4()
        connection.execute(text("""
            INSERT INTO cleanup_attempts(id,file_id,space_id,file_name,requested_by,confirmation_id,status)
            VALUES (:id,:file,:space,:name,:actor,:confirmation,'running')
        """), {"id": attempt_id, "file": file_id, "space": file_row["space_id"],
            "name": file_row["name"], "actor": actor.user_id, "confirmation": _value(confirmation, "id")})
        grouped = {}
        for row in versions:
            grouped.setdefault(row["content_object_id"], {"row": row, "count": 0})["count"] += 1
        for object_id, item in grouped.items():
            row, count = item["row"], item["count"]
            status = "shared" if row["reference_count"] > count else "pending"
            connection.execute(text("""
                INSERT INTO cleanup_items(attempt_id,content_object_id,bucket,object_key,sha256,size,
                  detached_references,status) VALUES (:attempt,:object,:bucket,:key,:sha,:size,:count,:status)
            """), {"attempt": attempt_id, "object": object_id, "bucket": row["bucket"],
                "key": row["object_key"], "sha": row["sha256"], "size": row["size"],
                "count": count, "status": status})
            connection.execute(text("""
                UPDATE content_objects SET reference_count=reference_count-:count,
                  status=CASE WHEN reference_count=:count THEN 'deleting' ELSE status END WHERE id=:id
            """), {"count": count, "id": object_id})
        detached_bytes = sum(row["size"] for row in versions)
        connection.execute(text("UPDATE files SET current_version_id=NULL WHERE id=:id"), {"id": file_id})
        connection.execute(text("DELETE FROM file_versions WHERE file_id=:id"), {"id": file_id})
        connection.execute(text("DELETE FROM files WHERE id=:id"), {"id": file_id})
        connection.execute(text("UPDATE spaces SET used_bytes=used_bytes-:size WHERE id=:id"),
            {"size": detached_bytes, "id": file_row["space_id"]})
        connection.execute(text("""
            UPDATE cleanup_attempts SET checkpoint='detached',detached_bytes=:size WHERE id=:id
        """), {"size": detached_bytes, "id": attempt_id})
        return {"attempt_id": attempt_id, "items": len(grouped), "detached_bytes": detached_bytes}

    def finalize_cleanup_item(self, connection, attempt_id: UUID, item):
        item_id, deleted = _value(item, "id"), _value(item, "deleted", False)
        row = connection.execute(text("SELECT * FROM cleanup_items WHERE id=:id AND attempt_id=:attempt FOR UPDATE"),
            {"id": item_id, "attempt": attempt_id}).mappings().first()
        if not row:
            raise BusinessError("NOT_FOUND", "清理项不存在", 404)
        status = "deleted" if deleted else "failed"
        if deleted:
            connection.execute(text("DELETE FROM content_objects WHERE id=:id AND reference_count=0 AND status='deleting'"),
                {"id": row["content_object_id"]})
        connection.execute(text("UPDATE cleanup_items SET status=:status,last_error_code=:error WHERE id=:id"),
            {"status": status, "error": _value(item, "error_code"), "id": item_id})
        remaining = connection.execute(text("""
            SELECT count(*) FROM cleanup_items WHERE attempt_id=:id AND status NOT IN ('shared','deleted')
        """), {"id": attempt_id}).scalar_one()
        if remaining == 0:
            connection.execute(text("""
                UPDATE cleanup_attempts SET status='completed',checkpoint='completed',finished_at=now()
                 WHERE id=:id
            """), {"id": attempt_id})
        return {"item_id": item_id, "status": status, "remaining": remaining}
