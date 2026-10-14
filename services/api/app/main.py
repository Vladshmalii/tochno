import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .catalog import DEFAULT_PLANS
from .config import get_settings
from .core import webhooks  # noqa: F401 — реєструє обробник задачі "webhook"
from .core.jobs import Worker, recover_stuck_jobs
from .db import Base, SessionLocal, engine
from .models import Plan, Tenant, User
from .modules import registry
from .modules.docs_extract import pipeline  # noqa: F401 — реєструє обробник "process_document"
from .routers import admin, auth, contractors, documents, integrations, knowledge, meta, settings
from .security import hash_password

logger = logging.getLogger("tochno")
registry.load_all()


def seed(db) -> None:
    """Ідемпотентне початкове наповнення: тарифи + перший адміністратор платформи."""
    existing = {p.code: p for p in db.scalars(select(Plan))}
    for p in DEFAULT_PLANS:
        if p["code"] not in existing:
            db.add(Plan(**p))
    s = get_settings()
    if not db.scalar(select(User).where(User.role == "platform_admin")):
        password = s.bootstrap_admin_password
        if not password:
            password = secrets.token_urlsafe(12)
            logger.warning("Створено адміна платформи %s з ВИПАДКОВИМ паролем: %s (змініть/збережіть)",
                           s.bootstrap_admin_email, password)
        db.add(User(email=s.bootstrap_admin_email.lower(), password_hash=hash_password(password),
                    full_name="Platform Admin", role="platform_admin"))
    for t in db.scalars(select(Tenant).where(Tenant.intake_token.is_(None))):
        t.intake_token = secrets.token_urlsafe(24)
    db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    s.validate_for_runtime()
    registry.load_all()
    if s.app_env != "prod":
        Base.metadata.create_all(engine)  # dev/тести; у проді схему веде `alembic upgrade head` перед стартом
    with SessionLocal() as db:
        seed(db)
    worker = None
    if s.worker_enabled:
        recover_stuck_jobs()
        worker = Worker()
        worker.start()
    yield
    if worker:
        worker.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Tochno API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_list, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    for r in (meta.router, auth.router, documents.router, contractors.router, integrations.router,
              knowledge.router, settings.router, admin.router):
        app.include_router(r)
    return app


app = create_app()
