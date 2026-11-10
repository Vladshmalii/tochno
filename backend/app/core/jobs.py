"""Черга фонових задач на БД + воркер-потік.

Задачі переживають рестарт процесу (running → queued при старті), повторюються з
експоненційною затримкою. Кілька воркерів безпечні: на Postgres задача бере
SELECT ... FOR UPDATE SKIP LOCKED."""

import logging
import threading
from datetime import timedelta
from typing import Any, Callable, Dict, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..models import Job, utcnow

logger = logging.getLogger(__name__)

Handler = Callable[[Dict[str, Any]], None]
_HANDLERS: Dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        return fn

    return deco


def enqueue(db: Session, kind: str, payload: Dict[str, Any], delay_seconds: float = 0, max_attempts: int = 3) -> Job:
    """Додає задачу в поточну транзакцію — комітить викликач (атомарно з бізнес-даними)."""
    job = Job(kind=kind, payload=payload, max_attempts=max_attempts,
              run_after=utcnow() + timedelta(seconds=delay_seconds))
    db.add(job)
    return job


def _claim(db: Session) -> Optional[Job]:
    job = db.scalar(
        select(Job).where(Job.status == "queued", Job.run_after <= utcnow())
        .order_by(Job.id).limit(1).with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status, job.attempts = "running", job.attempts + 1
    db.commit()
    return job


def run_one(session_factory=SessionLocal) -> bool:
    """Виконує одну задачу. True — якщо щось було виконано (для тестів і циклу воркера)."""
    with session_factory() as db:
        job = _claim(db)
        if job is None:
            return False
        fn = _HANDLERS.get(job.kind)
        try:
            if fn is None:
                raise RuntimeError(f"Немає обробника для задачі '{job.kind}'")
            fn(job.payload)
            job.status, job.finished_at, job.error = "done", utcnow(), ""
        except Exception as e:  # noqa: BLE001 — будь-яка помилка обробника має піти в retry
            logger.exception("Job %s (%s) failed", job.id, job.kind)
            job.error = str(e)[:1000]
            if job.attempts >= job.max_attempts:
                job.status, job.finished_at = "failed", utcnow()
            else:
                job.status = "queued"
                job.run_after = utcnow() + timedelta(seconds=15 * 2 ** (job.attempts - 1))
        db.commit()
        return True


class Worker(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="tochno-worker")
        self._stop_event = threading.Event()

    def run(self) -> None:
        poll = get_settings().worker_poll_seconds
        while not self._stop_event.is_set():
            try:
                busy = run_one()
            except Exception:  # noqa: BLE001
                logger.exception("Worker loop error")
                busy = False
            if not busy:
                self._stop_event.wait(poll)

    def stop(self) -> None:
        self._stop_event.set()


def recover_stuck_jobs() -> None:
    """Після рестарту: задачі, що були 'running', повертаємо в чергу."""
    with SessionLocal() as db:
        db.execute(update(Job).where(Job.status == "running").values(status="queued"))
        db.commit()
