from datetime import timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from .config import get_settings
from .models import utcnow

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(user_id: int, minutes: Optional[int] = None, extra: Optional[dict] = None) -> str:
    s = get_settings()
    exp = utcnow() + timedelta(minutes=minutes or s.access_token_minutes)
    return jwt.encode({"sub": str(user_id), "exp": exp, **(extra or {})}, s.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None
