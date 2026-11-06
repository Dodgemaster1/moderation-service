import asyncio
import time
from dataclasses import dataclass
from typing import Any, Self
from unittest.mock import patch

import httpx

from moderation_service.api.webhooks import receive_helpdesk_webhook
from moderation_service.main import health
from moderation_service.models import Ticket, TicketStatus
from moderation_service.schemas import HelpdeskWebhookPayload
from moderation_service.services import workers
from moderation_service.services.llm_service import LLMService


@dataclass
class _Result:
    rowcount: int


class _ConcurrentInsertSession:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.tickets: set[str] = set()
        self.events: set[str] = set()
        self.commits = 0

    async def scalar(self, _: Any) -> None:
        return None

    async def execute(self, statement: Any) -> _Result:
        table_name = statement.table.name
        values = statement.compile().params
        async with self._lock:
            target = self.tickets if table_name == Ticket.__tablename__ else self.events
            key = values["ticket_id"] if table_name == Ticket.__tablename__ else values["event_id"]
            if key in target:
                return _Result(0)
            target.add(key)
            return _Result(1)

    async def commit(self) -> None:
        self.commits += 1


def _payload(event_id: str = "evt-test") -> HelpdeskWebhookPayload:
    return HelpdeskWebhookPayload(
        event_id=event_id,
        ticket_id="T-test",
        customer_email="user@example.com",
        message="Не можу експортувати звіт у PDF",
        reply_url="https://helpdesk.example/replies",
    )


def test_concurrent_duplicate_webhooks_are_deduplicated() -> None:
    session = _ConcurrentInsertSession()

    async def run() -> list[Any]:
        return await asyncio.gather(
            *(
                receive_helpdesk_webhook(_payload(), session)
                for _ in range(25)
            ),
        )

    responses = asyncio.run(run())
    assert len(session.tickets) == 1
    assert len(session.events) == 1
    assert sum(response.duplicate for response in responses) == 24
    assert all(response.accepted for response in responses)


def test_webhook_acknowledgement_is_fast() -> None:
    session = _ConcurrentInsertSession()
    started = time.monotonic()
    response = asyncio.run(receive_helpdesk_webhook(_payload(), session))
    elapsed = time.monotonic() - started

    assert response.accepted
    assert elapsed < 2


def test_health_endpoint() -> None:
    assert asyncio.run(health()) == {"status": "ok"}


@dataclass
class _DeliveryTicket:
    ticket_id: str = "T-retry"
    retry_count: int = 0
    status: TicketStatus = TicketStatus.SENDING
    last_error: str | None = None
    next_retry_at: Any = None


class _SessionContext:
    def __init__(self, ticket: _DeliveryTicket) -> None:
        self.ticket = ticket

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def scalar(self, _: Any) -> _DeliveryTicket:
        return self.ticket

    async def commit(self) -> None:
        return None


def test_delivery_5xx_failure_schedules_exponential_retry() -> None:
    ticket = _DeliveryTicket()

    def factory() -> _SessionContext:
        return _SessionContext(ticket)

    with patch("moderation_service.services.workers.async_session_factory", factory):
        record_failure = workers._record_delivery_failure  # ruff: ignore[private-member-access]
        asyncio.run(record_failure(ticket.ticket_id, ticket.retry_count, "502 Bad Gateway"))

    assert ticket.status == TicketStatus.DELIVERY_RETRY
    assert ticket.retry_count == 1
    assert ticket.next_retry_at is not None
    assert ticket.last_error == "502 Bad Gateway"


def test_no_api_key_still_requests_provider_and_uses_static_fallback() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = LLMService(
        api_key="",
        base_url="https://provider.test/chat",
        client=client,
        timeout_seconds=1,
    )
    with patch("moderation_service.services.llm_service._RANDOM.uniform", return_value=0.0):
        result = asyncio.run(service.generate_draft("Як експортувати PDF?", []))
    asyncio.run(client.aclose())

    assert requests
    assert requests[0].url == "https://provider.test/chat"
    assert result.mode == "fallback_static"
    assert "Релевантних статей не знайдено" in result.draft
