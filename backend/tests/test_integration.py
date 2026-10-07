"""Opt-in checks against only this Compose project's initialized storage."""
import os
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from minio.error import S3Error
from app.core.config import Settings
from app.core.database import create_database_engine, check_database
from app.integrations.minio_client import MinioAdapter
from app.core.errors import BusinessError
from app.repositories.idempotency_repository import IdempotencyRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("FM_INTEGRATION_TESTS") != "1", reason="Requires initialized project storage")

@pytest.fixture
def engine():
    engine = create_database_engine(Settings())
    try:
        yield engine
    finally:
        engine.dispose()

def test_migration_and_app_privileges(engine):
    check_database(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_user")).scalar() == "fm_app"
        assert connection.execute(text("""SELECT count(*) FROM information_schema.tables
          WHERE table_schema='public' AND table_name <> 'alembic_version'""")).scalar() == 22
        assert not connection.execute(text("SELECT has_schema_privilege('public', 'CREATE')")).scalar()
        assert not connection.execute(text("SELECT has_table_privilege('users', 'TRUNCATE')")).scalar()
        assert not connection.execute(text("SELECT has_table_privilege('audit_events', 'UPDATE')")).scalar()
        assert not connection.execute(text("SELECT has_table_privilege('alembic_version', 'UPDATE')")).scalar()
        assert not connection.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")).scalar()

@pytest.mark.parametrize("statement", [
    "CREATE TABLE public.scaffold_forbidden_test (id integer)",
    "TRUNCATE public.users",
    "ALTER TABLE public.file_versions DISABLE TRIGGER ALL",
])
def test_forbidden_operations_are_rejected(engine, statement):
    with engine.connect() as connection:
        try:
            with pytest.raises(DBAPIError) as failure:
                connection.execute(text(statement))
            assert failure.value.orig.sqlstate == "42501"
        finally:
            connection.rollback()

def test_private_buckets_and_backup_isolation():
    storage = MinioAdapter(Settings())
    try:
        storage.check_buckets()
        for bucket in ("uploads", "contents", "backups"):
            response = storage.http.request("GET", "http://minio:9000/" + bucket)
            try:
                assert response.status == 403
            finally:
                response.close()
                response.release_conn()
        with pytest.raises(S3Error) as failure:
            storage.client.list_objects("backups").__next__()
        assert failure.value.code == "AccessDenied"
        # No content is written: this probe has no object-key side effects.
        with pytest.raises(S3Error):
            storage.client.stat_object("contents", "probe/" + str(uuid4()))
    finally:
        storage.close()

def test_idempotency_claim_replay_and_conflict_on_postgres(engine):
    actor_id = uuid4()
    key = "integration-" + str(uuid4())
    repository = IdempotencyRepository()
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO users(id,username,display_name,password_hash)
            VALUES (:id,:username,'Integration test','$argon2id$test')
        """), {"id": actor_id, "username": "integration-" + str(actor_id)})
    try:
        with repository.locked_transaction(engine, actor_id, key) as connection:
            claim = repository.claim(connection, actor_id=actor_id, key=key,
                method="POST", path="/api/spaces", payload={"name": "integration"})
            assert not claim.replayed
            repository.complete(connection, claim, {"space_id": str(uuid4())},
                http_status=201, target_type="space", target_id=None)
        with repository.locked_transaction(engine, actor_id, key) as connection:
            replay = repository.claim(connection, actor_id=actor_id, key=key,
                method="POST", path="/api/spaces", payload={"name": "integration"})
            assert replay.replayed
            assert replay.http_status == 201
            assert replay.response_data["space_id"]
        with pytest.raises(BusinessError) as failure:
            with repository.locked_transaction(engine, actor_id, key) as connection:
                repository.claim(connection, actor_id=actor_id, key=key,
                    method="POST", path="/api/spaces", payload={"name": "different"})
        assert failure.value.code == "IDEMPOTENCY_CONFLICT"
    finally:
        with engine.begin() as connection:
            connection.execute(text(
                "DELETE FROM idempotency_requests WHERE actor_id=:actor"), {"actor": actor_id})
            connection.execute(text("DELETE FROM users WHERE id=:actor"), {"actor": actor_id})
