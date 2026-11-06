from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from moderation_service.models import KBArticle

DEFAULT_KB_PATH = Path(__file__).resolve().parents[3] / "data" / "knowledge_base.json"
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "how", "in", "is", "it",
    "of", "on", "or", "the", "to", "в", "для", "і", "із", "на", "не", "чи", "як",
    "у", "та", "це",
}


class KnowledgeBaseRecord(TypedDict):
    id: str
    title: str
    url: str
    content: str
    keywords: list[str]


def load_knowledge_base(path: Path = DEFAULT_KB_PATH) -> list[KnowledgeBaseRecord]:
    """Load and validate the checked-in knowledge base document."""
    with path.open(encoding="utf-8") as file:
        records = json.load(file)
    if not isinstance(records, list) or not records:
        raise ValueError("Knowledge base must contain a non-empty JSON array")

    required = {"id", "title", "url", "content", "keywords"}
    validated: list[KnowledgeBaseRecord] = []
    for record in records:
        if not isinstance(record, dict) or not required.issubset(record):
            raise ValueError("Each knowledge-base article must contain id, title, url, content, and keywords")
        if not isinstance(record["keywords"], list):
            article_id = record["id"]
            message = f"Article {article_id} keywords must be an array"
            raise TypeError(message)
        validated.append(
            KnowledgeBaseRecord(
                id=str(record["id"]),
                title=str(record["title"]),
                url=str(record["url"]),
                content=str(record["content"]),
                keywords=[str(keyword) for keyword in record["keywords"]],
            )
        )
    return validated


async def seed_knowledge_base(
    session: AsyncSession,
    path: Path = DEFAULT_KB_PATH,
) -> int:
    """Upsert JSON articles and return the number of records processed."""
    records = load_knowledge_base(path)
    statement = insert(KBArticle).values(records)
    statement = statement.on_conflict_do_update(
        index_elements=[KBArticle.id],
        set_={
            "title": statement.excluded.title,
            "url": statement.excluded.url,
            "content": statement.excluded.content,
            "keywords": statement.excluded.keywords,
        },
    )
    await session.execute(statement)
    await session.commit()
    return len(records)


def _tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN_RE.findall(value)
        if len(token) > 1 and token.casefold() not in _STOP_WORDS
    }


def _score(article: KBArticle, query_tokens: set[str]) -> float:
    keyword_tokens = _tokens(" ".join(article.keywords))
    title_tokens = _tokens(article.title)
    content_tokens = _tokens(article.content)
    return (
        len(query_tokens & keyword_tokens) * 5.0
        + len(query_tokens & title_tokens) * 3.0
        + len(query_tokens & content_tokens)
    )


async def search_articles(
    session: AsyncSession,
    query: str,
    limit: int = 3,
) -> list[KBArticle]:
    """Return the highest-scoring articles for Ukrainian or English text."""
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    query_tokens = _tokens(query)
    if not query_tokens:
        return []

    articles = list((await session.scalars(select(KBArticle))).all())
    scored = [(article, _score(article, query_tokens)) for article in articles]
    scored = [(article, score) for article, score in scored if score > 0]
    scored.sort(key=lambda item: (-item[1], item[0].id))
    return [article for article, _ in scored[:limit]]
