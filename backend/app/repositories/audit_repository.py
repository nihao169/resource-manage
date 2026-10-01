import json
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

class AuditRepository:
    def append(self, connection, *, actor_id, action, target_type, target_id, request_id,
               result="success", detail=None, source_ip=None):
        return connection.execute(text("""
            INSERT INTO audit_events(actor_id,action,target_type,target_id,request_id,result,detail,source_ip)
            VALUES (:actor_id,:action,:target_type,:target_id,:request_id,:result,
                    CAST(:detail AS jsonb),:source_ip)
            RETURNING *
        """), {"actor_id": actor_id, "action": action, "target_type": target_type,
            "target_id": target_id, "request_id": request_id, "result": result,
            "detail": json.dumps(jsonable_encoder(detail or {}), ensure_ascii=False),
            "source_ip": source_ip}).mappings().one()

    def list(self, connection, *, limit, offset, actor_id=None, action=None,
             target_type=None, target_id=None, result=None):
        rows = connection.execute(text("""
            SELECT a.*,u.username,u.display_name,count(*) OVER() AS total
              FROM audit_events a LEFT JOIN users u ON u.id=a.actor_id
             WHERE (:actor_id IS NULL OR a.actor_id=:actor_id)
               AND (:action IS NULL OR a.action=:action)
               AND (:target_type IS NULL OR a.target_type=:target_type)
               AND (:target_id IS NULL OR a.target_id=:target_id)
               AND (:result IS NULL OR a.result=:result)
             ORDER BY a.created_at DESC,a.id DESC LIMIT :limit OFFSET :offset
        """), {"limit": limit, "offset": offset, "actor_id": actor_id, "action": action,
            "target_type": target_type, "target_id": target_id, "result": result}).mappings().all()
        return rows, (rows[0]["total"] if rows else 0)

