"""Інтеграції клієнта: API-ключі, вебхуки, intake-ендпоінт (для пошти/Zapier/Make/Bitrix24-роботів)."""

import secrets
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.webhooks import EVENTS, validate_webhook_url
from ..db import get_db
from ..deps import audit, current_tenant_user, hash_api_key, require_roles
from ..models import ApiKey, Tenant, User, Webhook
from .documents import ingest

router = APIRouter(tags=["integrations"])
owner_only = require_roles("owner")


@router.get("/api/integrations")
def overview(user: User = Depends(owner_only), db: Session = Depends(get_db)):
    keys = db.scalars(select(ApiKey).where(ApiKey.tenant_id == user.tenant_id, ApiKey.revoked.is_(False))
                      .order_by(ApiKey.id))
    hooks = db.scalars(select(Webhook).where(Webhook.tenant_id == user.tenant_id).order_by(Webhook.id))
    return {
        "intake_token": user.tenant.intake_token,
        "api_keys": [{"id": k.id, "name": k.name, "prefix": k.prefix, "read_only": k.read_only,
                      "last_used_at": k.last_used_at, "created_at": k.created_at} for k in keys],
        "webhooks": [{"id": h.id, "url": h.url, "events": h.events, "active": h.active,
                      "last_status": h.last_status} for h in hooks],
        "events": list(EVENTS),
    }


@router.post("/api/integrations/intake/rotate")
def rotate_intake(user: User = Depends(owner_only), db: Session = Depends(get_db)):
    t = db.get(Tenant, user.tenant_id)
    t.intake_token = secrets.token_urlsafe(24)
    audit(db, user, "integration.intake.rotate", "tenant", t.id)
    db.commit()
    return {"intake_token": t.intake_token}


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    read_only: bool = False


@router.post("/api/integrations/api-keys", status_code=201)
def create_key(body: KeyIn, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    prefix = secrets.token_hex(4)
    key = f"dm_{prefix}_{secrets.token_urlsafe(30)}"
    db.add(ApiKey(tenant_id=user.tenant_id, user_id=user.id, name=body.name, prefix=f"dm_{prefix}",
                  key_hash=hash_api_key(key), read_only=body.read_only))
    audit(db, user, "integration.apikey.create", "api_key", body.name)
    db.commit()
    return {"key": key, "note": "Збережіть ключ зараз — повторно він не показується"}


@router.delete("/api/integrations/api-keys/{kid}", status_code=204)
def revoke_key(kid: int, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    k = db.get(ApiKey, kid)
    if not k or k.tenant_id != user.tenant_id:
        raise HTTPException(404, "Ключ не знайдено")
    k.revoked = True
    audit(db, user, "integration.apikey.revoke", "api_key", kid)
    db.commit()


class HookIn(BaseModel):
    url: str = Field(max_length=500)
    events: List[str] = Field(default_factory=lambda: list(EVENTS))


@router.post("/api/integrations/webhooks", status_code=201)
def create_hook(body: HookIn, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    unknown = set(body.events) - set(EVENTS)
    if unknown:
        raise HTTPException(400, f"Невідомі події: {', '.join(sorted(unknown))}")
    try:
        validate_webhook_url(body.url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    h = Webhook(tenant_id=user.tenant_id, url=body.url, events=body.events, secret=secrets.token_hex(24))
    db.add(h)
    audit(db, user, "integration.webhook.create", "webhook", body.url)
    db.commit()
    return {"id": h.id, "secret": h.secret, "note": "Підписуйте перевірку заголовка X-Tochno-Signature цим секретом"}


@router.patch("/api/integrations/webhooks/{hid}")
def toggle_hook(hid: int, active: bool, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    h = db.get(Webhook, hid)
    if not h or h.tenant_id != user.tenant_id:
        raise HTTPException(404, "Вебхук не знайдено")
    h.active = active
    db.commit()
    return {"id": h.id, "active": h.active}


@router.delete("/api/integrations/webhooks/{hid}", status_code=204)
def delete_hook(hid: int, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    h = db.get(Webhook, hid)
    if not h or h.tenant_id != user.tenant_id:
        raise HTTPException(404, "Вебхук не знайдено")
    db.delete(h)
    db.commit()


@router.post("/api/intake/{token}", status_code=201)
async def intake(token: str, files: List[UploadFile] = File(...), doc_type: str = Query("invoice"),
                 db: Session = Depends(get_db)):
    """Прийом документів без логіну (токен — секрет тенанта): пошта→вебхук, Zapier, Make, Bitrix24-робот."""
    t = db.scalar(select(Tenant).where(Tenant.intake_token == token))
    if t is None or t.status != "active" or t.trial_expired():
        raise HTTPException(404, "Невідомий токен")
    owner: Optional[User] = db.scalar(select(User).where(User.tenant_id == t.id, User.role == "owner",
                                                          User.is_active.is_(True)).order_by(User.id))
    if owner is None:
        raise HTTPException(409, "У клієнта немає активного власника")
    items = [(f.filename or "file", f.content_type or "", await f.read()) for f in files]
    docs = ingest(db, owner, items, doc_type, description="Отримано через intake")
    return {"created": [d.id for d in docs]}
