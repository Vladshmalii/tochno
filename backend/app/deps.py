import hashlib
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import ApiKey, AuditLog, User, utcnow
from .security import decode_token

_bearer = HTTPBearer(auto_error=False)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _user_from_api_key(request: Request, db: Session, key: str) -> Optional[User]:
    row = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(key), ApiKey.revoked.is_(False)))
    if row is None:
        return None
    if row.read_only and request.method not in ("GET", "HEAD", "OPTIONS"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API-ключ лише для читання")
    row.last_used_at = utcnow()
    db.commit()
    return db.get(User, row.user_id)


def current_user(
    request: Request, cred: HTTPAuthorizationCredentials = Depends(_bearer), db: Session = Depends(get_db)
) -> User:
    user: Optional[User] = None
    if cred:
        uid = decode_token(cred.credentials)
        user = db.get(User, uid) if uid else None
    elif request.headers.get("x-api-key"):
        user = _user_from_api_key(request, db, request.headers["x-api-key"])
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невірний або прострочений токен")
    return user


def current_tenant_user(user: User = Depends(current_user)) -> User:
    """Користувач клієнтського кабінету: має tenant; tenant активний і пробний період не закінчився."""
    t = user.tenant
    if t is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Цей акаунт не належить жодному клієнту")
    if t.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Обліковий запис клієнта призупинено")
    if t.trial_expired():
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "Пробний період завершено — оберіть тариф")
    return user


def platform_admin(user: User = Depends(current_user)) -> User:
    if user.role != "platform_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Лише для адміністраторів платформи")
    return user


def require_module(code: str) -> Callable:
    def dep(user: User = Depends(current_tenant_user)) -> User:
        if code not in user.tenant.enabled_modules():
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Модуль '{code}' не підключено до вашого тарифу")
        return user

    return dep


def require_roles(*roles: str) -> Callable:
    def dep(user: User = Depends(current_tenant_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостатньо прав")
        return user

    return dep


def require_module_roles(code: str, *roles: str) -> Callable:
    """Модуль підключено І роль достатня — для операцій запису."""
    def dep(user: User = Depends(require_module(code))) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостатньо прав")
        return user

    return dep


def audit(db: Session, user: User, action: str, entity: str = "", entity_id="", detail=None) -> None:
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action=action, entity=entity,
                    entity_id=str(entity_id), detail=detail))
