from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from secrets import SystemRandom

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from moderation_service.config import settings
from moderation_service.database import async_session_factory
from moderation_service.models import KBArticle, Ticket, TicketStatus
from moderation_service.services.kb_search import search_articles
from moderation_service.services.llm_service import DraftGenerationResult, generate_draft

MAX_DELIVERY_RETRIES = 10
_RANDOM = SystemRandom()


async def _claim_ticket(
    session: AsyncSession,
    statuses: tuple[TicketStatus, ...],
    *,
    retryable: bool = False,
) -> Ticket | None:
    query = select(Ticket).where(Ticket.status.in_(statuses))
    if retryable:
        query = query.where(
            or_(
                Ticket.status == TicketStatus.APPROVED,
                and_(
                    Ticket.status == TicketStatus.DELIVERY_RETRY,
                    Ticket.next_retry_at <= datetime.now(UTC),
                ),
            ),
        )
    ticket = (
        await session.execute(
            query.order_by(Ticket.created_at).with_for_update(skip_locked=True).limit(1),
        )
    ).scalar_one_or_none()
    if ticket is None:
        return None
    return ticket


async def process_generation_once() -> bool:
    async with async_session_factory() as session:
        ticket = await _claim_ticket(session, (TicketStatus.NEW,))
        if ticket is None:
            return False
        ticket.status = TicketStatus.GENERATING
        await session.commit()
        ticket_id = ticket.ticket_id
        message = ticket.message

    started = time.monotonic()
    try:
        articles, result = await _generate_ticket(message)
        await _save_generated_draft(ticket_id, articles, result, time.monotonic() - started)
    except Exception as error:
        async with async_session_factory() as session:
            current = await session.scalar(select(Ticket).where(Ticket.ticket_id == ticket_id))
            if current is not None:
                current.status = TicketStatus.FAILED
                current.last_error = str(error)[:2000]
                await session.commit()
    return True


async def _generate_ticket(message: str) -> tuple[list[KBArticle], DraftGenerationResult]:
    async with async_session_factory() as session:
        articles = await search_articles(session, message)
    return articles, await generate_draft(message, articles)


async def _save_generated_draft(
    ticket_id: str,
    articles: list[KBArticle],
    result: DraftGenerationResult,
    elapsed: float,
) -> None:
    article_data = [{"id": article.id, "title": article.title, "url": article.url} for article in articles]
    async with async_session_factory() as session:
        current = await session.scalar(select(Ticket).where(Ticket.ticket_id == ticket_id))
        if current is None or current.status != TicketStatus.GENERATING:
            return
        current.draft_reply = result.draft
        current.referenced_articles = article_data
        current.llm_mode = result.mode
        current.generation_time_sec = elapsed
        current.status = TicketStatus.DRAFT_READY
        current.last_error = None
        await session.commit()


async def process_delivery_once() -> bool:
    async with async_session_factory() as session:
        ticket = await _claim_ticket(session, (TicketStatus.APPROVED, TicketStatus.DELIVERY_RETRY), retryable=True)
        if ticket is None:
            return False
        ticket.status = TicketStatus.SENDING
        await session.commit()
        ticket_id, reply_url, message, retry_count = (
            ticket.ticket_id,
            ticket.reply_url,
            ticket.draft_reply,
            ticket.retry_count,
        )

    try:
        async with httpx.AsyncClient(timeout=settings.helpdesk_timeout_seconds) as client:
            response = await client.post(
                reply_url,
                json={"ticket_id": ticket_id, "message": message or ""},
                headers={"Idempotency-Key": f"reply-{ticket_id}"},
            )
        if response.status_code not in {200, 201, 409}:
            response.raise_for_status()
    except (httpx.HTTPError, TimeoutError) as error:
        await _record_delivery_failure(ticket_id, retry_count, str(error))
    else:
        async with async_session_factory() as session:
            current = await session.scalar(select(Ticket).where(Ticket.ticket_id == ticket_id))
            if current is not None:
                current.status = TicketStatus.SENT
                current.next_retry_at = None
                current.last_error = None
                await session.commit()
    return True


async def _record_delivery_failure(ticket_id: str, retry_count: int, error: str) -> None:
    async with async_session_factory() as session:
        current = await session.scalar(select(Ticket).where(Ticket.ticket_id == ticket_id))
        if current is None:
            return
        current.retry_count = retry_count + 1
        current.last_error = error[:2000]
        if current.retry_count >= MAX_DELIVERY_RETRIES:
            current.status = TicketStatus.FAILED
            current.next_retry_at = None
        else:
            delay = min(300.0, 2 ** current.retry_count) + _RANDOM.uniform(0, 1)
            current.status = TicketStatus.DELIVERY_RETRY
            current.next_retry_at = datetime.now(UTC) + timedelta(seconds=delay)
        await session.commit()


class WorkerSupervisor:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._tasks:
            return
        self._stopping.clear()
        self._tasks = [
            asyncio.create_task(self._loop(process_generation_once), name="draft-generation-worker"),
            asyncio.create_task(self._loop(process_delivery_once), name="reply-delivery-worker"),
        ]

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _loop(self, processor: Callable[[], Awaitable[bool]]) -> None:
        semaphore = asyncio.Semaphore(settings.worker_concurrency)
        while not self._stopping.is_set():
            async with semaphore:
                processed = await processor()
            if not processed:
                await asyncio.sleep(settings.worker_poll_seconds)
