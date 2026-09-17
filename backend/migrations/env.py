"""B: explicit SQL migrations; do not autogenerate from incomplete ORM placeholders."""
from alembic import context
from app.core.config import Settings
from app.core.database import create_database_engine

config = context.config
target_metadata = None
if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported; use the isolated project database.")
if getattr(config.cmd_opts, "autogenerate", False):
    raise RuntimeError("ORM mapping is not complete. Use explicit, reviewed migrations.")
engine = create_database_engine(Settings())
try:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
