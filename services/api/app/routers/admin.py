"""API админки платформи: клієнти, тарифи, модулі, використання. Лише platform_admin."""

import csv
import io
import secrets
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..catalog import MODULES
from ..config import get_settings
from ..db import get_db
from ..deps import platform_admin
from ..models import AuditLog, Document, Job, Plan, Tenant, UsageEvent, User, utcnow
from ..config import get_settings as _cfg
from ..security import create_token, hash_password
from .documents import month_start

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _tenant_row(db: Session, t: Tenant) -> dict:
    ms = month_start()
    used = db.scalar(select(func.count(Document.id)).where(Document.tenant_id == t.id, Document.created_at >= ms)) or 0
    users = db.scalar(select(func.count(User.id)).where(User.tenant_id == t.id)) or 0
    tok = db.execute(select(func.coalesce(func.sum(UsageEvent.tokens_in), 0),
                            func.coalesce(func.sum(UsageEvent.tokens_out), 0))
                     .where(UsageEvent.tenant_id == t.id, UsageEvent.created_at >= ms)).one()
    last = db.scalar(select(func.max(Document.created_at)).where(Document.tenant_id == t.id))
    return {"id": t.id, "name": t.name, "slug": t.slug, "status": t.status, "plan": t.plan.code,
            "plan_name": t.plan.name, "modules": t.enabled_modules(), "modules_override": t.modules_override,
            "doc_limit": t.doc_limit(), "doc_limit_override": t.doc_limit_override, "docs_used": used,
            "users": users, "tokens_in": tok[0], "tokens_out": tok[1], "contact_email": t.contact_email,
            "notes": t.notes, "created_at": t.created_at, "last_activity": last, "trial_ends_at": t.trial_ends_at}


@router.get("/overview")
def overview(_: User = Depends(platform_admin), db: Session = Depends(get_db)):
    ms = month_start()
    tenants = list(db.scalars(select(Tenant)))
    mrr = sum(t.plan.price_month for t in tenants if t.status == "active")
    docs_month = db.scalar(select(func.count(Document.id)).where(Document.created_at >= ms)) or 0
    failed = db.scalar(select(func.count(Document.id)).where(Document.created_at >= ms, Document.status == "failed")) or 0
    tokens = db.execute(select(func.coalesce(func.sum(UsageEvent.tokens_in), 0),
                               func.coalesce(func.sum(UsageEvent.tokens_out), 0))
                        .where(UsageEvent.created_at >= ms)).one()
    by_plan = dict(db.execute(select(Plan.code, func.count(Tenant.id)).join(Tenant, Tenant.plan_id == Plan.id)
                              .group_by(Plan.code)).all())
    return {"tenants": len(tenants), "active": sum(1 for t in tenants if t.status == "active"),
            "suspended": sum(1 for t in tenants if t.status != "active"), "mrr": mrr, "docs_month": docs_month,
            "failed_month": failed, "tokens_in": tokens[0], "tokens_out": tokens[1], "by_plan": by_plan}


@router.get("/tenants")
def list_tenants(q: Optional[str] = None, _: User = Depends(platform_admin), db: Session = Depends(get_db)):
    stmt = select(Tenant).order_by(Tenant.id.desc())
    if q:
        stmt = stmt.where(Tenant.name.ilike(f"%{q}%") | Tenant.contact_email.ilike(f"%{q}%"))
    return [_tenant_row(db, t) for t in db.scalars(stmt)]


class TenantCreate(BaseModel):
    name: str = Field(min_length=2)
    plan: str = "trial"
    owner_email: EmailStr
    owner_name: str = ""
    owner_password: str = Field(min_length=8)


