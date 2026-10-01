from datetime import datetime
from uuid import UUID
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class ContentObject(Base):
    __tablename__ = "content_objects"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True)
    bucket: Mapped[str] = mapped_column(String(63))
    object_key: Mapped[str] = mapped_column(String(256))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    reference_count: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(12))
    producer_upload_id: Mapped[UUID | None] = mapped_column(PGUUID)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class File(Base):
    __tablename__ = "files"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True)
    space_id: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("spaces.id"))
    directory_id: Mapped[UUID | None] = mapped_column(PGUUID)
    owner_id: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(2000))
    current_version_id: Mapped[UUID | None] = mapped_column(PGUUID)
    status: Mapped[str] = mapped_column(String(12))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(PGUUID, ForeignKey("users.id"))
    creation_request_id: Mapped[UUID | None] = mapped_column(PGUUID)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class FileVersion(Base):
    __tablename__ = "file_versions"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True)
    file_id: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("files.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    version_note: Mapped[str] = mapped_column(String(1000))
    original_name: Mapped[str] = mapped_column(String(255))
    extension: Mapped[str] = mapped_column(String(32))
    content_object_id: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("content_objects.id"))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(127))
    retained_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legal_hold: Mapped[bool] = mapped_column(Boolean)
    restored_from_version_id: Mapped[UUID | None] = mapped_column(PGUUID)
    created_by: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("users.id"))
    creation_request_id: Mapped[UUID | None] = mapped_column(PGUUID)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

