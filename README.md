# MetricFlow Moderation Service

Асинхронний FastAPI-сервіс, який приймає звернення з helpdesk, ставить їх у PostgreSQL, знаходить статті MetricFlow, генерує чернетку для оператора та доставляє підтверджену відповідь назад через helpdesk API.

## Запуск

Потрібні Docker та Docker Compose:

```bash
docker compose up --build
```

Після запуску:

- операторський інтерфейс: http://localhost:8000/
- healthcheck: http://localhost:8000/health
- PostgreSQL: localhost:5432, база `moderation`, користувач `moderation`, пароль `moderation`

Для локального запуску в наявному virtualenv:

```bash
uv sync
uv run uvicorn moderation_service.main:app --reload
```

Налаштування можна передати через `.env` або змінні середовища. Основні змінні: `DATABASE_URL`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `HELPDESK_TIMEOUT_SECONDS`, `WORKER_CONCURRENCY` та параметри mock helpdesk. Приклад є у `.env.example`.

## Архітектура

`POST /webhooks/helpdesk` валідовує payload і атомарно зберігає подію та тікет через PostgreSQL `ON CONFLICT DO NOTHING`. Обробник не викликає LLM, тому відповідає до 2 секунд навіть коли генерація триває 5–30 секунд.

Фоновий worker із `FOR UPDATE SKIP LOCKED` шукає релевантні статті з `data/knowledge_base.json`, генерує чернетку та переводить тікет у `DRAFT_READY`. Глобальний `aiolimiter` обмежує LLM до 60 запитів на хвилину. Навіть без `LLM_API_KEY` виконується реальний HTTP-запит до налаштованого провайдера, після чого використовується відкладений статичний fallback із посиланнями на статті.

Оператор затверджує або відхиляє чернетку через UI. Worker доставки надсилає `POST <reply_url>` із `Idempotency-Key: reply-{ticket_id}`. Таймаути, 5xx і 429 отримують exponential backoff; mock helpdesk зберігає прийняту відповідь унікально за ticket або idempotency key.

## Приклади API

Прийняти звернення:

```bash
curl -X POST http://localhost:8000/webhooks/helpdesk \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": "evt_8f2a",
    "ticket_id": "T-1042",
    "customer_email": "user@example.com",
    "message": "Не можу експортувати звіт у PDF",
    "reply_url": "http://localhost:8000/mock-helpdesk/tickets/T-1042/replies"
  }'
```

Запустити симуляцію з UI/API:

```bash
curl -X POST http://localhost:8000/mock-helpdesk/trigger-webhook \
  -H 'Content-Type: application/json' \
  -d '{"mode":"burst","count":50}'
```

Прийняти відповідь у mock helpdesk:

```bash
curl -X POST http://localhost:8000/mock-helpdesk/tickets/T-1042/replies \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: reply-T-1042' \
  -d '{"ticket_id":"T-1042","message":"Відкрийте меню Export та виберіть PDF."}'
```

Переглянути доставлені відповіді:

```bash
curl http://localhost:8000/mock-helpdesk/replies
```

## Тести та перевірки

```bash
uv run pytest -q
uv run ruff check .
uv run ty check src
```

Тести перевіряють конкурентну дедуплікацію webhook-подій, швидке підтвердження webhook, `/health`, retry/backoff доставки та no-API-key fallback із фактичним HTTP-запитом.
