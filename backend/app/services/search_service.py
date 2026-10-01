from app.repositories.file_repository import FileRepository
from app.services.file_service import render_file

class SearchService:
    def __init__(self, resources):
        self.engine = resources.engine
        self.files = FileRepository()

    def search(self, actor, query):
        with self.engine.connect() as connection:
            rows, total = self.files.list(connection, actor, status="active",
                space_id=query.space_id, directory_id=query.directory_id, root=query.root,
                owner_id=query.owner_id, uploader_id=query.uploader_id, mime=query.mime,
                extensions=query.extension, q=query.q, limit=query.page_size,
                offset=query.offset, sort="updated_at_desc")
        needle = query.q.lower()
        items = []
        for row in rows:
            sources = [("name", 100, row["name"]), ("description", 80, row["description"]),
                ("directory", 40, row["directory_name"] or ""),
                ("uploader", 30, " ".join([row["uploader_username"], row["uploader_display_name"]])),
                ("mime", 20, row["mime"])]
            matches = [(name, score) for name, score, value in sources if needle in value.lower()]
            match_source, score = max(matches, key=lambda item: item[1]) if matches else ("name", 0)
            items.append({"file": render_file(row), "match_source": match_source, "score": score})
        items.sort(key=lambda item: item["score"], reverse=True)
        return {"items": items, "page": query.page, "page_size": query.page_size, "total": total}
