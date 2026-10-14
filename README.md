# Tochno

Мультитенантная SaaS-платформа для AI-обработки документов и бухгалтерии. Функционал подключается клиентам модулями (через тариф или индивидуально из админки).

```
services/api        FastAPI: auth, тенанты, модули/тарифы, docs_extract, контрагенты, админ-API
apps/client-web     React+TS: кабинет клиента          (порт 5173)
apps/admin-web      React+TS: админка платформы        (порт 5174)
apps/landing        статический рекламный лендинг
packages/shared     API-клиент, типы, дизайн-токены (общие для обоих фронтендов)
```

## Запуск (dev)

```
cd services/api
python -m venv ../../.venv && ../../.venv/Scripts/pip install -r requirements.txt
cp .env.example .env        # LLM_PROVIDER=mock работает без ключа (демо-распознавание)
../../.venv/Scripts/python -m uvicorn app.main:app --reload     # :8000
```
Первый админ платформы создаётся при старте (`BOOTSTRAP_ADMIN_*`); если пароль не задан — генерируется и пишется в лог.

```
npm install
npm run dev:client      # кабинет
npm run dev:admin       # админка
```
Лендинг: открыть `apps/landing/index.html`; адрес кабинета в проде задаётся `window.APP_URL`.

Тесты API: `cd services/api && pytest`.

## Модули
`docs_extract` (счета/акты/накладные, проверка ЄДРПОУ/ІПН/IBAN, дубли, подмена IBAN), `reconcile` (справочник контрагентов),
`reports` (выписка, баланс, ОПУ с показателями), `identity` (паспорт/ID/ИНН, MRZ), `knowledge` (RAG-ассистент, BM25).
Новый тип документа = один файл в `app/modules/<модуль>/types.py` + `register(DocType(...))`.

## Автоматизация и интеграции
Авто-затверждение «чистых» документов, массовое затверждение, конвейер проверки («Затвердити і далі»), экспорт CSV/XLSX,
API-ключи (`X-API-Key`), вебхуки с HMAC, intake-URL (почта/Zapier/Make), Telegram-бот (`PUBLIC_API_URL` должен быть
публичным https-адресом API), вход под клиентом из админки (журналируется, токен на 30 мин).

## Полный стек в Docker
```
cp .env.example .env     # POSTGRES_PASSWORD, SECRET_KEY, PUBLIC_API_URL ...
docker compose up -d --build
```
API :8000, кабинет :8080, админка :8081, лендинг :8082 (настройки лендинга — `apps/landing/config.js`).
Тесты на Postgres: `TEST_DATABASE_URL=postgresql+psycopg://... pytest`.

## Реальный LLM
`LLM_PROVIDER=openai`, `OPENAI_API_KEY=...`. Провайдеры — `app/modules/docs_extract/llm.py`.

## Что осталось до продакшена
- Биллинг/оплата, white-label, SSO.
- Токен Telegram-бота хранится в БД открытым текстом — перед продом шифровать (Fernet/KMS).
- Rate-limit логина in-memory (один процесс) — для нескольких инстансов вынести в Redis; сброс пароля по email.
- Очередь и воркер работают в процессе API; при росте нагрузки вынести воркер отдельным контейнером.
- JWT в localStorage — перейти на httpOnly-cookie; HTTPS/реверс-прокси перед сервисами.
- Приём почты по IMAP (сейчас через intake-URL + Zapier/Make).
