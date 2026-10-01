from sqlalchemy import text

class SpaceRepository:
    def authorize(self, connection, actor, space_id, *, write=False):
        return connection.execute(text("""
            SELECT s.* FROM spaces s
             WHERE s.id=:space_id
               AND (:admin OR EXISTS(SELECT 1 FROM space_members m
                    WHERE m.space_id=s.id AND m.user_id=:user_id AND m.status='active'))
               AND ((:admin AND NOT :write) OR s.status='active')
        """), {"space_id": space_id, "user_id": actor.user_id,
            "admin": actor.role == "admin", "write": write}).mappings().first()

    def list(self, connection, actor, *, limit, offset, status=None):
        rows = connection.execute(text("""
            SELECT s.*,count(*) OVER() AS total FROM spaces s
             WHERE (:admin AND (:status IS NULL OR s.status=:status)) OR
                   (NOT :admin AND s.status='active' AND EXISTS(
                     SELECT 1 FROM space_members m WHERE m.space_id=s.id
                      AND m.user_id=:user_id AND m.status='active'))
             ORDER BY s.name,s.id LIMIT :limit OFFSET :offset
        """), {"admin": actor.role == "admin", "status": status, "user_id": actor.user_id,
            "limit": limit, "offset": offset}).mappings().all()
        return rows, (rows[0]["total"] if rows else 0)

    def create(self, connection, *, name, quota_bytes, actor_id):
        return connection.execute(text("""
            INSERT INTO spaces(name,quota_bytes,created_by) VALUES (:name,:quota,:actor)
            RETURNING *
        """), {"name": name, "quota": quota_bytes, "actor": actor_id}).mappings().one()

    def members(self, connection, space_id, *, limit, offset, status=None):
        rows = connection.execute(text("""
            SELECT m.*,u.id AS uid,u.username,u.display_name,count(*) OVER() AS total
              FROM space_members m JOIN users u ON u.id=m.user_id
             WHERE m.space_id=:space AND (:status IS NULL OR m.status=:status)
             ORDER BY u.username,u.id LIMIT :limit OFFSET :offset
        """), {"space": space_id, "status": status, "limit": limit, "offset": offset}).mappings().all()
        return rows, (rows[0]["total"] if rows else 0)

    def put_member(self, connection, space_id, user_id):
        return connection.execute(text("""
            INSERT INTO space_members(space_id,user_id) VALUES (:space,:user)
            ON CONFLICT(space_id,user_id) DO UPDATE SET status='active' RETURNING *
        """), {"space": space_id, "user": user_id}).mappings().one()

    def remove_member(self, connection, space_id, user_id):
        return connection.execute(text("""
            UPDATE space_members SET status='removed' WHERE space_id=:space AND user_id=:user RETURNING *
        """), {"space": space_id, "user": user_id}).mappings().first()
