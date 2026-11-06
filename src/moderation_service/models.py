from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TicketStatus(enum.StrEnum):
    NEW = "NEW"
    GENERATING = "GENERATING"
    DRAFT_READY = "DRAFT_READY"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SENDING = "SENDING"
    DELIVERY_RETRY = "DELIVERY_RETRY"
    SENT = "SENT"
    FAILED = "FAILED"


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    customer_email: Mapped[str] = mapped_column(String(320))
    message: Mapped[str] = mapped_column(Text)
    reply_url: Mapped[str] = mapped_column(String(2048))
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, name="ticket_status"),
        default=TicketStatus.NEW,
        index=True,
    )
    draft_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    referenced_articles: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    llm_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    generation_time_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    webhook_events: Mapped[list[WebhookEvent]] = relationship(back_populates="ticket")


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tickets.ticket_id", ondelete="CASCADE"),
        index=True,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    ticket: Mapped[Ticket] = relationship(back_populates="webhook_events")


class KBArticle(Base):
    __tablename__ = "kb_articles"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)


class MockHelpdeskReply(Base):
    __tablename__ = "mock_helpdesk_replies"
    __table_args__ = (
        UniqueConstraint("ticket_id", name="uq_mock_helpdesk_replies_ticket_id"),
        UniqueConstraint("idempotency_key", name="uq_mock_helpdesk_replies_idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[str] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
