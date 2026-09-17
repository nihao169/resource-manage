"""B implements DB methods; C orchestrates storage. No second HTTP service."""
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

@dataclass(frozen=True)
class ActorSession:
    user_id: UUID
    session_id: UUID

@dataclass(frozen=True)
class VerifiedContent:
    object_id: UUID
    size: int
    sha256: str
    mime: str

class DatabaseContract(Protocol):
    def authorize_upload(self, connection: Any, actor: ActorSession, payload: Any) -> Any: ...
    def create_upload_record(self, connection: Any, actor: ActorSession, payload: Any) -> Any: ...
    def confirm_part(self, connection: Any, upload_id: UUID, part: Any) -> Any: ...
    def get_upload_resume(self, connection: Any, actor: ActorSession, upload_id: UUID) -> Any: ...
    def prepare_content_record(self, connection: Any, content: Any) -> Any: ...
    def mark_object_ready(self, connection: Any, content: VerifiedContent) -> Any: ...
    def commit_upload(self, connection: Any, actor: ActorSession, upload_id: UUID,
                      content: VerifiedContent, idempotency_id: UUID, request_id: UUID) -> Any: ...
    def authorize_download(self, connection: Any, actor: ActorSession,
                           file_id: UUID, version_id: UUID) -> Any: ...
    def detach_file(self, connection: Any, actor: ActorSession, file_id: UUID,
                    confirmation: Any) -> Any: ...
    def finalize_cleanup_item(self, connection: Any, attempt_id: UUID, item: Any) -> Any: ...
# The connection above is pinned by the owning Service; methods MUST NOT commit it.
# See doc/MinIO对象规则.md section 8 for inputs, outputs and compensation ownership.

