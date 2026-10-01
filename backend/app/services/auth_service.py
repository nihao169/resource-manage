from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import text

from app.core.database import transaction
from app.core.errors import BusinessError
from app.core.security import (CurrentActor, create_access_token, create_csrf_token,
    hash_password, hash_refresh_token, new_refresh_token, read_key, verify_password)
from app.repositories.audit_repository import AuditRepository
from app.repositories.user_repository import UserRepository

class AuthService:
    def __init__(self, resources, settings):
        self.engine = resources.engine
        self.settings = settings
        self.users = UserRepository()
        self.audit = AuditRepository()

    @staticmethod
    def public_user(row):
        return {"id": row["id"], "username": row["username"], "display_name": row["display_name"],
            "role": row["role"], "status": row["status"],
            "must_change_password": row["must_change_password"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def login(self, username, password, *, user_agent, source_ip, request_id):
        now = datetime.now(timezone.utc)
        refresh = new_refresh_token()
        with transaction(self.engine) as connection:
            user = self.users.by_username(connection, username, for_update=True)
            if not user or not verify_password(user["password_hash"], password):
                raise BusinessError("INVALID_CREDENTIALS", "用户名或密码错误", 401)
            if user["status"] != "active":
                raise BusinessError("ACCOUNT_FROZEN", "账号当前不可用", 403)
            session = self.users.create_session(connection, user_id=user["id"],
                token_hash=hash_refresh_token(refresh),
                expires_at=now + timedelta(seconds=self.settings.refresh_ttl_seconds),
                user_agent=(user_agent or "")[:512] or None, source_ip=source_ip)
            actor = CurrentActor(UUID(str(user["id"])), UUID(str(session["id"])), user["username"],
                user["display_name"], user["role"], user["token_version"], user["must_change_password"])
            self.audit.append(connection, actor_id=user["id"], action="auth.login",
                target_type="session", target_id=session["id"], request_id=request_id,
                detail={}, source_ip=source_ip)
        return self._tokens(actor, user, session, refresh)

    def _tokens(self, actor, user, session, refresh):
        access, access_expires = create_access_token(actor,
            read_key(self.settings, "jwt_key_file"), self.settings.access_ttl_seconds)
        csrf, _ = create_csrf_token(str(actor.session_id),
            read_key(self.settings, "csrf_key_file"), self.settings.refresh_ttl_seconds)
        return {"access": access, "refresh": refresh, "csrf": csrf,
            "data": {"user": self.public_user(user), "access_expires_at": access_expires,
                "session_expires_at": session["expires_at"], "csrf_token": csrf}}

    def refresh(self, refresh_token, csrf_token):
        if not refresh_token:
            raise BusinessError("UNAUTHENTICATED", "缺少刷新会话", 401)
        now = datetime.now(timezone.utc)
        replacement = new_refresh_token()
        with transaction(self.engine) as connection:
            session = self.users.session_by_hash(connection, hash_refresh_token(refresh_token), for_update=True)
            if not session or session["revoked_at"] is not None or session["expires_at"] <= now:
                raise BusinessError("SESSION_EXPIRED", "会话已过期", 401)
            from app.core.security import validate_csrf_token
            try:
                validate_csrf_token(csrf_token, read_key(self.settings, "csrf_key_file"), str(session["id"]))
            except BusinessError:
                raise BusinessError("CSRF_INVALID", "CSRF 校验失败", 403) from None
            user = self.users.by_id(connection, session["user_id"], for_update=True)
            if not user or user["status"] != "active":
                raise BusinessError("ACCOUNT_FROZEN", "账号当前不可用", 403)
            session = self.users.rotate_session(connection, session["id"], hash_refresh_token(replacement))
            actor = CurrentActor(UUID(str(user["id"])), UUID(str(session["id"])), user["username"],
                user["display_name"], user["role"], user["token_version"], user["must_change_password"])
        return self._tokens(actor, user, session, replacement)

    def logout(self, session_id, refresh_token=None):
        with transaction(self.engine) as connection:
            if session_id:
                self.users.revoke_session(connection, session_id)
            elif refresh_token:
                session = self.users.session_by_hash(connection, hash_refresh_token(refresh_token))
                if session:
                    self.users.revoke_session(connection, session["id"])

    def change_password(self, actor, current_password, new_password, request_id):
        with transaction(self.engine) as connection:
            user = self.users.by_id(connection, actor.user_id, for_update=True)
            if not user or not verify_password(user["password_hash"], current_password):
                raise BusinessError("INVALID_CREDENTIALS", "当前密码错误", 401)
            connection.execute(text("""
                UPDATE users SET password_hash=:hash,password_changed_at=now(),
                  must_change_password=false,token_version=token_version+1 WHERE id=:id
            """), {"hash": hash_password(new_password), "id": actor.user_id})
            self.users.revoke_all(connection, actor.user_id)
            self.audit.append(connection, actor_id=actor.user_id, action="auth.password_changed",
                target_type="user", target_id=actor.user_id, request_id=request_id)

    def sessions(self, actor, page, page_size):
        with self.engine.connect() as connection:
            rows, total = self.users.list_sessions(connection, actor.user_id, page_size, (page-1)*page_size)
        return {"items": [{"session_id": row["id"], "is_current": row["id"] == actor.session_id,
            "created_at": row["created_at"], "expires_at": row["expires_at"],
            "last_used_at": row["last_used_at"], "revoked_at": row["revoked_at"],
            "user_agent": row["user_agent"], "source_ip": str(row["source_ip"]) if row["source_ip"] else None}
            for row in rows], "page": page, "page_size": page_size, "total": total}

    def revoke(self, actor, session_id):
        with transaction(self.engine) as connection:
            if not self.users.revoke_session(connection, session_id, actor.user_id):
                raise BusinessError("NOT_FOUND", "会话不存在", 404)

