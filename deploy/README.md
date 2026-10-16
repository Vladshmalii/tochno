# Деплой docsai (Traefik + Docker + GHCR)

| Домен | Сервіс | Джерело |
|---|---|---|
| docsai.dvms.tech | landing | `apps/landing` |
| docsai-client.dvms.tech | client (кабінет) | `apps/client-web` |
| docsai-admin.dvms.tech | admin (адмінка) | `apps/admin-web` |
| docsai-backend.dvms.tech | api (FastAPI) + Postgres | `services/api` |

## Як працює CI/CD (`.github/workflows/ci.yml`)
1. Будь-який push/PR: тести API (`pytest`) і збірка фронтендів.
2. Push у `main`: 4 образи → `ghcr.io/<owner>/tochno-{api,client,admin,landing}:<sha>` і `:latest`.
   URL API/кабінету вшиваються у фронтенди під час збірки (Vite build args).
3. Деплой: `docker-compose.yml` і `deploy.sh` копіюються в `/opt/docsai`, далі `docker compose pull && up -d`,
   потім перевірка, що всі 4 домени відповідають 200.

Міграції Alembic застосовуються автоматично при старті контейнера api.

## Одноразове налаштування сервера
```bash
sudo mkdir -p /opt/docsai && sudo chown deploy:deploy /opt/docsai
# скопіювати deploy/.env.example → /opt/docsai/.env, заповнити, chmod 600
```
DNS: A-записи для всіх 4 доменів у Cloudflare (до першого деплою — інакше LE не видасть сертифікат).

## Secrets у GitHub (Settings → Environments → `production`)
| Secret | Значення |
|---|---|
| `SSH_HOST` | IP/хост сервера |
| `SSH_USER` | `deploy` (у групі `docker`) |
| `SSH_PRIVATE_KEY` | приватний ключ, публічний — в `~deploy/.ssh/authorized_keys` |
| `SSH_PORT` | необов'язково, за замовчуванням 22 |
| `SSH_KNOWN_HOSTS` | необов'язково: вивід `ssh-keyscan <host>`; без нього ключ хоста береться при кожному деплої |

GHCR-токен не потрібен: використовується `GITHUB_TOKEN` прогону, після pull виконується `docker logout`.

## Відкат
```bash
cd /opt/docsai
tail deploy-history.log                 # попередні sha
TAG=<sha> docker compose up -d          # образ уже є локально
```
