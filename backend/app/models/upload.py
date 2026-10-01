from datetime import datetime
from uuid import UUID
from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class Upload(Base):
    __tablename__ = "uploads"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True)
    batch_id: Mapped[UUID | None] = mapped_column(PGUUID)
    user_id: Mapped[UUID] = mapped_column(PGUUID)
    space_id: Mapped[UUID] = mapped_column(PGUUID)
    directory_id: Mapped[UUID | None] = mapped_column(PGUUID)
    target_file_id: Mapped[UUID | None] = mapped_column(PGUUID)
    mode: Mapped[str] = mapped_column(String(12))
    original_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(2000))
    version_note: Mapped[str] = mapped_column(String(1000))
    tag_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID))
    metadata_values: Mapped[list] = mapped_column(JSONB)
    expected_size: Mapped[int] = mapped_column(BigInteger)
    actual_size: Mapped[int | None] = mapped_column(BigInteger)
    expected_sha256: Mapped[str] = mapped_column(String(64))
    actual_sha256: Mapped[str | None] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(127))
    storage_method: Mapped[str] = mapped_column(String(12))
    part_size: Mapped[int] = mapped_column(Integer)
    part_count: Mapped[int] = mapped_column(Integer)
    minio_upload_id: Mapped[str | None] = mapped_column(Text)
    temp_object_key: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(12))
    checkpoint: Mapped[str] = mapped_column(String(16))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    result_file_id: Mapped[UUID | None] = mapped_column(PGUUID)
    result_version_id: Mapped[UUID | None] = mapped_column(PGUUID)
    result_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    temp_cleaned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class UploadPart(Base):
    __tablename__ = "upload_parts"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True)
    upload_id: Mapped[UUID] = mapped_column(PGUUID)
    part_no: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer)
    etag: Mapped[str | None] = mapped_column(String(256))
    checksum: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
