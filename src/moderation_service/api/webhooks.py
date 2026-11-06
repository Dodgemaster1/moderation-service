from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from moderation_service.database import get_session
from moderation_service.models import Ticket, TicketStatus, WebhookEvent
from moderation_service.schemas import HelpdeskWebhookPayload, HelpdeskWebhookResponse

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post(
    "/helpdesk",
    response_model=HelpdeskWebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_helpdesk_webhook(
    payload: HelpdeskWebhookPayload,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HelpdeskWebhookResponse:
    """Persist a helpdesk event and ticket without doing any slow processing."""
    existing_event = await session.scalar(
        select(WebhookEvent.event_id).where(WebhookEvent.event_id == payload.event_id),
    )
    if existing_event is not None:
        return HelpdeskWebhookResponse(accepted=True, duplicate=True)

    ticket_insert = insert(Ticket).values(
        ticket_id=payload.ticket_id,
        customer_email=payload.customer_email,
        message=payload.message,
        reply_url=str(payload.reply_url),
        status=TicketStatus.NEW,
    )
    ticket_insert = ticket_insert.on_conflict_do_nothing(
        index_elements=[Ticket.ticket_id],
    )
    ticket_result = cast(CursorResult[Any], await session.execute(ticket_insert))
    if ticket_result.rowcount == 0:
        await session.commit()
        return HelpdeskWebhookResponse(accepted=True, duplicate=True)

    event_insert = insert(WebhookEvent).values(
        event_id=payload.event_id,
        ticket_id=payload.ticket_id,
    )
    event_insert = event_insert.on_conflict_do_nothing(
        index_elements=[WebhookEvent.event_id],
    )
    result = cast(CursorResult[Any], await session.execute(event_insert))
    await session.commit()

    return HelpdeskWebhookResponse(accepted=True, duplicate=result.rowcount == 0)
