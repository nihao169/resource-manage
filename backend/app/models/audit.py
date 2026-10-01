from datetime import datetime
from uuid import UUID
from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID)
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[UUID | None] = mapped_column(PGUUID)
    request_id: Mapped[UUID] = mapped_column(PGUUID)
    result: Mapped[str] = mapped_column(String(12))
    detail: Mapped[dict] = mapped_column(JSONB)
    source_ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
