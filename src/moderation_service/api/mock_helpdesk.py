from __future__ import annotations

import asyncio
from secrets import SystemRandom
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from moderation_service.config import settings
from moderation_service.database import get_session
from moderation_service.models import MockHelpdeskReply
from moderation_service.schemas import MockHelpdeskReplyRequest, MockHelpdeskReplyResponse

_RANDOM = SystemRandom()
_FAILURE_SPLIT = 0.5

router = APIRouter(prefix="/mock-helpdesk", tags=["mock-helpdesk"])


@router.post(
    "/tickets/{ticket_id}/replies",
    response_model=MockHelpdeskReplyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def receive_reply(
    ticket_id: str,
    payload: MockHelpdeskReplyRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MockHelpdeskReplyResponse:
    """Simulate an unreliable helpdesk while keeping accepted replies idempotent."""
    if payload.ticket_id != ticket_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ticket ID mismatch")

    existing = await session.scalar(
        select(MockHelpdeskReply).where(
            (MockHelpdeskReply.ticket_id == ticket_id)
            | (idempotency_key is not None and MockHelpdeskReply.idempotency_key == idempotency_key),
        ),
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reply already accepted")

    outcome = _RANDOM.random()
    if outcome < settings.mock_failure_rate:
        failure_status = (
            status.HTTP_502_BAD_GATEWAY
            if _RANDOM.random() < _FAILURE_SPLIT
            else status.HTTP_504_GATEWAY_TIMEOUT
        )
        raise HTTPException(status_code=failure_status, detail="Simulated upstream failure")
    timed_out = outcome < settings.mock_failure_rate + settings.mock_timeout_rate

    statement = insert(MockHelpdeskReply).values(
        ticket_id=ticket_id,
        idempotency_key=idempotency_key,
        message=payload.message,
    ).on_conflict_do_nothing()
    result = cast(CursorResult[Any], await session.execute(statement))
    await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reply already accepted")
    if timed_out:
        await asyncio.sleep(settings.mock_timeout_seconds)
    return MockHelpdeskReplyResponse(ticket_id=ticket_id, accepted=True)


@router.get("/replies", response_model=list[MockHelpdeskReplyResponse])
async def list_replies(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MockHelpdeskReplyResponse]:
    replies = list((await session.scalars(select(MockHelpdeskReply).order_by(MockHelpdeskReply.created_at))).all())
    return [MockHelpdeskReplyResponse(ticket_id=reply.ticket_id, accepted=True) for reply in replies]
