"""Налаштування клієнта: авто-затвердження, Telegram-бот, вхід-вебхук Telegram."""

import hmac
import secrets
from typing import Any, Dict

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core import telegram as tg
from ..db import get_db
from ..deps import audit, current_tenant_user, require_roles
from ..models import Tenant, User
from .documents import ingest

router = APIRouter(tags=["settings"])
owner_only = require_roles("owner")


def _public(t: Tenant) -> Dict[str, Any]:
    s = t.settings or {}
    tgs = s.get("telegram") or {}
    return {"auto_approve_clean": bool(s.get("auto_approve_clean")),
            "telegram": {"connected": bool(tgs.get("bot_token")), "bot_username": tgs.get("bot_username", ""),
                         "pair_code": tgs.get("pair_code", ""), "chats": len(tgs.get("chats", []))}}


@router.get("/api/settings")
def get_tenant_settings(user: User = Depends(current_tenant_user)):
    return _public(user.tenant)


class SettingsIn(BaseModel):
    auto_approve_clean: bool


@router.put("/api/settings")
def put_settings(body: SettingsIn, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    t = db.get(Tenant, user.tenant_id)
    t.settings = {**(t.settings or {}), "auto_approve_clean": body.auto_approve_clean}
    audit(db, user, "settings.update", "tenant", t.id, {"auto_approve_clean": body.auto_approve_clean})
    db.commit()
    return _public(t)


class TelegramIn(BaseModel):
    bot_token: str = Field(min_length=20, max_length=100)


@router.put("/api/settings/telegram")
def connect_telegram(body: TelegramIn, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    """Підключає бота: перевіряє токен (getMe) і реєструє вебхук на адресу API (PUBLIC_API_URL)."""
    cfg = get_settings()
    if not cfg.public_api_url:
        raise HTTPException(409, "На сервері не задано PUBLIC_API_URL — Telegram не зможе надсилати оновлення")
    t = db.get(Tenant, user.tenant_id)
    secret = secrets.token_urlsafe(24)
    try:
        me = tg.call(body.bot_token, "getMe")
        tg.call(body.bot_token, "setWebhook", url=f"{cfg.public_api_url.rstrip('/')}/api/telegram/{t.intake_token}",
                secret_token=secret, allowed_updates=["message"])
    except tg.TelegramError as e:
        raise HTTPException(400, str(e))
    t.settings = {**(t.settings or {}), "telegram": {
        "bot_token": body.bot_token, "bot_username": me.get("username", ""), "secret": secret,
        "pair_code": secrets.token_hex(3), "chats": []}}
    audit(db, user, "settings.telegram.connect", "tenant", t.id, {"bot": me.get("username")})
    db.commit()
    return _public(t)


@router.delete("/api/settings/telegram", status_code=204)
def disconnect_telegram(user: User = Depends(owner_only), db: Session = Depends(get_db)):
    t = db.get(Tenant, user.tenant_id)
    tgs = (t.settings or {}).get("telegram") or {}
    if tgs.get("bot_token"):
        try:
            tg.call(tgs["bot_token"], "deleteWebhook")
        except tg.TelegramError:
            pass  # токен міг бути відкликаний — локально все одно відключаємо
    t.settings = {k: v for k, v in (t.settings or {}).items() if k != "telegram"}
    audit(db, user, "settings.telegram.disconnect", "tenant", t.id)
    db.commit()


def _reply(token: str, chat_id: int, text: str) -> None:
    try:
        tg.call(token, "sendMessage", chat_id=chat_id, text=text)
    except tg.TelegramError:
        pass  # відповідь у чат — не критична


@router.post("/api/telegram/{token}")
async def telegram_webhook(token: str, request: Request, db: Session = Depends(get_db),
                           x_telegram_bot_api_secret_token: str = Header("")):
    t = db.scalar(select(Tenant).where(Tenant.intake_token == token))
    tgs = ((t.settings or {}).get("telegram") or {}) if t else {}
    # однакова відповідь для невідомого токена і хибного секрету — не розкриваємо існування тенанта
    if not tgs.get("bot_token") or not hmac.compare_digest(x_telegram_bot_api_secret_token, tgs.get("secret", "")):
        raise HTTPException(404, "Not found")
    msg = (await request.json()).get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    if not chat_id:
        return {"ok": True}
    bot = tgs["bot_token"]
    text = (msg.get("text") or "").strip()

    if text.startswith("/bind"):
        code = text[5:].strip()
        if code and hmac.compare_digest(code, tgs.get("pair_code", "")):
            chats = set(tgs.get("chats", [])) | {chat_id}
            t.settings = {**t.settings, "telegram": {**tgs, "chats": sorted(chats)}}
            db.commit()
            _reply(bot, chat_id, "✅ Чат підключено. Надсилайте рахунки та документи — я їх оброблю.")
        else:
            _reply(bot, chat_id, "Невірний код. Код прив'язки — у Налаштуваннях Tochno.")
        return {"ok": True}

    if chat_id not in tgs.get("chats", []):
        _reply(bot, chat_id, "Цей чат не підключено. Надішліть /bind КОД (код — у Налаштуваннях Tochno).")
        return {"ok": True}

    f = tg.extract_file(msg)
    if not f:
        _reply(bot, chat_id, "Надішліть файл (PDF, фото, Word, Excel) — я розпізнаю документ.")
        return {"ok": True}
    owner = db.scalar(select(User).where(User.tenant_id == t.id, User.role == "owner", User.is_active.is_(True))
                      .order_by(User.id))
    try:
        name, raw = tg.download(bot, f[0])
        ingest(db, owner, [(f[1] if "." in f[1] else name, "", raw)], "invoice", "Отримано через Telegram")
        _reply(bot, chat_id, "📥 Прийнято. Результат буде в розділі «Документи» на перевірці.")
    except tg.TelegramError as e:
        _reply(bot, chat_id, f"Не вдалося отримати файл: {e}")
    except HTTPException as e:  # ліміт тарифу, формат файлу тощо
        _reply(bot, chat_id, f"Не прийнято: {e.detail}")
    return {"ok": True}
