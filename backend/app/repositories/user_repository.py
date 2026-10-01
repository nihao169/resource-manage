"""Explicit account queries. Callers own transaction boundaries."""
from sqlalchemy import text

class UserRepository:
    def by_username(self, connection, username: str, *, for_update: bool = False):
        suffix = " FOR UPDATE" if for_update else ""
        return connection.execute(text("SELECT * FROM users WHERE lower(username)=lower(:username)" + suffix),
            {"username": username}).mappings().first()

    def by_id(self, connection, user_id, *, for_update: bool = False):
        suffix = " FOR UPDATE" if for_update else ""
        return connection.execute(text("SELECT * FROM users WHERE id=:id" + suffix),
            {"id": user_id}).mappings().first()

    def create_session(self, connection, **values):
        return connection.execute(text("""
            INSERT INTO refresh_sessions(user_id,token_hash,expires_at,user_agent,source_ip)
            VALUES (:user_id,:token_hash,:expires_at,:user_agent,:source_ip)
            RETURNING *
        """), values).mappings().one()

    def session_by_hash(self, connection, token_hash: str, *, for_update: bool = False):
        suffix = " FOR UPDATE" if for_update else ""
        return connection.execute(text("SELECT * FROM refresh_sessions WHERE token_hash=:hash" + suffix),
            {"hash": token_hash}).mappings().first()

    def rotate_session(self, connection, session_id, token_hash: str):
        return connection.execute(text("""
            UPDATE refresh_sessions SET token_hash=:hash, token_id=gen_random_uuid(), last_used_at=now()
             WHERE id=:id RETURNING *
        """), {"id": session_id, "hash": token_hash}).mappings().one()

    def revoke_session(self, connection, session_id, user_id=None) -> bool:
        result = connection.execute(text("""
            UPDATE refresh_sessions SET revoked_at=COALESCE(revoked_at,now())
             WHERE id=:id AND (:user_id IS NULL OR user_id=:user_id)
        """), {"id": session_id, "user_id": user_id})
        return result.rowcount > 0

    def revoke_all(self, connection, user_id) -> None:
        connection.execute(text("UPDATE refresh_sessions SET revoked_at=COALESCE(revoked_at,now()) WHERE user_id=:id"),
            {"id": user_id})

    def list_sessions(self, connection, user_id, limit: int, offset: int):
        rows = connection.execute(text("""
            SELECT *, count(*) OVER() AS total FROM refresh_sessions
             WHERE user_id=:user_id ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset
        """), {"user_id": user_id, "limit": limit, "offset": offset}).mappings().all()
        return rows, (rows[0]["total"] if rows else 0)

