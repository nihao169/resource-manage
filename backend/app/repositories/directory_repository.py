from sqlalchemy import text

class DirectoryRepository:
    def list(self, connection, space_id, parent_id, *, limit, offset, tree=False):
        parent_filter = "" if tree else "AND parent_id IS NOT DISTINCT FROM :parent"
        rows = connection.execute(text(f"""
            SELECT *,count(*) OVER() AS total FROM directories
             WHERE space_id=:space AND status='active' {parent_filter}
             ORDER BY path_key,id LIMIT :limit OFFSET :offset
        """), {"space": space_id, "parent": parent_id, "limit": limit, "offset": offset}).mappings().all()
        return rows, (rows[0]["total"] if rows else 0)

    def by_id(self, connection, directory_id, *, for_update=False):
        suffix = " FOR UPDATE" if for_update else ""
        return connection.execute(text("SELECT * FROM directories WHERE id=:id AND status='active'" + suffix),
            {"id": directory_id}).mappings().first()

    def create(self, connection, *, directory_id, space_id, parent_id, name, actor_id, parent_path="/"):
        path_key = parent_path + str(directory_id) + "/"
        return connection.execute(text("""
            INSERT INTO directories(id,space_id,parent_id,name,path_key,created_by)
            VALUES (:id,:space,:parent,:name,:path,:actor) RETURNING *
        """), {"id": directory_id, "space": space_id, "parent": parent_id,
            "name": name, "path": path_key, "actor": actor_id}).mappings().one()

    def rename(self, connection, directory_id, name):
        return connection.execute(text("UPDATE directories SET name=:name WHERE id=:id RETURNING *"),
            {"id": directory_id, "name": name}).mappings().first()
