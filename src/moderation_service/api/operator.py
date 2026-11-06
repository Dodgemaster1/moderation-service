from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from moderation_service.database import get_session
from moderation_service.models import Ticket, TicketStatus, WebhookEvent

router = APIRouter(tags=["operator"])
templates = Jinja2Templates(directory="src/moderation_service/templates")


class ApproveTicketRequest(BaseModel):
    draft_reply: str | None = Field(default=None, min_length=1)


class SimulationRequest(BaseModel):
    mode: Literal["single", "duplicate", "burst"] = "single"
    count: int = Field(default=10, ge=1, le=500)


@router.get("/")
async def operator_dashboard(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: TicketStatus | None = None,
) -> Response:
    query = select(Ticket).order_by(Ticket.created_at.desc())
    if status_filter is not None:
        query = query.where(Ticket.status == status_filter)
    tickets = list((await session.scalars(query.limit(100))).all())
    counts = {
        status.value: count
        for status, count in (await session.execute(select(Ticket.status, func.count()).group_by(Ticket.status))).all()
    }
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "tickets": tickets,
            "counts": counts,
            "statuses": list(TicketStatus),
            "active_status": status_filter.value if status_filter else "",
        },
    )


@router.post("/api/tickets/{ticket_id}/approve")
async def approve_ticket(
    ticket_id: str,
    payload: ApproveTicketRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    ticket = await session.scalar(select(Ticket).where(Ticket.ticket_id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if ticket.status != TicketStatus.DRAFT_READY:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ticket is not ready for approval")
    if payload.draft_reply is not None:
        ticket.draft_reply = payload.draft_reply
    ticket.status = TicketStatus.APPROVED
    await session.commit()
    return {"ticket_id": ticket_id, "status": ticket.status.value}


@router.post("/api/tickets/{ticket_id}/reject")
async def reject_ticket(
    ticket_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    ticket = await session.scalar(select(Ticket).where(Ticket.ticket_id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if ticket.status not in {TicketStatus.DRAFT_READY, TicketStatus.FAILED}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ticket cannot be rejected in this state")
    ticket.status = TicketStatus.REJECTED
    await session.commit()
    return {"ticket_id": ticket_id, "status": ticket.status.value}


@router.post("/mock-helpdesk/trigger-webhook")
async def trigger_webhook(
    payload: SimulationRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, int | str]:
    total = 1 if payload.mode in {"single", "duplicate"} else payload.count
    ticket_id = f"SIM-{await _next_simulation_number(session)}"
    event_ids = [f"sim-{ticket_id.lower()}-{index}" for index in range(total)]
    if payload.mode == "duplicate":
        event_ids = [event_ids[0]] * payload.count

    for index, event_id in enumerate(event_ids):
        simulated_ticket_id = ticket_id if payload.mode == "duplicate" else f"{ticket_id}-{index}"
        ticket_insert = (
            insert(Ticket)
            .values(
                ticket_id=simulated_ticket_id,
                customer_email="operator-simulation@example.com",
                message="How do I export a dashboard report to PDF?",
                reply_url=str(request.base_url).rstrip("/") + f"/mock-helpdesk/tickets/{simulated_ticket_id}/replies",
                status=TicketStatus.NEW,
            )
            .on_conflict_do_nothing(index_elements=[Ticket.ticket_id])
        )
        await session.execute(ticket_insert)
        event_insert = (
            insert(WebhookEvent)
            .values(
                event_id=event_id,
                ticket_id=simulated_ticket_id,
            )
            .on_conflict_do_nothing(index_elements=[WebhookEvent.event_id])
        )
        await session.execute(event_insert)
    await session.commit()
    return {"mode": payload.mode, "created": total if payload.mode == "burst" else 1}


async def _next_simulation_number(session: AsyncSession) -> int:
    count = await session.scalar(select(func.count()).select_from(Ticket))
    return int(count or 0) + 1
