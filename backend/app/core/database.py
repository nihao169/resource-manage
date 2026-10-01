"""B: engine/session primitives. Services own transaction boundaries."""
from sqlalchemy import URL, create_engine
from contextlib import contextmanager
from sqlalchemy.orm import DeclarativeBase
from app.core.config import Settings

EXPECTED_REVISION = "0001_base"

class Base(DeclarativeBase):
    pass

def create_database_engine(settings: Settings):
    url = URL.create("postgresql+psycopg", username=settings.database_user,
                     password=settings.read_secret(settings.database_password_file),
                     host=settings.database_host, port=settings.database_port,
                     database=settings.database_name)
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5,
                         connect_args={"connect_timeout": 3,
                         "options": "-c statement_timeout=3000 -c timezone=UTC"})

@contextmanager
def transaction(engine):
    """Open a short transaction. Repositories never commit independently."""
    with engine.connect() as connection:
        with connection.begin():
            yield connection

def advisory_lock_key(namespace: str, identity: str) -> str:
    return f"fm:{namespace}:{identity}"

def try_advisory_lock(connection, namespace: str, identity: str) -> bool:
    from sqlalchemy import text
    return bool(connection.execute(text(
        "SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"
    ), {"key": advisory_lock_key(namespace, identity)}).scalar())

def release_advisory_lock(connection, namespace: str, identity: str) -> None:
    from sqlalchemy import text
    connection.execute(text(
        "SELECT pg_advisory_unlock(hashtextextended(:key, 0))"
    ), {"key": advisory_lock_key(namespace, identity)})

def check_database(engine):
    from sqlalchemy import text
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if revision != EXPECTED_REVISION:
            raise RuntimeError("Migration revision mismatch")
        connection.execute(text("SELECT id FROM users LIMIT 1"))

