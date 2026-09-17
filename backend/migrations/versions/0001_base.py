"""B: 22-table contract baseline. C supplies storage field requirements."""
from pathlib import Path
from alembic import op

revision = "0001_base"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    sql = (Path(__file__).parent.parent / "sql" / "0001_base.sql").read_text(encoding="utf-8")
    # psycopg supports this reviewed multi-statement SQL via a raw cursor.
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(sql, prepare=False)
        cursor.execute("""
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO fm_app;
            REVOKE UPDATE, DELETE ON audit_events FROM fm_app;
            REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM fm_app;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public
              GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fm_app;
        """, prepare=False)

def downgrade():
    raise RuntimeError("Initial migration is irreversible; restore a reviewed backup, never drop data.")

