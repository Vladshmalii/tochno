import re
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.ratelimit import login_limiter
from ..db import get_db
from ..deps import audit, current_tenant_user, current_user, require_roles
from ..models import AuditLog, Plan, Tenant, User, utcnow
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/api", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


class SignupIn(BaseModel):
    company: str = Field(min_length=2, max_length=200)
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class MeOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    tenant_id: Optional[int]
    tenant_name: Optional[str]
    plan: Optional[str]
    modules: List[str]
    trial_ends_at: Optional[datetime] = None


def me_out(u: User) -> MeOut:
    t = u.tenant
    return MeOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role, tenant_id=u.tenant_id,
                 tenant_name=t.name if t else None, plan=t.plan.code if t else None,
                 modules=t.enabled_modules() if t else [],
                 trial_ends_at=t.trial_ends_at if t and t.plan.code == "trial" else None)


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "client"
    return base[:60]


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    key = f"{request.client.host if request.client else '?'}|{email}"
    if login_limiter.blocked(key, get_settings().login_max_attempts):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Забагато невдалих спроб. Спробуйте за 15 хвилин")
    user = db.scalar(select(User).where(User.email == email))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        login_limiter.fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невірний email або пароль")
    login_limiter.reset(key)
    user.last_login_at = utcnow()
    db.commit()
    return {"access_token": create_token(user.id), "token_type": "bearer", "user": me_out(user)}


@router.post("/auth/signup", status_code=201)
def signup(body: SignupIn, db: Session = Depends(get_db)):
    if not get_settings().allow_signup:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Самореєстрацію вимкнено")
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Користувач з таким email вже існує")
    plan = db.scalar(select(Plan).where(Plan.code == "trial"))
    slug = _slugify(body.company)
    if db.scalar(select(Tenant).where(Tenant.slug == slug)):
        slug = f"{slug}-{secrets.token_hex(2)}"
    tenant = Tenant(name=body.company, slug=slug, plan_id=plan.id, contact_email=email,
                    trial_ends_at=utcnow() + timedelta(days=get_settings().trial_days),
                    intake_token=secrets.token_urlsafe(24))
    db.add(tenant)
    db.flush()
    user = User(tenant_id=tenant.id, email=email, password_hash=hash_password(body.password),
                full_name=body.full_name, role="owner")
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"access_token": create_token(user.id), "token_type": "bearer", "user": me_out(user)}


@router.get("/auth/me", response_model=MeOut)
def me(user: User = Depends(current_user)):
    return me_out(user)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/auth/change-password", status_code=204)
def change_password(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Поточний пароль невірний")
    user.password_hash = hash_password(body.new_password)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="auth.password.change", entity="user",
                    entity_id=str(user.id)))
    db.commit()


# ---- команда клієнта ----

class TeamUserIn(BaseModel):
    email: EmailStr
    full_name: str = ""
    role: str = Field(pattern="^(accountant|viewer|owner)$")
    password: str = Field(min_length=8, max_length=128)


@router.get("/team")
def team(user: User = Depends(current_tenant_user), db: Session = Depends(get_db)):
    users = db.scalars(select(User).where(User.tenant_id == user.tenant_id).order_by(User.id))
    return [{"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active,
             "last_login_at": u.last_login_at} for u in users]


@router.post("/team", status_code=201)
def add_team_user(body: TeamUserIn, user: User = Depends(require_roles("owner")), db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Користувач з таким email вже існує")
    u = User(tenant_id=user.tenant_id, email=email, full_name=body.full_name, role=body.role,
             password_hash=hash_password(body.password))
    db.add(u)
    audit(db, user, "team.add", "user", email)
    db.commit()
    return {"id": u.id, "email": u.email, "role": u.role}


@router.patch("/team/{user_id}")
def toggle_team_user(user_id: int, active: bool, user: User = Depends(require_roles("owner")),
                     db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u or u.tenant_id != user.tenant_id:
        raise HTTPException(404, "Користувача не знайдено")
    if u.id == user.id:
        raise HTTPException(400, "Не можна змінити власний статус")
    u.is_active = active
    audit(db, user, "team.active", "user", u.id, {"active": active})
    db.commit()
    return {"id": u.id, "is_active": u.is_active}
