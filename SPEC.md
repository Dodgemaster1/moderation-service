# Technical Specification: AI Helpdesk Draft & Moderation Service

## 1. Огляд системи
Бекенд-сервіс для автоматизації першої лінії підтримки. Приймає звернення (тікети) через вебхук від хелпдеску, шукає релевантні статті у локальній базі знань (RAG), генерує чернетку відповіді через LLM з урахуванням лімітів (60 RPM), надає веб-інтерфейс оператору для модерації (Approve/Reject) і надійно доставляє підтверджену відповідь назад у хелпдеск.

## 2. Технологічний стек
- **Мова та Фреймворк:** Python 3.14, FastAPI, Uvicorn
- **База даних:** PostgreSQL 18 + SQLAlchemy 2.0 (Async) + `psycopg` + Alembic (або автоініціалізація схем при старті)
- **HTTP-клієнт:** `httpx` (асинхронний)
- **Черга та воркери:** Аснинхронні фонові воркери на базі PostgreSQL + tasqkiq. *Примітка: Використання Postgres як черги гарантує відсутність втрати даних (ACID) і зменшує кількість інфраструктурних компонентів для деплою.*
- **Фронтенд (UI оператора):** Server-Side Rendering (Jinja2) + HTMX + Tailwind CDN (мінімалістичний інтерфейс без складного білду).
- **Контейнеризація:** Docker & Docker Compose.

## 3. Архітектурні вимоги та вирішення Edge Cases

### 3.1. Прийом вебхуків (`POST /webhooks/helpdesk`)
- **SLA < 2 секунд:** Ендпоінт НЕ виконує звернень до LLM. Він лише валідує вхідний JSON, зберігає подію/тікет у БД у статусі `NEW` і миттєво повертає `200 OK` (або `202 Accepted`). Час відповіді: ~5–20 мс.
- **Ідемпотентність та конкурентні дублікати:** 
  - Та сама подія (`event_id`) або тікет (`ticket_id`) можуть прийти одночасно в кількох потоках.
  - Рішення: Унікальні індекси в БД на `tickets.ticket_id` та `webhook_events.event_id`. Використання `INSERT INTO ... ON CONFLICT DO NOTHING`. Якщо це дублікат — повертаємо `200 OK` без повторної постановки в чергу.
- **Пікове навантаження (500 звернень за 10 хвилин):**
  - 500 запитів за 10 хв = у середньому 50 запитів/хв (0.83 RPS, у піках до кількох десятків RPS).
  - Асинхронний запис у Postgres легко витримує >1000 RPS. Всі 500 тікетів миттєво лягають у таблицю `tickets` зі статусом `NEW` і поступово обробляються воркером зі швидкістю до 60 тікетів/хвилину. Жодне звернення не втрачається.

### 3.2. База знань (Knowledge Base) та Пошук (RAG)
- **Продукт:** Вигаданий B2B SaaS-сервіс аналітики **"MetricFlow"** (дашборди, експорт у PDF/CSV, білінг, API-ключі, інтеграція зі Slack, SSO, ліміти даних).
- **Обсяг:** 8 структурованих статей (зберігаються у JSON/Markdown файлі `data/knowledge_base.json` і завантажуються в таблицю `kb_articles` при старті). Кожна стаття має `id`, `title`, `url`, `content`, `keywords`.
- **Пошук:** Оскільки система повинна повноцінно працювати **без API-ключа**, векторні ембедінги через зовнішній API не підходять як єдиний механізм. Використовуємо комбінований пошук (PostgreSQL Full-Text Search / `ILIKE` + текстовий скоринг TF-IDF/BM25 по ключових словах та контенту на Python). Повертаємо Топ-2 або Топ-3 релевантні статті.

### 3.3. Генерація відповіді (LLM Worker)
- **Rate Limiting (60 RPM):** Глобальний лімітер на рівні сервісу (aiolimiter: максимум 60 запитів на 60 секунд).
- **Затримка (5–30 секунд):** Виклик до LLM є довгим, тому воркер працює конкурентно (наприклад, пул з 15–20 асинхронних тасок у `asyncio.Semaphore(20)`), але старт кожної таски проходить через Rate Limiter (60 RPM).
- **Режим без API-ключа (No-API-Key Mode) — КРИТИЧНА ВИМОГА:**
  1. Навіть якщо `OPENAI_API_KEY` не заданий або невалідний, сервіс **робить реальний HTTP POST запит** через `httpx` до ендпоінту провайдера (наприклад, `https://api.openai.com/v1/chat/completions` з заголовком `Authorization: Bearer dummy-key`).
  2. Засікається час виконання цього реального запиту (`elapsed`).
  3. Якщо ключ відсутній або провайдер повернув `401/403` (або іншу помилку авторизації при пустому ключі), сервіс обчислює залишок часу до випадкового значення `target_delay = random.uniform(5.0, 30.0)` і виконує `await asyncio.sleep(max(0, target_delay - elapsed))`.
  4. Після затримки формується якісна статична відповідь на основі знайдених у RAG статей (із підстановкою реальних назв статей та їх `url`).
  5. Якщо ж API-ключ валідний і реальний виклик виконався швидше за 5 секунд, додається штучний `sleep`, щоб вкластися у вимогу 5–30 секунд.

