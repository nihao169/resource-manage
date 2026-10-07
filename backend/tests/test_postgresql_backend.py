from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4
import pytest

from app.core.errors import BusinessError
from app.core.security import (create_csrf_token, decode_token, encode_token, hash_password,
                               require_idempotency_key, validate_csrf_token, verify_password)
from app.models import (AuditEvent, ContentObject, Directory, File, FileVersion,
                        RefreshSession, Space, SpaceMember, Upload, UploadPart, User)
from app.schemas.dto import PatchFile, normalize_name
from app.repositories.idempotency_repository import IdempotencyRepository, request_fingerprint

def test_password_hash_is_argon2_and_verifies():
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("$argon2id$")
    assert verify_password(encoded, "correct horse battery staple")
    assert not verify_password(encoded, "wrong password")

def test_tokens_pin_algorithm_type_issuer_and_audience():
    key = "k" * 32
    expires = int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())
    token = encode_token({"sub": "user", "sid": "session", "token_version": 0,
        "iss": "file-manager", "aud": "file-manager-web", "exp": expires},
        key, token_type="access")
    assert decode_token(token, key, token_type="access")["sid"] == "session"
    with pytest.raises(BusinessError):
        decode_token(token, "x" * 32, token_type="access")

def test_expired_token_is_rejected():
    key = "k" * 32
    token = encode_token({"iss": "file-manager", "aud": "file-manager-web",
        "exp": 1}, key, token_type="access")
    with pytest.raises(BusinessError) as failure:
        decode_token(token, key, token_type="access")
    assert failure.value.code == "UNAUTHENTICATED"

def test_csrf_is_bound_to_session():
    token, _ = create_csrf_token("session-a", "k" * 32, 300)
    assert validate_csrf_token(token, "k" * 32, "session-a")["binding"] == "session-a"
    with pytest.raises(BusinessError) as failure:
        validate_csrf_token(token, "k" * 32, "session-b")
    assert failure.value.code == "CSRF_INVALID"

def test_idempotency_key_contract():
    assert require_idempotency_key("12345678") == "12345678"
    with pytest.raises(BusinessError):
        require_idempotency_key("short")

def test_names_are_normalized_and_file_paths_rejected():
    assert normalize_name("  e\u0301  ") == "é"
    with pytest.raises(ValueError):
        PatchFile(name="folder/file")

def test_mvp_mappings_share_migration_base():
    assert {model.__tablename__ for model in (AuditEvent, ContentObject, Directory, File,
        FileVersion, RefreshSession, Space, SpaceMember, Upload, UploadPart, User)} == {
        "audit_events", "content_objects", "directories", "files", "file_versions",
        "refresh_sessions", "spaces", "space_members", "uploads", "upload_parts", "users"}

def test_idempotency_fingerprint_is_canonical():
    first = request_fingerprint("post", "/api/spaces", {"name": "A", "quota": 10})
    second = request_fingerprint("POST", "/api/spaces", {"quota": 10, "name": "A"})
    assert first == second

def test_completed_idempotency_claim_replays_snapshot():
    actor_id, request_id = uuid4(), uuid4()
    payload = {"name": "documents"}
    connection = MagicMock()
    result = connection.execute.return_value.mappings.return_value
    result.first.return_value = {"id": request_id, "method": "POST", "path": "/api/spaces",
        "request_hash": request_fingerprint("POST", "/api/spaces", payload),
        "status": "completed", "http_status": 201,
        "response_data": {"space_id": str(uuid4())}}
    claim = IdempotencyRepository().claim(connection, actor_id=actor_id, key="request-123",
        method="POST", path="/api/spaces", payload=payload)
    assert claim.replayed is True
    assert claim.http_status == 201
    assert claim.response_data["space_id"]

def test_reused_idempotency_key_with_different_payload_conflicts():
    connection = MagicMock()
    result = connection.execute.return_value.mappings.return_value
    result.first.return_value = {"id": uuid4(), "method": "POST", "path": "/api/spaces",
        "request_hash": request_fingerprint("POST", "/api/spaces", {"name": "A"}),
        "status": "completed", "http_status": 201, "response_data": {}}
    with pytest.raises(BusinessError) as failure:
        IdempotencyRepository().claim(connection, actor_id=uuid4(), key="request-123",
            method="POST", path="/api/spaces", payload={"name": "B"})
    assert failure.value.code == "IDEMPOTENCY_CONFLICT"
