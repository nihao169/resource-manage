from sqlalchemy import text

FILE_SELECT = """
 SELECT f.*,d.name AS directory_name,o.username AS owner_username,o.display_name AS owner_display_name,
        v.id AS version_id,v.version_no,v.version_note,v.original_name,v.extension,v.mime,v.size,
        v.sha256,v.retained_until,v.legal_hold,v.restored_from_version_id,v.created_at AS version_created_at,
        up.id AS uploader_id,up.username AS uploader_username,up.display_name AS uploader_display_name,
        db.username AS deleted_username,db.display_name AS deleted_display_name
   FROM files f JOIN users o ON o.id=f.owner_id
   JOIN file_versions v ON v.id=f.current_version_id
   JOIN users up ON up.id=v.created_by
   LEFT JOIN users db ON db.id=f.deleted_by
   LEFT JOIN directories d ON d.id=f.directory_id
"""

class FileRepository:
    def visible(self, connection, actor, file_id, *, include_deleted=False, for_update=False):
        status = "" if include_deleted else "AND f.status='active'"
        suffix = " FOR UPDATE OF f" if for_update else ""
        return connection.execute(text(FILE_SELECT + f"""
             WHERE f.id=:id {status} AND (:admin OR EXISTS(
               SELECT 1 FROM space_members sm WHERE sm.space_id=f.space_id
                AND sm.user_id=:user AND sm.status='active')) {suffix}
        """), {"id": file_id, "admin": actor.role == "admin", "user": actor.user_id}).mappings().first()

    def list(self, connection, actor, *, status='active', space_id=None, directory_id=None,
             root=False, owner_id=None, uploader_id=None, mime=None, extensions=None,
             q=None, limit=50, offset=0, sort='updated_at_desc'):
        order = {"updated_at_desc": "f.updated_at DESC,f.id DESC",
                 "created_at_desc": "f.created_at DESC,f.id DESC",
                 "name_asc": "lower(f.name),f.id"}.get(sort, "f.updated_at DESC,f.id DESC")
        rows = connection.execute(text(FILE_SELECT + f"""
             WHERE f.status=:status
               AND (:admin OR EXISTS(SELECT 1 FROM space_members sm WHERE sm.space_id=f.space_id
                    AND sm.user_id=:user AND sm.status='active'))
               AND (:space IS NULL OR f.space_id=:space)
               AND (:directory IS NULL OR f.directory_id=:directory)
               AND (NOT :root OR f.directory_id IS NULL)
               AND (:owner IS NULL OR f.owner_id=:owner)
               AND (:uploader IS NULL OR v.created_by=:uploader)
               AND (:mime IS NULL OR v.mime=:mime)
               AND (:extensions IS NULL OR v.extension=ANY(:extensions))
               AND (:q IS NULL OR lower(f.name) LIKE :pattern ESCAPE '\\'
                    OR lower(f.description) LIKE :pattern ESCAPE '\\'
                    OR lower(COALESCE(d.name,'')) LIKE :pattern ESCAPE '\\'
                    OR lower(v.mime) LIKE :pattern ESCAPE '\\'
                    OR lower(o.username) LIKE :pattern ESCAPE '\\'
                    OR lower(o.display_name) LIKE :pattern ESCAPE '\\'
                    OR lower(up.username) LIKE :pattern ESCAPE '\\'
                    OR lower(up.display_name) LIKE :pattern ESCAPE '\\')
             ORDER BY {order} LIMIT :limit OFFSET :offset
        """), {"status": status, "admin": actor.role == "admin", "user": actor.user_id,
            "space": space_id, "directory": directory_id, "root": root, "owner": owner_id,
            "uploader": uploader_id, "mime": mime, "extensions": extensions or None,
            "q": q, "pattern": None if q is None else "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",
            "limit": limit, "offset": offset}).mappings().all()
        # Count uses the same authorization and the same filters without multiplying joins.
        count = connection.execute(text("""
            SELECT count(*) FROM files f JOIN file_versions v ON v.id=f.current_version_id
              JOIN users o ON o.id=f.owner_id JOIN users up ON up.id=v.created_by
              LEFT JOIN directories d ON d.id=f.directory_id
             WHERE f.status=:status
               AND (:admin OR EXISTS(SELECT 1 FROM space_members sm WHERE sm.space_id=f.space_id
                    AND sm.user_id=:user AND sm.status='active'))
               AND (:space IS NULL OR f.space_id=:space)
               AND (:directory IS NULL OR f.directory_id=:directory)
               AND (NOT :root OR f.directory_id IS NULL)
               AND (:owner IS NULL OR f.owner_id=:owner)
               AND (:uploader IS NULL OR v.created_by=:uploader)
               AND (:mime IS NULL OR v.mime=:mime)
               AND (:extensions IS NULL OR v.extension=ANY(:extensions))
               AND (:q IS NULL OR lower(f.name) LIKE :pattern ESCAPE '\\'
                    OR lower(f.description) LIKE :pattern ESCAPE '\\'
                    OR lower(COALESCE(d.name,'')) LIKE :pattern ESCAPE '\\'
                    OR lower(v.mime) LIKE :pattern ESCAPE '\\'
                    OR lower(o.username) LIKE :pattern ESCAPE '\\'
                    OR lower(o.display_name) LIKE :pattern ESCAPE '\\'
                    OR lower(up.username) LIKE :pattern ESCAPE '\\'
                    OR lower(up.display_name) LIKE :pattern ESCAPE '\\')
        """), {"status": status, "admin": actor.role == "admin", "user": actor.user_id,
            "space": space_id, "directory": directory_id, "root": root, "owner": owner_id,
            "uploader": uploader_id, "mime": mime, "extensions": extensions or None,
            "q": q, "pattern": None if q is None else "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"}).scalar_one()
        return rows, count

    def patch(self, connection, file_id, *, name=None, description=None):
        return connection.execute(text("""
            UPDATE files SET name=COALESCE(:name,name),description=COALESCE(:description,description)
             WHERE id=:id RETURNING *
        """), {"id": file_id, "name": name, "description": description}).mappings().first()

    def soft_delete(self, connection, file_id, actor_id):
        connection.execute(text("""
            UPDATE files SET status='deleted',deleted_at=COALESCE(deleted_at,now()),
              deleted_by=COALESCE(deleted_by,:actor) WHERE id=:id
        """), {"id": file_id, "actor": actor_id})

    def restore(self, connection, file_id):
        connection.execute(text("""
            UPDATE files SET status='active',deleted_at=NULL,deleted_by=NULL WHERE id=:id
        """), {"id": file_id})

    def versions(self, connection, file_id, *, limit, offset):
        rows = connection.execute(text("""
            SELECT v.*,u.username,u.display_name,count(*) OVER() AS total
              FROM file_versions v JOIN users u ON u.id=v.created_by
             WHERE v.file_id=:file ORDER BY v.version_no DESC LIMIT :limit OFFSET :offset
        """), {"file": file_id, "limit": limit, "offset": offset}).mappings().all()
        return rows, (rows[0]["total"] if rows else 0)

    def version(self, connection, file_id, version_id):
        return connection.execute(text("""
            SELECT v.*,u.username,u.display_name FROM file_versions v JOIN users u ON u.id=v.created_by
             WHERE v.file_id=:file AND v.id=:version
        """), {"file": file_id, "version": version_id}).mappings().first()