### 3.4. Модерація оператором (Web UI)
- Сторінка `GET /` (або `/operator`):
  - Відображає статистику (New, Generating, Ready for Review, Approved/Sending, Sent, Rejected, Failed).
  - Список тікетів із фільтрацією за статусом.
  - Для тікетів у статусі `DRAFT_READY`: показує повідомлення клієнта, згенеровану чернетку, список знайдених статей БЗ, кнопки **Approve (Підтвердити)** (з можливістю відредагувати текст чернетки перед відправкою) та **Reject (Відхилити)**.
  - Кнопка "Simulate Incoming Ticket" та "Simulate Peak Load" у UI (або через окремий скрипт) для зручної перевірки рев'юером.

### 3.5. Відправка відповіді клієнту та Надійність (Outbox / Delivery Worker)
- Після натискання **Approve** тікет переходить у статус `APPROVED`.
- Окремий фоновий процес (Delivery Worker) підхоплює тікети у статусі `APPROVED` (або `DELIVERY_RETRY`, де `next_retry_at <= NOW()`).
- **Запит:** `POST <reply_url>` з тілом `{"ticket_id": "...", "message": "..."}`.
- **Захист від дублювання відповіді клієнту:**
  - До заголовків запиту додається детермінований ключ ідемпотентності: `Idempotency-Key: reply-{ticket_id}`.
  - Воркер блокує рядок у БД через `FOR UPDATE SKIP LOCKED`, щоб жоден інший воркер не відправив цей самий тікет паралельно.
- **Обробка помилок (5xx та таймаути):**
  - Таймаут HTTP-запиту налаштовується на 5 секунд.
  - Очікуваний успішний статус: `201 Created` (також `200 OK` або `409 Conflict` від ідемпотентного хелпдеску трактується як успішна доставка, якщо хелпдеск вже прийняв запит раніше).
  - При `5xx`, `429` або `httpx.TimeoutException / RequestError`: збільшується `retry_count`, обчислюється `next_retry_at` за алгоритмом Exponential Backoff + Jitter (`2^retry_count` секунд), статус змінюється на `DELIVERY_RETRY`. Після N спроб (наприклад, 10) — статус `DELIVERY_FAILED` з можливістю ручного ретраю в UI.

### 3.6. Мок Хелпдеску (Mock Helpdesk)
Вбудований у FastAPI роутер `/mock-helpdesk` (або `http://localhost:8000/mock-helpdesk/tickets/{ticket_id}/replies`), який імітує поведінку реального хелпдеску:
- Ендпоінт `POST /mock-helpdesk/tickets/{ticket_id}/replies`:
  - Має налаштовуваний режим нестабільності (за замовчуванням: ~20% шанс повернути `502 Bad Gateway`, ~10% шанс зависнути на 6 секунд і викликати таймаут клієнта, 70% — успішно обробити і повернути `201 Created`).
  - Зберігає отримані відповіді у таблицю `mock_helpdesk_replies` з унікальним обмеженням на `ticket_id` / `Idempotency-Key`, гарантуючи, що клієнт ніколи не отримає дублікат, навіть якщо таймаут стався після збереження.
  - Ендпоінт `GET /mock-helpdesk/replies` для перегляду доставлених клієнту повідомлень.

## 4. Схема Бази Даних (PostgreSQL)

1. **`kb_articles`**:
   - `id` (PK, String/Serial)
   - `title` (String)
   - `content` (Text)
   - `url` (String)
   - `keywords` (String/Array)

2. **`webhook_events`** (для дедуплікації подій):
   - `event_id` (PK, String, Unique)
   - `ticket_id` (String, Index)
   - `received_at` (DateTime)

3. **`tickets`**:
   - `id` (PK, UUID/Serial)
   - `ticket_id` (String, Unique, Index) — напр. "T-1042"
   - `customer_email` (String)
   - `message` (Text)
   - `reply_url` (String)
   - `status` (Enum: `NEW`, `GENERATING`, `DRAFT_READY`, `APPROVED`, `REJECTED`, `SENDING`, `DELIVERY_RETRY`, `SENT`, `FAILED`)
   - `draft_reply` (Text, nullable)
   - `referenced_articles` (JSONB, default `[]`)
   - `llm_mode` (String, nullable — `'real'` або `'fallback_static'`)
   - `generation_time_sec` (Float, nullable)
   - `retry_count` (Int, default 0)
   - `next_retry_at` (DateTime, nullable)
   - `last_error` (Text, nullable)
   - `created_at`, `updated_at` (DateTime)

4. **`mock_helpdesk_replies`** (для демонстрації роботи моку):
   - `id` (PK)
   - `ticket_id` (String, Unique)
   - `idempotency_key` (String, Unique, nullable)
   - `message` (Text)
   - `created_at` (DateTime)

## 5. API Ендпоінти
- `GET /health` -> `200 OK` `{"status": "ok"}`
- `POST /webhooks/helpdesk` -> Прийом тікета (< 2s)
- `GET /` -> Веб-інтерфейс оператора
- `POST /api/tickets/{ticket_id}/approve` -> Підтвердження чернетки та запуск доставки
- `POST /api/tickets/{ticket_id}/reject` -> Відхилення чернетки
- `POST /mock-helpdesk/tickets/{ticket_id}/replies` -> Мок-ендпоінт прийому відповідей (повертає `201 Created`, іноді `5xx`/таймаут)
- `POST /mock-helpdesk/trigger-webhook` -> Допоміжний ендпоінт у UI для генерації тестових вебхуків (одиночних, дублікатів або пачки).
- 