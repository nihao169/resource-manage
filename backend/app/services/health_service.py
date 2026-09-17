"""B+C: readiness is genuine, bounded and sanitized."""
from app.core.database import check_database
from app.core.errors import BusinessError

class HealthService:
    def __init__(self, resources):
        self.resources = resources

    def ready(self):
        try:
            check_database(self.resources.engine)
        except Exception:
            raise BusinessError("DATABASE_UNAVAILABLE", "数据库或迁移不可用", 503) from None
        try:
            self.resources.storage.check_buckets()
        except Exception:
            raise BusinessError("STORAGE_UNAVAILABLE", "对象存储不可用", 503) from None
        return {"status": "ready"}

