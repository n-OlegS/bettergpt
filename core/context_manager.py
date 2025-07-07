from collections import deque
from datetime import datetime, timedelta


class ContextManager:
    """Rolling time‑window memory (default 6h, but min 100 msgs)."""

    def __init__(self, max_age_hours: int = 6, min_msgs: int = 100):
        self.max_delta = timedelta(hours=max_age_hours)
        self.min_msgs = min_msgs
        self.store: deque[tuple[datetime, str]] = deque()

    def add(self, msg: str):
        now = datetime.utcnow()
        self.store.append((now, msg))
        self._trim(now)

    def _trim(self, now: datetime):
        while len(self.store) > self.min_msgs and (now - self.store[0][0] > self.max_delta):
            self.store.popleft()

    def get_context(self) -> str:
        return "\n".join(m for _, m in self.store)
