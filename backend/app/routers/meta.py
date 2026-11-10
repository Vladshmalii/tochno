from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..catalog import MODULES
from ..db import get_db
from ..deps import current_tenant_user, require_roles
from ..models import AuditLog, Document, User, utcnow
from .documents import docs_used

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/modules")
def my_modules(user: User = Depends(current_tenant_user)):
    enabled = set(user.tenant.enabled_modules())
    return [{"code": c, "name": m["name"], "description": m["description"], "ready": m["ready"],
             "enabled": c in enabled} for c, m in MODULES.items()]


@router.get("/usage")
def usage(user: User = Depends(current_tenant_user), db: Session = Depends(get_db)):
    t = user.tenant
    return {"plan": t.plan.name, "docs_used": docs_used(db, t.id), "docs_limit": t.doc_limit(),
            "modules": t.enabled_modules()}


@router.get("/audit")
def my_audit(limit: int = 100, user: User = Depends(require_roles("owner")), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).where(AuditLog.tenant_id == user.tenant_id)
                      .order_by(AuditLog.id.desc()).limit(min(limit, 500)))
    return [{"id": r.id, "action": r.action, "entity": r.entity, "entity_id": r.entity_id,
             "user_id": r.user_id, "created_at": r.created_at, "detail": r.detail} for r in rows]


@router.get("/dashboard")
def dashboard(user: User = Depends(current_tenant_user), db: Session = Depends(get_db)):
    """Що потребує уваги + навантаження за 14 днів — по всіх підключених модулях документів."""
    mods = [m for m in user.tenant.enabled_modules() if m in ("docs_extract", "identity", "reports")]
    base = [Document.tenant_id == user.tenant_id, Document.module.in_(mods)]
    review = db.scalars(select(Document).where(*base, Document.status == "review").order_by(Document.id)).all()
    attention = sorted(review, key=lambda d: -sum(1 for f in (d.flags or []) if f["severity"] == "error"))[:8]
    failed = db.scalar(select(func.count(Document.id)).where(*base, Document.status == "failed")) or 0
    since = utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=13)
    per_day = {}
    for (created,) in db.execute(select(Document.created_at).where(*base, Document.created_at >= since)):
        per_day[created.date().isoformat()] = per_day.get(created.date().isoformat(), 0) + 1
    series = [{"date": (since + timedelta(days=i)).date().isoformat(),
               "count": per_day.get((since + timedelta(days=i)).date().isoformat(), 0)} for i in range(14)]
    return {"review_total": len(review), "failed_total": failed, "series": series,
            "attention": [{"id": d.id, "module": d.module, "filename": d.filename, "name": d.supplier_name,
                           "errors": sum(1 for f in (d.flags or []) if f["severity"] == "error"),
                           "flags": len(d.flags or [])} for d in attention]}
