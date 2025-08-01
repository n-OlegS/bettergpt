import json
import time
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from redis import Redis


class ContextManager:
    """Rolling time‑window memory (default 6h, but min 100 msgs). 
    Stores ALL messages persistently in Redis, but only loads recent ones for context."""

    def __init__(self, user_id: int, redis_conn: Redis, max_age_hours: int = 6, min_msgs: int = 100):
        self.user_id = user_id
        self.redis_conn = redis_conn
        self.max_age_seconds = max_age_hours * 3600
        self.min_msgs = min_msgs
        self.redis_key = f"chat_history:{user_id}"

    def add(self, role: str, content: str):
        """Add a message to persistent storage. Role should be 'user' or 'assistant'."""
        message = {
            "timestamp": time.time(),
            "role": role,
            "content": content,
            "message_id": str(uuid.uuid4())
        }
        
        # Store message permanently in Redis list
        self.redis_conn.lpush(self.redis_key, json.dumps(message))

    def get_recent_messages(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get recent messages within the time window for OpenAI context."""
        now = time.time()
        cutoff_time = now - self.max_age_seconds
        
        # Get all messages from Redis (they're stored newest first)
        raw_messages = self.redis_conn.lrange(self.redis_key, 0, -1)
        messages = []
        
        for raw_msg in raw_messages:
            try:
                msg = json.loads(raw_msg.decode('utf-8'))
                # Include message if it's within time window OR we haven't hit min_msgs yet
                if msg['timestamp'] >= cutoff_time or len(messages) < self.min_msgs:
                    messages.append(msg)
                elif len(messages) >= self.min_msgs:
                    # We have enough recent messages, stop processing older ones
                    break
            except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
                continue
        
        # Reverse to get chronological order (oldest first)
        messages.reverse()
        
        # Apply limit if specified
        if limit:
            messages = messages[-limit:]
            
        return messages

    def get_context(self) -> str:
        """Get formatted context string for LLM (maintains backward compatibility)."""
        messages = self.get_recent_messages()
        return "\n".join(f"{msg['role']}: {msg['content']}" for msg in messages)

    def get_openai_messages(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        """Get messages in OpenAI chat format."""
        messages = self.get_recent_messages(limit)
        return [
            {
                "role": msg['role'],
                "content": msg['content']
            }
            for msg in messages
        ]

    def get_full_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get complete message history (for export/admin purposes)."""
        raw_messages = self.redis_conn.lrange(self.redis_key, 0, limit - 1 if limit else -1)
        messages = []
        
        for raw_msg in raw_messages:
            try:
                msg = json.loads(raw_msg.decode('utf-8'))
                messages.append(msg)
            except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
                continue
        
        # Reverse to get chronological order
        messages.reverse()
        return messages

    def clear_history(self):
        """Clear all message history for this user."""
        self.redis_conn.delete(self.redis_key)

    def get_message_count(self) -> int:
        """Get total number of stored messages."""
        return self.redis_conn.llen(self.redis_key)
