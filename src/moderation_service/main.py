from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from moderation_service.api.mock_helpdesk import router as mock_helpdesk_router
from moderation_service.api.operator import router as operator_router
from moderation_service.api.webhooks import router as webhooks_router
from moderation_service.config import settings
from moderation_service.database import async_session_factory, close_db, init_db
from moderation_service.services.kb_search import seed_knowledge_base
from moderation_service.services.workers import WorkerSupervisor

worker_supervisor = WorkerSupervisor()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    await init_db()
    async with async_session_factory() as session:
        await seed_knowledge_base(session)
    await worker_supervisor.start()
    try:
        yield
    finally:
        await worker_supervisor.stop()
        await close_db()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(webhooks_router)
app.include_router(mock_helpdesk_router)
app.include_router(operator_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
