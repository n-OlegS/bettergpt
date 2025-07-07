import random
import math
import asyncio
from typing import Iterable, Callable


class SendQueue:
    """Streams multi‑part replies with human‑typing delays.

    Args:
        sender: an async callable `(text:str) -> None` that actually sends a message.
        cps: average characters per second.
        jitter: multiplicative ± randomness.
    """

    def __init__(self, sender: Callable[[str], asyncio.Future], cps: float = 8.5, jitter: float = 0.6):
        self.sender = sender
        self.cps = cps
        self.jitter = jitter
        self._cancel = asyncio.Event()

    def cancel(self):
        self._cancel.set()

    async def flush(self, parts: Iterable[str]):
        for part in parts:
            delay = len(part) / (self.cps * random.uniform(1 - self.jitter, 1 + self.jitter))
            try:
                await asyncio.wait_for(self._cancel.wait(), timeout=delay)
                # cancelled
                return
            except asyncio.TimeoutError:
                pass
            await self.sender(part)
            
        self._cancel.clear()
