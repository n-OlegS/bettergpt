import random
import math
import asyncio
from typing import Iterable, Callable, Optional
from redis import Redis


class SendQueue:
    """Streams multi‑part replies with human‑typing delays.

    Args:
        sender: an async callable `(text:str) -> None` that actually sends a message.
        cps: average characters per second.
        jitter: multiplicative ± randomness.
    """

    def __init__(self, sender: Callable[[str], asyncio.Future], cps: float = 8.5, jitter: float = 0.6, user_id: Optional[int] = None, llm_processing_time: float = 0.0):
        self.sender = sender
        self.cps = cps
        self.jitter = jitter
        self.user_id = user_id
        self.llm_processing_time = llm_processing_time
        self._cancel = asyncio.Event()
        self._redis = Redis() if user_id else None

    def cancel(self):
        self._cancel.set()

    async def flush(self, parts: Iterable[str]):
        print(f"🔄 SENDQUEUE: Starting flush for user {self.user_id} with {len(list(parts))} parts")
        parts = list(parts)  # Convert back to list since we consumed it
        
        for i, part in enumerate(parts):
            print(f"🔍 SENDQUEUE: Processing part {i+1}/{len(parts)}: '{part}'")
            
            # Check for Redis cancellation signal before each part
            if self._redis and self.user_id:
                cancel_key = f"cancel_reply:{self.user_id}"
                signal_exists = self._redis.exists(cancel_key)
                print(f"🔍 SENDQUEUE: Checking cancel signal '{cancel_key}': {signal_exists}")
                
                if signal_exists:
                    print(f"❌ SENDQUEUE: CANCELLATION DETECTED! Stopping at part {i+1}")
                    # Clear the signal and cancel
                    self._redis.delete(cancel_key)
                    print(f"🧹 SENDQUEUE: Cleared cancel signal")
                    return
            
            base_delay = len(part) / (self.cps * random.uniform(1 - self.jitter, 1 + self.jitter))
            
            # For the first part, subtract LLM processing time
            if i == 0 and self.llm_processing_time > 0:
                delay = max(0, base_delay - self.llm_processing_time)
                print(f"⏰ SENDQUEUE: First part - base delay {base_delay:.2f}s minus LLM time {self.llm_processing_time:.2f}s = {delay:.2f}s")
            else:
                delay = base_delay
                print(f"⏰ SENDQUEUE: Waiting {delay:.2f}s before sending part {i+1}")
            
            try:
                await asyncio.wait_for(self._cancel.wait(), timeout=delay)
                print(f"❌ SENDQUEUE: Local cancel event triggered at part {i+1}")
                return
            except asyncio.TimeoutError:
                print(f"✅ SENDQUEUE: Timeout completed, sending part {i+1}")
                pass
            
            print(f"📤 SENDQUEUE: About to call sender for part {i+1}")
            
            # Check for cancellation one more time right before sending
            if self._redis and self.user_id:
                cancel_key = f"cancel_reply:{self.user_id}"
                if self._redis.exists(cancel_key):
                    print(f"❌ SENDQUEUE: Last-second cancellation detected before sending part {i+1}")
                    self._redis.delete(cancel_key)
                    return
            
            await self.sender(part)
            print(f"✅ SENDQUEUE: Successfully sent part {i+1}")
            
        print(f"🎉 SENDQUEUE: All parts sent successfully")
        self._cancel.clear()
