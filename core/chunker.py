from __future__ import annotations
import asyncio
import time
from redis import Redis
from typing import List, Optional


class Chunker:
    """Accumulates user messages into a single *thought*.

    A thought is emitted when no new text arrives for `timeout` seconds, **and**

    Example:
        chunker = Chunker(timeout=1.5)
        async for thought in chunker.feed_stream(message_stream):
            ...  # send to worker
    """

    def __init__(self, timeout: float = 1.5, user_id: int = 0):
        self.timeout = timeout
        self._buffer: List[str] = []
        self._last_ts: float | None = None
        self.redis = Redis()

        if user_id == 0:
            raise ValueError("Default user-id specified")

        self.user_id = user_id

    def _condition_met(self) -> bool:
        if not self._buffer or self._last_ts is None:
            return False
        gap_ok = (time.time() - (self._last_ts or time.time())) >= self.timeout

        print(time.time(), self._last_ts)
        print(f"Elapsed time: {time.time() - (self._last_ts or time.time())}")

        if self.redis.exists(f"last_ai_reply:{self.user_id}"):
            last_ai_time = float(self.redis.get(f"last_ai_reply:{self.user_id}").decode())
            if self._last_ts < last_ai_time:
                return False

        return gap_ok

    def reset_elapsed(self):
        self._last_ts = None

    async def feed(self, msg: str) -> Optional[str]:
        """Feed a single incoming telegram message.
        Returns a *thought* string if completed, else None.
        """

        print(f"Received message to buffer!")
        self._buffer.append(msg)
        await asyncio.sleep(0)  # yield control
        if self._condition_met():
            print("Formed thought")
            thought = " ".join(self._buffer)
            self._buffer.clear()
            self._last_ts = time.time()
            return thought

        self._last_ts = time.time()
        return None
    