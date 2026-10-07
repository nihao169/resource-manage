import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from app.core.database import release_advisory_lock, try_advisory_lock
from app.core.errors import BusinessError


@dataclass(frozen=True)
class IdempotencyClaim:
    id: Any
    replayed: bool
    http_status: int | None = None
    response_data: Any = None


def request_fingerprint(method: str, path: str, payload: Any) -> str:
    normalized = json.dumps({"method": method.upper(), "path": path,
        "payload": jsonable_encoder(payload)}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class IdempotencyRepository:
    @contextmanager
    def locked_transaction(self, engine, actor_id, key):
        identity = f"{actor_id}:{key}"
        with engine.connect() as connection:
            locked = try_advisory_lock(connection, "idem", identity)
            if not locked:
                connection.rollback()
                raise BusinessError("OPERATION_IN_PROGRESS", "相同操作正在处理中", 409)
            connection.commit()
            try:
                with connection.begin():
                    yield connection
            finally:
                if connection.in_transaction():
                    connection.rollback()
                release_advisory_lock(connection, "idem", identity)
                connection.commit()

    def claim(self, connection, *, actor_id, key, method, path, payload) -> IdempotencyClaim:
        fingerprint = request_fingerprint(method, path, payload)
        row = connection.execute(text("""
            SELECT * FROM idempotency_requests
             WHERE actor_id=:actor AND idempotency_key=:key FOR UPDATE
        """), {"actor": actor_id, "key": key}).mappings().first()
        if row:
            if row["method"] != method.upper() or row["path"] != path \
                    or row["request_hash"] != fingerprint:
                raise BusinessError("IDEMPOTENCY_CONFLICT", "幂等键已用于不同请求", 409)
            if row["status"] == "completed":
                return IdempotencyClaim(row["id"], True, row["http_status"], row["response_data"])
            raise BusinessError("OPERATION_IN_PROGRESS", "相同操作正在处理中", 409)
        row = connection.execute(text("""
            INSERT INTO idempotency_requests(actor_id,idempotency_key,method,path,request_hash)
            VALUES (:actor,:key,:method,:path,:hash) RETURNING id
        """), {"actor": actor_id, "key": key, "method": method.upper(),
            "path": path, "hash": fingerprint}).mappings().one()
        return IdempotencyClaim(row["id"], False)

    def complete(self, connection, claim: IdempotencyClaim, data, *, http_status=200,
                 target_type=None, target_id=None):
        encoded = json.dumps(jsonable_encoder(data), ensure_ascii=False,
            sort_keys=True, separators=(",", ":"))
        connection.execute(text("""
            UPDATE idempotency_requests
               SET status='completed',http_status=:status,response_data=CAST(:data AS jsonb),
                   result_target_type=:target_type,result_target_id=:target_id,completed_at=now()
             WHERE id=:id
        """), {"status": http_status, "data": encoded, "target_type": target_type,
            "target_id": target_id, "id": claim.id})
