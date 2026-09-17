"""B+C: create resources once in lifespan, release even on partial initialization."""
from dataclasses import dataclass
from app.core.config import Settings
from app.core.database import create_database_engine
from app.integrations.minio_client import MinioAdapter

@dataclass
class Resources:
    engine: object
    storage: object

    def close(self):
        try:
            self.storage.close()
        finally:
            self.engine.dispose()

def make_resources(settings: Settings):
    engine = create_database_engine(settings)
    try:
        return Resources(engine=engine, storage=MinioAdapter(settings))
    except Exception:
        engine.dispose()
        raise
