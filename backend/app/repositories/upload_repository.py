import json
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

class UploadRepository:
    def by_id(self, connection, upload_id, *, for_update=False):
        suffix = " FOR UPDATE" if for_update else ""
        return connection.execute(text("SELECT * FROM uploads WHERE id=:id" + suffix),
            {"id": upload_id}).mappings().first()

    def create(self, connection, values):
        return connection.execute(text("""
            INSERT INTO uploads(user_id,space_id,directory_id,target_file_id,mode,original_name,
              description,version_note,tag_ids,metadata_values,expected_size,expected_sha256,mime,
              storage_method,part_size,part_count,temp_object_key,idempotency_key,request_hash,batch_id)
            VALUES (:user_id,:space_id,:directory_id,:target_file_id,:mode,:original_name,
              :description,:version_note,:tag_ids,CAST(:metadata_values AS jsonb),:expected_size,:expected_sha256,:mime,
              :storage_method,:part_size,:part_count,:temp_object_key,:idempotency_key,:request_hash,:batch_id)
            RETURNING *
        """), {**values, "metadata_values": json.dumps(
            jsonable_encoder(values["metadata_values"]), ensure_ascii=False)}).mappings().one()

    def confirm_part(self, connection, upload_id, *, part_no, size, etag, checksum):
        return connection.execute(text("""
            INSERT INTO upload_parts(upload_id,part_no,size,etag,checksum,status,confirmed_at)
            VALUES (:upload_id,:part_no,:size,:etag,:checksum,'confirmed',now())
            ON CONFLICT(upload_id,part_no) DO UPDATE SET
              size=CASE WHEN upload_parts.size=excluded.size AND upload_parts.checksum=excluded.checksum
                        THEN upload_parts.size ELSE -1 END
            RETURNING *
        """), {"upload_id": upload_id, "part_no": part_no, "size": size,
            "etag": etag, "checksum": checksum}).mappings().one()

    def parts(self, connection, upload_id):
        return connection.execute(text("""
            SELECT * FROM upload_parts WHERE upload_id=:id AND status='confirmed' ORDER BY part_no
        """), {"id": upload_id}).mappings().all()
