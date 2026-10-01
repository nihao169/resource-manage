from datetime import datetime, timezone
from sqlalchemy import text
from app.core.errors import BusinessError
from app.core.security import require_admin

class AdminService:
    def __init__(self, resources):
        self.resources = resources
        self.engine = resources.engine

    def settings(self, actor):
        require_admin(actor)
        with self.engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT key,value,value_type,updated_at FROM system_settings ORDER BY key"
            )).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def components(self, actor):
        require_admin(actor)
        checked = datetime.now(timezone.utc)
        items = [{"name": "api", "status": "healthy", "checked_at": checked,
            "latency_ms": 0, "error_code": None}]
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            items.append({"name": "postgres", "status": "healthy", "checked_at": checked,
                "latency_ms": None, "error_code": None})
        except Exception:
            items.append({"name": "postgres", "status": "unhealthy", "checked_at": checked,
                "latency_ms": None, "error_code": "DATABASE_UNAVAILABLE"})
        try:
            self.resources.storage.check_buckets()
            items.append({"name": "minio", "status": "healthy", "checked_at": checked,
                "latency_ms": None, "error_code": None})
        except Exception:
            items.append({"name": "minio", "status": "unhealthy", "checked_at": checked,
                "latency_ms": None, "error_code": "STORAGE_UNAVAILABLE"})
        return {"items": items}

    def backups(self, actor, page, page_size, status=None):
        require_admin(actor)
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT *,count(*) OVER() AS total FROM backup_runs
                 WHERE (:status IS NULL OR status=:status)
                 ORDER BY started_at DESC,id DESC LIMIT :limit OFFSET :offset
            """), {"status": status, "limit": page_size,
                "offset": (page-1)*page_size}).mappings().all()
        def render(row):
            public_artifacts = [{key: item[key] for key in ("name", "size", "sha256") if key in item}
                for item in row["artifacts"]]
            return {"backup_run_id": row["id"], "scope": row["scope"], "status": row["status"],
                "checkpoint": row["checkpoint"], "started_at": row["started_at"],
                "finished_at": row["finished_at"], "checksum": row["checksum"],
                "artifacts": public_artifacts, "error_code": row["error_code"]}
        return {"items": [render(row) for row in rows], "page": page, "page_size": page_size,
            "total": rows[0]["total"] if rows else 0}

    def backup(self, actor, backup_run_id):
        require_admin(actor)
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT * FROM backup_runs WHERE id=:id"),
                {"id": backup_run_id}).mappings().first()
        if not row:
            raise BusinessError("NOT_FOUND", "备份记录不存在", 404)
        public_artifacts = [{key: item[key] for key in ("name", "size", "sha256") if key in item}
            for item in row["artifacts"]]
        return {"backup_run_id": row["id"], "scope": row["scope"], "status": row["status"],
            "checkpoint": row["checkpoint"], "started_at": row["started_at"],
            "finished_at": row["finished_at"], "checksum": row["checksum"],
            "artifacts": public_artifacts, "error_code": row["error_code"]}

