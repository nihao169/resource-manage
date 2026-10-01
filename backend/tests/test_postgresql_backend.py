from datetime import datetime, timedelta, timezone
import pytest

from app.core.errors import BusinessError
from app.core.security import (create_csrf_token, decode_token, encode_token, hash_password,
                               require_idempotency_key, validate_csrf_token, verify_password)
from app.models import (AuditEvent, ContentObject, Directory, File, FileVersion,
                        RefreshSession, Space, SpaceMember, Upload, UploadPart, User)
from app.schemas.dto import PatchFile, normalize_name

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
