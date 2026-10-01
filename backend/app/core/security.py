"""Authentication, signed cookies, CSRF and authorization dependencies."""
import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Cookie, Header, Request
from sqlalchemy import text

from app.core.errors import BusinessError
ACCESS_TTL_SECONDS = 900
REFRESH_TTL_SECONDS = 604800
ACCESS_COOKIE = "__Host-fm_access"
REFRESH_COOKIE = "__Host-fm_refresh"
CSRF_COOKIE = "__Host-fm_csrf"
ISSUER = "file-manager"
AUDIENCE = "file-manager-web"
_PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)

@dataclass(frozen=True)
class CurrentActor:
    user_id: UUID
    session_id: UUID
    username: str
    display_name: str
    role: str
    token_version: int
    must_change_password: bool

def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

def _sign(encoded: str, key: str) -> str:
    return _b64encode(hmac.new(key.encode(), encoded.encode(), hashlib.sha256).digest())

def encode_token(claims: dict, key: str, *, token_type: str) -> str:
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = dict(claims)
    body["typ"] = token_type
    encoded = header + "." + _b64encode(json.dumps(body, separators=(",", ":")).encode())
    return encoded + "." + _sign(encoded, key)

def decode_token(token: str, key: str, *, token_type: str) -> dict:
    try:
        header, payload, signature = token.split(".")
        encoded = header + "." + payload
        if not hmac.compare_digest(signature, _sign(encoded, key)):
            raise ValueError
        header_data = json.loads(_b64decode(header))
        claims = json.loads(_b64decode(payload))
        now = int(datetime.now(timezone.utc).timestamp())
        if header_data != {"alg": "HS256", "typ": "JWT"}:
            raise ValueError
        if claims.get("typ") != token_type or claims.get("exp", 0) <= now:
            raise ValueError
        if token_type == "access" and (claims.get("iss") != ISSUER or claims.get("aud") != AUDIENCE):
            raise ValueError
        return claims
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
        raise BusinessError("UNAUTHENTICATED", "登录状态无效", 401) from None

def hash_password(password: str) -> str:
    return _PASSWORD_HASHER.hash(password)

def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False

def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def new_refresh_token() -> str:
    return _b64encode(secrets.token_bytes(32))

def create_access_token(actor: CurrentActor, key: str, ttl: int = ACCESS_TTL_SECONDS) -> tuple[str, datetime]:
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    return encode_token({"sub": str(actor.user_id), "sid": str(actor.session_id),
        "token_version": actor.token_version, "iss": ISSUER, "aud": AUDIENCE,
        "exp": int(expires.timestamp())}, key, token_type="access"), expires

def create_csrf_token(binding: str, key: str, ttl: int = REFRESH_TTL_SECONDS) -> tuple[str, datetime]:
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    token = encode_token({"binding": binding, "nonce": _b64encode(secrets.token_bytes(18)),
        "exp": int(expires.timestamp())}, key, token_type="csrf")
    return token, expires

def validate_csrf_token(token: str, key: str, binding: str | None = None) -> dict:
    claims = decode_token(token, key, token_type="csrf")
    if binding is not None and claims.get("binding") != binding:
        raise BusinessError("CSRF_INVALID", "CSRF 校验失败", 403)
    return claims

def read_key(settings, attribute: str) -> str:
    return settings.read_secret(getattr(settings, attribute))

def require_csrf(request: Request, csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
                 csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None) -> None:
    origin = request.headers.get("origin")
    if origin != str(request.app.state.settings.public_origin).rstrip("/"):
        raise BusinessError("ORIGIN_FORBIDDEN", "请求来源不允许", 403)
    if not csrf_header or not csrf_cookie or not hmac.compare_digest(csrf_header, csrf_cookie):
        raise BusinessError("CSRF_INVALID", "CSRF 校验失败", 403)
    try:
        validate_csrf_token(csrf_header, read_key(request.app.state.settings, "csrf_key_file"))
    except BusinessError:
        raise BusinessError("CSRF_INVALID", "CSRF 校验失败", 403) from None

def require_idempotency_key(
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> str:
    if not idempotency_key or not 8 <= len(idempotency_key) <= 128 \
            or any(ord(char) < 33 or ord(char) > 126 for char in idempotency_key):
        raise BusinessError("VALIDATION_ERROR", "Idempotency-Key 格式无效", 422,
            {"fields": [{"loc": ["header", "Idempotency-Key"], "type": "value_error"}]})
    return idempotency_key

def current_actor(request: Request,
                  access_cookie: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None) -> CurrentActor:
    if not access_cookie:
        raise BusinessError("UNAUTHENTICATED", "请先登录", 401)
    claims = decode_token(access_cookie,
        read_key(request.app.state.settings, "jwt_key_file"), token_type="access")
    with request.app.state.resources.engine.connect() as connection:
        row = connection.execute(text("""
            SELECT u.id, s.id AS session_id, u.username, u.display_name, u.role,
                   u.status, u.token_version, u.must_change_password,
                   s.revoked_at, s.expires_at
              FROM users u JOIN refresh_sessions s ON s.user_id=u.id
             WHERE u.id=:uid AND s.id=:sid
        """), {"uid": claims["sub"], "sid": claims["sid"]}).mappings().first()
    if not row or row["revoked_at"] is not None or row["expires_at"] <= datetime.now(timezone.utc):
        raise BusinessError("SESSION_EXPIRED", "会话已过期", 401)
    if row["status"] != "active":
        raise BusinessError("ACCOUNT_FROZEN", "账号当前不可用", 403)
    if row["token_version"] != claims.get("token_version"):
        raise BusinessError("SESSION_EXPIRED", "会话已失效", 401)
    return CurrentActor(UUID(str(row["id"])), UUID(str(row["session_id"])), row["username"],
        row["display_name"], row["role"], row["token_version"], row["must_change_password"])

def require_admin(actor: CurrentActor) -> None:
    if actor.role != "admin":
        raise BusinessError("FORBIDDEN", "需要管理员权限", 403)

def ensure_business_access(actor: CurrentActor) -> None:
    if actor.must_change_password:
        raise BusinessError("PASSWORD_CHANGE_REQUIRED", "请先修改密码", 403)

