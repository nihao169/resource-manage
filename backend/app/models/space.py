from datetime import datetime
from uuid import UUID
from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class Space(Base):
    __tablename__ = "spaces"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    quota_bytes: Mapped[int] = mapped_column(BigInteger)
    used_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(12))
    created_by: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class SpaceMember(Base):
    __tablename__ = "space_members"
    space_id: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("spaces.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class Directory(Base):
    __tablename__ = "directories"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True)
    space_id: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("spaces.id"))
    parent_id: Mapped[UUID | None] = mapped_column(PGUUID)
    name: Mapped[str] = mapped_column(String(100))
    path_key: Mapped[str]
    status: Mapped[str] = mapped_column(String(12))
    created_by: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
