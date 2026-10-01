"""Public DTOs: no object bucket/key, storage credentials or internal ETag."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import Field, field_validator, model_validator
from app.schemas.common import ContractModel

UploadStatus = Literal["created", "uploading", "uploaded", "committed", "failed", "expired"]

class UserSummary(ContractModel):
    id: UUID
    username: str
    display_name: str

class User(UserSummary):
    role: Literal["admin", "user"]
    status: Literal["active", "frozen", "disabled"]
    must_change_password: bool
    created_at: datetime
    updated_at: datetime

class AuthResult(ContractModel):
    user: User
    access_expires_at: datetime
    session_expires_at: datetime
    csrf_token: str

class Session(ContractModel):
    session_id: UUID
    is_current: bool
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime
    revoked_at: datetime | None
    user_agent: str | None
    source_ip: str | None

class Space(ContractModel):
    space_id: UUID
    name: str
    quota_bytes: int
    used_bytes: int
    status: Literal["active", "disabled"]
    created_at: datetime
    updated_at: datetime

class Member(ContractModel):
    space_id: UUID
    user: UserSummary
    status: Literal["active", "removed"]
    created_at: datetime
    updated_at: datetime

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

def normalize_name(value: str, *, file_name: bool = False) -> str:
    import unicodedata
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise ValueError("名称包含非法字符")
    if file_name and any(char in normalized for char in "/\\"):
        raise ValueError("文件名不能包含路径分隔符")
    return normalized

class LoginInput(ContractModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=128)

class PasswordInput(ContractModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

class CreateSpace(ContractModel):
    name: str = Field(min_length=1, max_length=100)
    quota_bytes: int = Field(default=10737418240, ge=0, le=9007199254740991)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return normalize_name(value)

class CreateDirectory(ContractModel):
    space_id: UUID
    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return normalize_name(value)

class PatchDirectory(ContractModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return normalize_name(value) if value is not None else None

    @model_validator(mode="after")
    def require_change(self):
        if self.name is None:
            raise ValueError("至少提供一个修改字段")
        return self

class PatchFile(ContractModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return normalize_name(value, file_name=True) if value is not None else None

    @model_validator(mode="after")
    def require_change(self):
        if self.name is None and self.description is None:
            raise ValueError("至少提供一个修改字段")
        return self

class RestoreVersion(ContractModel):
    source_version_id: UUID
    version_note: str = Field(default="", max_length=1000)
    expected_current_version_id: UUID | None = None

class FileQuery(ContractModel):
    space_id: UUID | None = None
    directory_id: UUID | None = None
    root: bool = False
    owner_id: UUID | None = None
    uploader_id: UUID | None = None
    mime: str | None = Field(default=None, max_length=127)
    extension: list[str] = Field(default_factory=list)
    q: str | None = Field(default=None, min_length=1, max_length=200)
    sort: Literal["updated_at_desc", "created_at_desc", "name_asc"] = "updated_at_desc"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)

    @model_validator(mode="after")
    def validate_location(self):
        if self.root and self.directory_id is not None:
            raise ValueError("root 与 directory_id 不能同时使用")
        if any(not item or item.startswith(".") or item.lower() != item for item in self.extension):
            raise ValueError("扩展名必须为小写且不含点")
        return self

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

