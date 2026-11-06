from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from secrets import SystemRandom
from typing import Any

import httpx

from moderation_service.config import settings
from moderation_service.models import KBArticle
from moderation_service.services.rate_limiter import LLM_RATE_LIMITER

_RANDOM = SystemRandom()


@dataclass(frozen=True, slots=True)
class DraftGenerationResult:
    """Generated draft and metadata needed by the ticket worker."""

    draft: str
    mode: str
    elapsed_seconds: float


class LLMService:
    """Generate support drafts through an OpenAI-compatible chat-completions API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = settings.llm_api_key if api_key is None else api_key
        self.base_url = settings.llm_base_url if base_url is None else base_url
        self.model = settings.llm_model if model is None else model
        self.timeout_seconds = (
            settings.llm_timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        self._client = client

    async def generate_draft(
        self,
        message: str,
        articles: list[KBArticle],
    ) -> DraftGenerationResult:
        """Generate a draft, using a delayed article-backed fallback when necessary."""
        prompt = self.build_prompt(message, articles)
        started = time.monotonic()
        async with LLM_RATE_LIMITER:
            response_text: str | None = None
            request_error: Exception | None = None
            try:
                response_text = await self._request(prompt)
            except (httpx.HTTPError, TimeoutError) as error:
                request_error = error

        elapsed = time.monotonic() - started
        target_delay = _RANDOM.uniform(5.0, 30.0)
        if elapsed < target_delay:
            await asyncio.sleep(target_delay - elapsed)

        if response_text and self.api_key:
            return DraftGenerationResult(response_text, "real", time.monotonic() - started)

        # request_error is intentionally retained for debugging without exposing provider
        # credentials or making the fallback dependent on provider availability.
        del request_error
        return DraftGenerationResult(
            self.static_fallback(message, articles),
            "fallback_static",
            time.monotonic() - started,
        )

    async def _request(self, prompt: str) -> str | None:
        """Make the provider request even when the configured API key is empty."""
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a support agent. Answer in the customer's language, "
                        "be concise, and only use the supplied knowledge-base articles."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self._client is not None:
            response = await self._client.post(
                self.base_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            return self._extract_content(response.json())

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        response.raise_for_status()
        return self._extract_content(response.json())

    @staticmethod
    def build_prompt(message: str, articles: list[KBArticle]) -> str:
        """Build a grounded prompt containing article titles, content, and URLs."""
        sources = "\n\n".join(
            f"Article: {article.title}\nURL: {article.url}\nContent: {article.content}"
            for article in articles
        )
        return f"Customer message:\n{message}\n\nKnowledge base:\n{sources or 'No matching articles found.'}"

    @staticmethod
    def static_fallback(message: str, articles: list[KBArticle]) -> str:
        """Return a useful deterministic answer when the provider is unavailable."""
        links = "\n".join(f"- {article.title}: {article.url}" for article in articles)
        if articles:
            guidance = (
                "Будь ласка, скористайтеся наведеними інструкціями з бази знань. "
                "Якщо проблема залишиться, надішліть додаткові деталі."
            )
        else:
            guidance = "Оператор перевірить це питання та надасть додаткові інструкції."
        sources = links or "- Релевантних статей не знайдено."
        return f"Дякуємо за звернення щодо: «{message}».\n\n{guidance}\n\nКорисні статті:\n{sources}"

    @staticmethod
    def _extract_content(payload: Any) -> str | None:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        return content.strip() if isinstance(content, str) and content.strip() else None


async def generate_draft(message: str, articles: list[KBArticle]) -> DraftGenerationResult:
    """Convenience entry point for workers and simple integrations."""
    return await LLMService().generate_draft(message, articles)
