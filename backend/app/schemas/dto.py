"""Public DTOs: no object bucket/key, storage credentials or internal ETag."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from app.schemas.common import ContractModel

UploadStatus = Literal["created", "uploading", "uploaded", "committed", "failed", "expired"]

class UserSummary(ContractModel):
    id: UUID
    username: str
    display_name: str

class Version(ContractModel):
    version_id: UUID
    file_id: UUID
    version_no: int
    version_note: str
    original_name: str
    extension: str
    mime: str
    size: int
    sha256: str
    retained_until: datetime | None
    legal_hold: bool
    restored_from_version_id: UUID | None
    uploader: UserSummary
    created_at: datetime

class Tag(ContractModel):
    tag_id: UUID
    space_id: UUID
    name: str
    status: Literal["active", "disabled"]
    created_at: datetime
    updated_at: datetime

class MetadataValue(ContractModel):
    field_id: UUID
    value_type: Literal["text", "number", "date", "boolean"]
    value: str | bool

class File(ContractModel):
    file_id: UUID
    space_id: UUID
    directory_id: UUID | None
    directory_path: str
    owner: UserSummary
    name: str
    description: str
    current_version: Version
    status: Literal["active", "deleted"]
    tags: list[Tag]
    metadata_values: list[MetadataValue]
    deleted_at: datetime | None
    deleted_by: UserSummary | None
    created_at: datetime
    updated_at: datetime

class Part(ContractModel):
    part_no: int
    size: int
    checksum: str
    confirmed_at: datetime

class Upload(ContractModel):
    upload_id: UUID
    batch_id: UUID | None
    mode: Literal["new_file", "new_version"]
    space_id: UUID
    directory_id: UUID | None
    target_file_id: UUID | None
    original_name: str
    expected_size: int
    expected_sha256: str
    mime: str
    storage_method: Literal["single", "multipart"]
    part_size: int
    part_count: int
    status: UploadStatus
    confirmed_parts: list[Part]
    confirmed_bytes: int
    expires_at: datetime
    last_error_code: str | None
    result_file_id: UUID | None
    result_version_id: UUID | None

class FileCommit(ContractModel):
    upload_id: UUID | None
    file: File
    version: Version

class Directory(ContractModel):
    directory_id: UUID
    space_id: UUID
    parent_id: UUID | None
    name: str
    display_path: str
    created_at: datetime
    updated_at: datetime