@router.post("/tenants", status_code=201)
def create_tenant(body: TenantCreate, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    plan = db.scalar(select(Plan).where(Plan.code == body.plan))
    if not plan:
        raise HTTPException(400, "Невідомий тариф")
    email = body.owner_email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Користувач з таким email вже існує")
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-") or "client"
    if db.scalar(select(Tenant).where(Tenant.slug == slug)):
        slug += f"-{db.scalar(select(func.count(Tenant.id))) + 1}"
    t = Tenant(name=body.name, slug=slug, plan_id=plan.id, contact_email=email, intake_token=secrets.token_urlsafe(24),
               trial_ends_at=utcnow() + timedelta(days=get_settings().trial_days) if plan.code == "trial" else None)
    db.add(t)
    db.flush()
    db.add(User(tenant_id=t.id, email=email, full_name=body.owner_name, role="owner",
                password_hash=hash_password(body.owner_password)))
    db.add(AuditLog(user_id=admin.id, tenant_id=t.id, action="admin.tenant.create", entity="tenant", entity_id=str(t.id)))
    db.commit()
    return _tenant_row(db, t)


class TenantPatch(BaseModel):
    name: Optional[str] = None
    plan: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|suspended)$")
    modules_override: Optional[List[str]] = None
    clear_modules_override: bool = False
    doc_limit_override: Optional[int] = Field(None, ge=0)
    clear_doc_limit_override: bool = False
    notes: Optional[str] = None
    extend_trial_days: Optional[int] = Field(None, ge=1, le=365)


