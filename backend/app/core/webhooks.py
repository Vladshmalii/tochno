"""Вихідні вебхуки: підписаний HMAC payload, доставка через чергу з повторами, захист від SSRF."""

import hashlib
import hmac
import ipaddress
import json
import socket
from typing import Any, Dict
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..models import Webhook, utcnow
from .jobs import enqueue, handler

EVENTS = ("document.processed", "document.approved", "document.failed")


def validate_webhook_url(url: str) -> None:
    """Кидає ValueError для небезпечних URL (не http(s), приватні/loopback/link-local адреси)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("URL має починатися з http:// або https://")
    if get_settings().allow_private_webhooks:
        return
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror as e:
        raise ValueError("Не вдалося визначити адресу хоста") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("Адреси внутрішньої мережі заборонені")


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def emit(db: Session, tenant_id: int, event: str, data: Dict[str, Any]) -> None:
    """Ставить доставку в чергу для всіх активних підписок тенанта (у поточній транзакції)."""
    hooks = db.scalars(select(Webhook).where(Webhook.tenant_id == tenant_id, Webhook.active.is_(True)))
    for h in hooks:
        if event in (h.events or []):
            enqueue(db, "webhook", {"webhook_id": h.id, "event": event, "data": data}, max_attempts=5)


@handler("webhook")
def deliver(payload: Dict[str, Any]) -> None:
    with SessionLocal() as db:
        h = db.get(Webhook, payload["webhook_id"])
        if h is None or not h.active:
            return
        body = json.dumps({"event": payload["event"], "data": payload["data"],
                           "sent_at": utcnow().isoformat() + "Z"}, ensure_ascii=False).encode()
        try:
            validate_webhook_url(h.url)  # перевіряємо й на момент доставки (захист від DNS-rebinding)
            r = httpx.post(h.url, content=body, timeout=10, follow_redirects=False, headers={
                "Content-Type": "application/json", "X-Tochno-Event": payload["event"],
                "X-Tochno-Signature": "sha256=" + sign(h.secret, body)})
            h.last_status = f"{r.status_code}"
            db.commit()
            if r.status_code >= 400:
                raise RuntimeError(f"Webhook відповів {r.status_code}")
        except (httpx.HTTPError, ValueError) as e:
            h.last_status = f"error: {e}"[:100]
            db.commit()
            raise
