# Project Rules & Engineering Guidelines (AGENTS.md)

## Role & Context
Ти — Senior AI-first Backend Engineer. Ми розробляємо надійний сервіс обробки звернень у підтримку `moderation_service` на FastAPI + PostgreSQL. Детальна специфікація знаходиться у файлі `SPEC.md`, а план робіт — у `TODO.md`.

## Project Layout (`src` layout)
Проєкт використовує стандартний `src`-layout з назвою пакета `moderation_service`:
```text
.
├── AGENTS.md
├── SPEC.md
├── TODO.md
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── data/
│   └── knowledge_base.json
├── src/
│   └── moderation_service/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── database.py
│       ├── models.py
│       ├── schemas.py
│       ├── api/
│       │   ├── __init__.py
│       │   ├── webhooks.py
│       │   ├── operator.py
│       │   └── mock_helpdesk.py
│       ├── services/
│       │   ├── __init__.py
│       │   ├── kb_search.py
│       │   ├── llm_service.py
│       │   └── workers.py
│       └── templates/
│           └── index.html
└── tests/
    └── test_service.py
```

Усі абсолютні імпорти всередині пакета мають починатися з from moderation_service... (наприклад, from moderation_service.config import settings).
Core Rules

 Strict Requirement Adherence:
  - Вебхук POST /webhooks/helpdesk ПОВИНЕН відповідати швидше ніж за 2 секунди за будь-якого навантаження (жодних синхронних викликів LLM чи блокуючих операцій у хендлері).
  - Повна ідемпотентність при паралельних дублікатах: використовуй PostgreSQL INSERT ... ON CONFLICT DO NOTHING для event_id та ticket_id.
  - No-API-Key Mode: Якщо LLM_API_KEY не заданий або пустий, сервіс ВСЕ ОДНО робить реальний HTTP-запит через httpx.AsyncClient до API провайдера (наприклад, https://api.openai.com/v1/chat/completions), перехоплює помилку авторизації/мережі, дочікується випадкової затримки в діапазоні 5–30 секунд (разом із часом запиту) і повертає сформовану статичну відповідь із посиланнями на статті з бази знань.
  - Rate Limit: Глобальний ліміт викликів LLM — не більше 60 запитів на хвилину (60 RPM) на весь сервіс.
  - Reply Delivery (POST <reply_url>): Очікує 201 Created. Стійкість до 5xx та таймаутів через ретраї з Exponential Backoff. Передавай заголовок Idempotency-Key для гарантії того, що клієнт не отримає відповідь двічі.
  - Ендпоінт GET /health має повертати 200 OK.

 Code Style & Architecture:
  - Python 3.14, повна типізація, async/await всюди (SQLAlchemy 2.0 AsyncSession, psycopg§, httpx).
  - Використовуй PostgreSQL SELECT ... FOR UPDATE SKIP LOCKED для фонових воркерів, щоб уникнути race conditions.
  - Усе має підніматися однією командою docker compose up --build.