@router.patch("/tenants/{tid}")
def patch_tenant(tid: int, body: TenantPatch, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    t = db.get(Tenant, tid)
    if not t:
        raise HTTPException(404, "Клієнта не знайдено")
    changes = body.model_dump(exclude_unset=True)
    if body.plan is not None:
        plan = db.scalar(select(Plan).where(Plan.code == body.plan))
        if not plan:
            raise HTTPException(400, "Невідомий тариф")
        t.plan_id = plan.id
        t.plan = plan
    if body.modules_override is not None:
        unknown = set(body.modules_override) - set(MODULES)
        if unknown:
            raise HTTPException(400, f"Невідомі модулі: {', '.join(sorted(unknown))}")
        t.modules_override = body.modules_override
    if body.clear_modules_override:
        t.modules_override = None
    if body.doc_limit_override is not None:
        t.doc_limit_override = body.doc_limit_override
    if body.clear_doc_limit_override:
        t.doc_limit_override = None
    if body.extend_trial_days:
        base = max(t.trial_ends_at or utcnow(), utcnow())
        t.trial_ends_at = base + timedelta(days=body.extend_trial_days)
    for f in ("name", "status", "notes"):
        if getattr(body, f) is not None:
            setattr(t, f, getattr(body, f))
    db.add(AuditLog(user_id=admin.id, tenant_id=t.id, action="admin.tenant.update", entity="tenant",
                    entity_id=str(t.id), detail=changes))
    db.commit()
    return _tenant_row(db, t)


@router.get("/tenants/{tid}/users")
def tenant_users(tid: int, _: User = Depends(platform_admin), db: Session = Depends(get_db)):
    return [{"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active,
             "last_login_at": u.last_login_at} for u in db.scalars(select(User).where(User.tenant_id == tid))]


@router.get("/plans")
def plans(_: User = Depends(platform_admin), db: Session = Depends(get_db)):
    return [{"id": p.id, "code": p.code, "name": p.name, "price_month": p.price_month,
             "doc_limit_month": p.doc_limit_month, "modules": p.modules} for p in db.scalars(select(Plan))]


class PlanPatch(BaseModel):
    name: Optional[str] = None
    price_month: Optional[float] = Field(None, ge=0)
    doc_limit_month: Optional[int] = Field(None, ge=0)
    modules: Optional[List[str]] = None


@router.patch("/plans/{pid}")
def patch_plan(pid: int, body: PlanPatch, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    p = db.get(Plan, pid)
    if not p:
        raise HTTPException(404, "Тариф не знайдено")
    if body.modules is not None:
        unknown = set(body.modules) - set(MODULES)
        if unknown:
            raise HTTPException(400, f"Невідомі модулі: {', '.join(sorted(unknown))}")
        p.modules = body.modules
    for f in ("name", "price_month", "doc_limit_month"):
        if getattr(body, f) is not None:
            setattr(p, f, getattr(body, f))
    db.add(AuditLog(user_id=admin.id, action="admin.plan.update", entity="plan", entity_id=str(p.id),
                    detail=body.model_dump(exclude_unset=True)))
    db.commit()
    return {"id": p.id, "code": p.code, "name": p.name, "price_month": p.price_month,
            "doc_limit_month": p.doc_limit_month, "modules": p.modules}


@router.get("/modules")
def modules(_: User = Depends(platform_admin)):
    return [{"code": c, **m} for c, m in MODULES.items()]


@router.get("/audit")
def audit_log(limit: int = 100, tenant_id: Optional[int] = None, _: User = Depends(platform_admin),
              db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))
    if tenant_id:
        stmt = stmt.where(AuditLog.tenant_id == tenant_id)
    return [{"id": r.id, "tenant_id": r.tenant_id, "user_id": r.user_id, "action": r.action, "entity": r.entity,
             "entity_id": r.entity_id, "detail": r.detail, "created_at": r.created_at} for r in db.scalars(stmt)]


class ResetIn(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/users/{uid}/reset-password", status_code=204)
def reset_password(uid: int, body: ResetIn, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Користувача не знайдено")
    u.password_hash = hash_password(body.new_password)
    db.add(AuditLog(user_id=admin.id, tenant_id=u.tenant_id, action="admin.user.reset_password", entity="user",
                    entity_id=str(u.id)))
    db.commit()


@router.patch("/users/{uid}")
def set_user_active(uid: int, active: bool, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or u.id == admin.id:
        raise HTTPException(404, "Користувача не знайдено")
    u.is_active = active
    db.add(AuditLog(user_id=admin.id, tenant_id=u.tenant_id, action="admin.user.active", entity="user",
                    entity_id=str(u.id), detail={"active": active}))
    db.commit()
    return {"id": u.id, "is_active": u.is_active}


@router.get("/usage.csv")
def usage_csv(_: User = Depends(platform_admin), db: Session = Depends(get_db)):
    """Місячний звіт для виставлення рахунків: тариф, документи, токени по кожному клієнту."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["id", "клієнт", "тариф", "ціна/міс", "статус", "документів", "токени_in", "токени_out"])
    for t in db.scalars(select(Tenant).order_by(Tenant.id)):
        r = _tenant_row(db, t)
        w.writerow([t.id, t.name, t.plan.code, t.plan.price_month, t.status, r["docs_used"], r["tokens_in"], r["tokens_out"]])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="usage.csv"'})


@router.get("/health")
def platform_health(_: User = Depends(platform_admin), db: Session = Depends(get_db)):
    """Стан черги задач — перший погляд, чи не зависла обробка."""
    jobs = dict(db.execute(select(Job.status, func.count(Job.id)).group_by(Job.status)).all())
    oldest = db.scalar(select(func.min(Job.created_at)).where(Job.status == "queued"))
    return {"jobs": jobs, "oldest_queued": oldest}


@router.post("/tenants/{tid}/impersonate")
def impersonate(tid: int, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    """Короткоживучий токен власника клієнта — для підтримки. Кожен виклик фіксується в журналі."""
    owner = db.scalar(select(User).where(User.tenant_id == tid, User.role == "owner", User.is_active.is_(True))
                      .order_by(User.id))
    if owner is None:
        raise HTTPException(404, "У клієнта немає активного власника")
    db.add(AuditLog(user_id=admin.id, tenant_id=tid, action="admin.impersonate", entity="user",
                    entity_id=str(owner.id)))
    db.commit()
    return {"access_token": create_token(owner.id, minutes=_cfg().impersonation_minutes, extra={"imp": admin.id}),
            "expires_minutes": _cfg().impersonation_minutes}
