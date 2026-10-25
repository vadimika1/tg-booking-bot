# TG Booking Bot (MVP)

Telegram-бот для заявок и записи (MVP): bot + admin API + worker. Слоты и услуги, лист ожидания, отмена и перенос, напоминания, ежедневный отчёт администратору, русский и английский.

A Telegram booking bot (MVP): bot, admin API and worker. Slots and services, a waitlist, cancel and reschedule, reminders, a daily admin report, Russian and English.

Автор: [Вадим Антонович](https://vadim.tabletools.ru). Клиенты в демо-данных вымышленные.

## Stack

- Python 3.9+
- aiogram 3 (bot)
- FastAPI (admin/api)
- PostgreSQL 16
- Redis 7
- SQLAlchemy 2 + Alembic

## Структура

```text
tg-booking-bot/
  app/
    bot/
    api/
    application/
    domain/
    infrastructure/
    worker/
  docs/
  scripts/
  migrations/
  tests/
  docker/
  .github/workflows/
  Makefile
  .env.example
  .env.local.example
  .env.staging.example
  docker-compose.yml
  pyproject.toml
```

## Быстрый старт

1. Подготовить переменные окружения (Docker-профиль):

```bash
cp .env.example .env
```

2. Запустить контейнеры:

```bash
docker compose up --build -d
```

3. Применить миграции:

```bash
docker compose run --rm api alembic upgrade head
```

4. Проверить API:

- Health: `GET http://localhost:8000/health`
- Docs: `http://localhost:8000/docs`

5. Проверить цикл миграций (upgrade/downgrade/upgrade):

```bash
make migrate-check
```

6. Заполнить демо-данные (услуги + рабочие часы):

```bash
make seed-demo
```

Если нужен полный демо-набор (пользователи, записи разных статусов, лист ожидания, уведомления, audit log):

```bash
make seed-full
```

Примечание: integration/e2e тесты очищают таблицы, после `pytest` выполните `make seed-demo` повторно.

7. Проверить Telegram-конфиг и готовность демо:

```bash
make check-telegram
make demo-ready
```

## Локальный запуск без Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.local.example .env
alembic upgrade head
api
```

Отдельные процессы:

```bash
bot
worker
```

## Профили окружения

- `.env.example` - Docker/local compose профиль (`POSTGRES_HOST=postgres`).
- `.env.local.example` - локальный запуск с хоста (`127.0.0.1:5433`).
- `.env.staging.example` - шаблон для staging.
- `.env.staging` - рабочий staging-файл (игнорируется Git), создается командой `make prepare-staging-env`.

Опционально для визуала бота:

- `TELEGRAM_STICKER_WELCOME` - стикер приветствия.
- `TELEGRAM_STICKER_BOOKED` - стикер после успешной записи.
- `TELEGRAM_STICKER_CANCELLED` - стикер после отмены записи.

Если ID стикера не задан, бот отправит fallback-анимацию `dice`.

Настройки ежедневного отчета менеджеру:

- `WORKER_DAILY_REPORT_ENABLED` - включить/выключить ежедневный отчет (`true/false`).
- `WORKER_DAILY_REPORT_HOUR` - час отправки отчета по `TIMEZONE` (0-23).
- `WORKER_DAILY_REPORT_MINUTE` - минута отправки отчета (0-59).

## Админ-команды в канале

1. Добавьте бота в канал как администратора с правом публикации и удаления сообщений.
2. Укажите ID канала в `TELEGRAM_MANAGER_CHAT_IDS` (пример: `-1001234567890`).
3. Используйте команды прямо в канале:

- Справка: `/admin_help`
- Статусы записи: `/admin_confirm <booking_id>`, `/admin_done <booking_id>`, `/admin_noshow <booking_id>`
- Отмена записи: `/admin_cancel <booking_id> | <причина>`
- Удобный режим: ответьте на карточку записи и отправьте `/admin_cancel <причина>`
- Через reply на карточку также работают `/admin_confirm`, `/admin_done`, `/admin_noshow`
- Управление услугами:
`/admin_services`
`/admin_service_add Название | 60 | 2500`
`/admin_service_edit <service_id> | Название | 60 | 2500 | 1`
`/admin_service_delete <service_id>`
- Управление календарём:
`/admin_hours`
`/admin_hours_set Пн | 09:00 | 18:00`
`/admin_hours_off Вс`
`/admin_hours_delete Вс`

Команда админа автоматически удаляется после обработки, чтобы канал оставался чистым.

## Документы этапов

- `docs/scope.md` (`AN-01`): ниша демо, 6 услуг, рабочие часы.
- `docs/business-rules.md` (`AN-02`): роли, статусы, правила отмены/no-show.
- `docs/secret-policy.md` (`INF-03`): правила хранения/ротации секретов.
- `docs/demo-scenario.md` (`DOC-01`): пошаговый сценарий демонстрации.
- `docs/portfolio-draft.md` (`DOC-01`): черновик кейса для портфолио.

## CI/CD (REL-01)

- Workflow: `.github/workflows/ci-cd.yml`
- Pipeline: `lint -> tests -> build -> deploy_staging`
- При падении deploy запускается `scripts/rollback_staging.sh`

Если работаем без GitHub, используйте локальный прогон готовности:

```bash
make local-ready
```

### Секреты для staging deploy

- `STAGING_HOST`
- `STAGING_USER`
- `STAGING_SSH_KEY`
- `STAGING_PORT` (обычно `22`)
- `STAGING_PROJECT_DIR` (например, `/opt/tg-booking-bot`)
- `STAGING_HEALTHCHECK_URL` (например, `http://127.0.0.1:8000/health`)

Автоматическая установка secrets через GitHub CLI:

```bash
export STAGING_HOST=...
export STAGING_USER=...
export STAGING_SSH_KEY='...'
export STAGING_PORT=22
export STAGING_PROJECT_DIR=/opt/tg-booking-bot
export STAGING_HEALTHCHECK_URL=http://127.0.0.1:8000/health
bash scripts/setup_github_secrets.sh <owner/repo>
```

Если GitHub пока не используется, этот шаг можно пропустить.

## Реализовано

- Каркас проекта `bot/api/worker`.
- API `services`, `bookings`, `slots`, `metrics`, `health`.
- Для админа: `POST /api/bookings/{id}/admin-cancel` с обязательной причиной + уведомление клиенту.
- Алгоритм генерации свободных слотов с учетом буфера и занятых интервалов.
- FSM-поток бота: услуга -> дата -> слот -> контакт -> подтверждение -> мои записи/отмена.
- Выбор языка интерфейса при старте (`RU/EN`) + смена языка через кнопку `🌐 Язык`.
- Локализация клиентского потока и напоминаний (`RU/EN`) с сохранением языка в профиле пользователя.
- Быстрая запись: кнопка `⚡ Быстрая запись` использует последнюю услугу клиента как шаблон.
- Перенос записи клиентом из раздела `Мои записи` (новая дата/время, пересчет напоминаний).
- Лист ожидания: если на выбранную дату нет слотов, клиент может встать в очередь, менеджер получает уведомление.
- Напоминания клиенту с кнопками `✅ Приду` / `❌ Не приду`.
- Модели БД MVP и Alembic migration.
- Worker: напоминания `24h/2h`, ретраи `5/15/30`, пометка `failed`, ежедневный отчет менеджеру.
- Unit + integration + e2e smoke тесты критического пути.
- Docker Compose для `postgres/redis/api/bot/worker`.
