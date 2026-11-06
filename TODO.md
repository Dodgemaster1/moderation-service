# Implementation Checklist & Commit Plan

- [x] **Крок 1: Ініціалізація та конфігурація агента**
  - Створити структуру проєкту (`src/moderation_service`), `.gitignore`, `.env.example`, зберегти `SPEC.md`, `AGENTS.md`, `TODO.md`.
  - *Коміт:* `docs: add system specification, agent rules, and implementation checklist`

- [x] **Крок 2: Інфраструктура та База даних**
  - Написати `docker-compose.yml` (FastAPI + PostgreSQL 18).
  - Налаштувати `src/moderation_service/config.py` (Pydantic Settings) та `src/moderation_service/database.py` (Async SQLAlchemy).
  - Створити моделі `Ticket`, `WebhookEvent`, `KBArticle`, `MockHelpdeskReply` у `src/moderation_service/models.py`.
  - Реалізувати точку входу `src/moderation_service/main.py` та `GET /health` -> `200 OK`.
  - *Коміт:* `feat(core): setup FastAPI, PostgreSQL async models, healthcheck, and Docker Compose`

- [x] **Крок 3: База знань (KB) та пошуковий рушій (RAG)**
  - Згенерувати `data/knowledge_base.json` (8 статей про продукт MetricFlow з URL та ключовими словами).
  - Написати сідинг (seeding) бази знань при старті застосунку.
  - Реалізувати сервіс пошуку релевантних статей `src/moderation_service/services/kb_search.py` (пошук за ключовими словами та змістом українською/англійською мовами).
  - *Коміт:* `feat(kb): add fictional product knowledge base and relevant article search service`

- [ ] **Крок 4: Прийом вебхуків та ідемпотентність**
  - Реалізувати `POST /webhooks/helpdesk` у `src/moderation_service/api/webhooks.py` та схеми у `src/moderation_service/schemas.py`.
  - Додати атомарну обробку дублікатів через `INSERT ... ON CONFLICT DO NOTHING` (по `event_id` та `ticket_id`).
  - Гарантувати час відповіді < 50 мс (ліміт за умовою — 2 с).
  - *Коміт:* `feat(webhook): implement idempotent helpdesk webhook receiver with concurrency protection`

- [ ] **Крок 5: LLM клієнт (Rate Limiter 60 RPM + No-API-Key Mode)**
  - Реалізувати глобальний Rate Limiter на 60 запитів на хвилину (`src/moderation_service/services/rate_limiter.py`).
  - Реалізувати `src/moderation_service/services/llm_service.py`:
    - Формування промпту зі знайденими статтями та їх URL.
    - Реальний HTTP-запит до LLM провайдера навіть за відсутності ключа.
    - Обробка fallback-режиму без ключа: імітація затримки 5–30 секунд і генерація змістовної статичної чернетки з посиланнями на знайдені статті.
  - *Коміт:* `feat(llm): add LLM draft generator with 60 RPM limiter and real-request fallback mode`

- [ ] **Крок 6: Фонові воркери та Мок Хелпдеску (Відправка та Ретраї)**
  - Реалізувати Mock Helpdesk (`src/moderation_service/api/mock_helpdesk.py`: `POST /mock-helpdesk/tickets/{ticket_id}/replies`), який повертає `201 Created`, симулює періодичні `502`/`504`/таймаути та перевіряє `Idempotency-Key` для захисту клієнта від дублікатів.
  - Реалізувати у `src/moderation_service/services/workers.py` воркер генерації чернеток (`NEW` -> `GENERATING` -> `DRAFT_READY`) через `FOR UPDATE SKIP LOCKED`.
  - Реалізувати воркер доставки підтверджених відповідей (`APPROVED` / `DELIVERY_RETRY` -> `SENT`) з Exponential Backoff.
  - *Коміт:* `feat(workers): implement async DB-backed workers for LLM generation and reliable reply delivery`

- [ ] **Крок 7: Веб-інтерфейс оператора (Moderation UI)**
  - Створити роутер оператора `src/moderation_service/api/operator.py` та шаблон `src/moderation_service/templates/index.html` (`GET /`) на Jinja2 + HTMX/JS.
  - Додати перегляд списку звернень, тексту чернетки, прикріплених статей, статусів ретраїв.
  - Додати кнопки Approve (з можливістю редагування), Reject та панель симуляції вебхуків (Single, Duplicate Race Condition, Burst Load).
  - *Коміт:* `feat(ui): build operator moderation interface and simulation dashboard`

- [ ] **Крок 8: Тести, перевірка навантаження та Документація**
  - Написати автотести (`tests/test_service.py`): дедуплікація одночасних вебхуків, таймаут < 2с, ретраї при 5xx, робота без API-ключа.
  - Оформити детальний `README.md` з інструкцією запуску, описом архітектури та прикладами `curl`.
  - *Коміт:* `test & docs: add integration tests and comprehensive README`
