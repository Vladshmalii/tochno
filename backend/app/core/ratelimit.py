"""Проста in-memory захист від перебору паролів (на один процес; для кількох інстансів — Redis)."""

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict

WINDOW_SECONDS = 15 * 60


class FailureLimiter:
    def __init__(self) -> None:
        self._fails: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> Deque[float]:
        q = self._fails[key]
        while q and now - q[0] > WINDOW_SECONDS:
            q.popleft()
        return q

    def blocked(self, key: str, limit: int) -> bool:
        with self._lock:
            return len(self._prune(key, time.monotonic())) >= limit

    def fail(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


login_limiter = FailureLimiter()
