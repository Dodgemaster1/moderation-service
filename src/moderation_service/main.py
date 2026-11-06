from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from moderation_service.config import settings
from moderation_service.database import async_session_factory, close_db, init_db
from moderation_service.services.kb_search import seed_knowledge_base


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    await init_db()
    async with async_session_factory() as session:
        await seed_knowledge_base(session)
    try:
        yield
    finally:
        await close_db()


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
