"""B: engine/session primitives. Services own transaction boundaries."""
from sqlalchemy import URL, create_engine
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

def check_database(engine):
    from sqlalchemy import text
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if revision != EXPECTED_REVISION:
            raise RuntimeError("Migration revision mismatch")
        connection.execute(text("SELECT id FROM users LIMIT 1"))

