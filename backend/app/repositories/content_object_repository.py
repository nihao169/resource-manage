from sqlalchemy import text

class ContentObjectRepository:
    def prepare(self, connection, *, sha256, size, object_key, producer_upload_id):
        return connection.execute(text("""
            INSERT INTO content_objects(sha256,size,object_key,producer_upload_id)
            VALUES (:sha256,:size,:object_key,:producer_upload_id)
            ON CONFLICT(sha256,size) DO UPDATE SET updated_at=content_objects.updated_at
            RETURNING *
        """), {"sha256": sha256, "size": size, "object_key": object_key,
            "producer_upload_id": producer_upload_id}).mappings().one()

    def by_id(self, connection, object_id, *, for_update=False):
        suffix = " FOR UPDATE" if for_update else ""
        return connection.execute(text("SELECT * FROM content_objects WHERE id=:id" + suffix),
            {"id": object_id}).mappings().first()

    def mark_ready(self, connection, object_id, *, sha256, size):
        return connection.execute(text("""
            UPDATE content_objects SET status='ready',last_error_code=NULL
             WHERE id=:id AND sha256=:sha256 AND size=:size AND status IN ('staging','ready')
             RETURNING *
        """), {"id": object_id, "sha256": sha256, "size": size}).mappings().first()
