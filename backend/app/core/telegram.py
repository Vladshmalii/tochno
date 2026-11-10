"""Мінімальний клієнт Telegram Bot API: прийом документів/фото від бухгалтерів і відповіді в чат."""

from typing import Any, Dict, Optional, Tuple

import httpx

API = "https://api.telegram.org"
MAX_BYTES = 20 * 1024 * 1024  # ліміт getFile у Bot API


class TelegramError(Exception):
    pass


def call(token: str, method: str, **params: Any) -> Dict[str, Any]:
    try:
        r = httpx.post(f"{API}/bot{token}/{method}", json=params, timeout=15)
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise TelegramError(f"Telegram недоступний: {e}") from e
    if not data.get("ok"):
        raise TelegramError(data.get("description", "Помилка Telegram"))
    return data["result"]


def download(token: str, file_id: str) -> Tuple[str, bytes]:
    info = call(token, "getFile", file_id=file_id)
    if info.get("file_size", 0) > MAX_BYTES:
        raise TelegramError("Файл завеликий (макс. 20 МБ)")
    try:
        r = httpx.get(f"{API}/file/bot{token}/{info['file_path']}", timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise TelegramError(f"Не вдалося завантажити файл: {e}") from e
    return info["file_path"].rsplit("/", 1)[-1], r.content


def extract_file(message: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """(file_id, ім'я файлу) для документа або найбільшого фото; None — якщо у повідомленні немає файлу."""
    if message.get("document"):
        d = message["document"]
        return d["file_id"], d.get("file_name") or "document.pdf"
    if message.get("photo"):
        return message["photo"][-1]["file_id"], "photo.jpg"
    return None
