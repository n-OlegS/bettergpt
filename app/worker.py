# app/worker.py
import time

import requests
import asyncio
import dotenv
import json
import httpx

from redis import Redis
from rq import SimpleWorker

from urllib.parse import quote

from services.llm_gateway import LLMGateway
from core.context_manager import ContextManager
from core.send_queue import SendQueue
from app.telegram_bot import send_part, reset_elapsed   # re-use the bot’s sender

redis_conn = Redis()                      # host/port/db kwargs as needed

llm = LLMGateway(api_url="https://api.openai.com/v1/chat/completions",
                 api_key=dotenv.get_key("../.env", "OPENAI_API_KEY"),
                 model=dotenv.get_key("../.env", "LLM_MODEL") or "gpt-3.5-turbo")

# Global context managers per user (will be created per request)
user_contexts = {}


def strip_trailing_period(text: str) -> str:
    """Strip period only if it's the last character in the text"""
    return text[:-1] if text.endswith('.') else text


def process_thought(user_id: int, thought: str):
    print(f"🚀 WORKER: Starting process_thought for user {user_id}")
    print(f"🚀 WORKER: Thought content: '{thought}'")
    
    # Check if cancel signal exists before clearing
    cancel_key = f"cancel_reply:{user_id}"
    signal_exists_before = redis_conn.exists(cancel_key)
    print(f"🔍 WORKER: Cancel signal exists BEFORE clear: {signal_exists_before}")
    
    # Clear any existing cancel signal - we're starting a new response
    deleted_count = redis_conn.delete(cancel_key)
    print(f"🧹 WORKER: Deleted cancel signal, count: {deleted_count}")
    
    # Set response started timestamp so bot knows we're streaming
    response_started_key = f"response_started:{user_id}"
    redis_conn.set(response_started_key, time.time(), ex=120)  # expires in 2 minutes
    print(f"🚀 WORKER: Set response_started timestamp")
    
    # Verify signal is actually cleared
    signal_exists_after = redis_conn.exists(cancel_key)
    print(f"✅ WORKER: Cancel signal exists AFTER clear: {signal_exists_after}")
    
    # Get or create context manager for this user
    if user_id not in user_contexts:
        print(f"📝 WORKER: Creating new context manager for user {user_id}")
        user_contexts[user_id] = ContextManager(user_id, redis_conn)
    else:
        print(f"📝 WORKER: Using existing context manager for user {user_id}")
    ctx = user_contexts[user_id]
    
    # Add user message to persistent storage
    print(f"💾 WORKER: Adding user message to context: '{thought}'")
    ctx.add("user", thought)
    
    # Get OpenAI-formatted messages for better context handling
    messages = ctx.get_openai_messages()
    print(f"📚 WORKER: Retrieved {len(messages)} context messages")
    print(f"📚 WORKER: Last 3 messages: {messages[-3:] if len(messages) >= 3 else messages}")
    
    # Convert to old format for current LLM gateway compatibility
    prompt = "\n".join(f"{msg['role']}: {msg['content']}" for msg in messages)
    print(f"🎯 WORKER: Generated prompt length: {len(prompt)} chars")
    
    # Run LLM request with proper event loop handling
    llm_start_time = time.time()
    print(f"🤖 WORKER: Calling LLM API...")
    try:
        reply_text = asyncio.run(llm.chat(prompt))
        llm_processing_time = time.time() - llm_start_time
        print(f"✅ WORKER: LLM API call successful in {llm_processing_time:.2f}s")
    except RuntimeError as e:
        if "Event loop is closed" in str(e):
            print(f"⚠️ WORKER: Event loop closed, recreating client...")
            # Recreate the LLM client and try again
            llm._client = httpx.AsyncClient(
                timeout=30.0,
                trust_env=False,
                http2=False,
                headers={"Accept-Encoding": "identity"}
            )
            reply_text = asyncio.run(llm.chat(prompt))
            llm_processing_time = time.time() - llm_start_time
            print(f"✅ WORKER: LLM API call successful after retry in {llm_processing_time:.2f}s")
        else:
            print(f"❌ WORKER: LLM API error: {e}")
            raise
    
    print(f"📝 WORKER: LLM Reply length: {len(reply_text)} chars")
    print(f"📝 WORKER: LLM Reply preview: '{reply_text[:200]}...'")

    parts = [strip_trailing_period(p.strip()[p.find(":") + 1:].strip()) for p in reply_text.split("\n") if p.strip()]
    print(f"📦 WORKER: Split into {len(parts)} parts")
    print(f"📦 WORKER: Parts: {parts}")
    
    # Track which parts were actually sent
    sent_parts = []
    def track_sender(txt):
        # Final cancellation check right before sending to Telegram
        cancel_key = f"cancel_reply:{user_id}"
        if redis_conn.exists(cancel_key):
            print(f"❌ WORKER: Final cancellation check - NOT sending part: '{txt}'")
            return asyncio.ensure_future(asyncio.sleep(0))  # Return completed future
        
        print(f"📤 WORKER: SENDING part: '{txt}'")
        sent_parts.append(txt)
        return asyncio.ensure_future(send_part(user_id, txt))
    
    print(f"🚀 WORKER: Creating SendQueue for user {user_id}")
    sendq = SendQueue(track_sender, user_id=user_id, llm_processing_time=llm_processing_time)
    
    print(f"💨 WORKER: Starting sendq.flush() with {len(parts)} parts (LLM took {llm_processing_time:.2f}s)")
    asyncio.run(sendq.flush(parts))
    print(f"✅ WORKER: sendq.flush() completed")
    
    print(f"📊 WORKER: Actually sent {len(sent_parts)} out of {len(parts)} parts")
    print(f"📊 WORKER: Sent parts: {sent_parts}")
    
    redis_conn.set(f"last_ai_reply:{user_id}", time.time())
    print(f"⏰ WORKER: Set last_ai_reply timestamp")
    
    # Store ONLY the parts that were actually sent
    print(f"💾 WORKER: Storing {len(sent_parts)} sent parts to context")
    for i, p in enumerate(sent_parts):
        print(f"💾 WORKER: Storing part {i+1}: '{p}'")
        ctx.add("assistant", p)
    
    # Clear response started timestamp - we're done
    response_started_key = f"response_started:{user_id}"
    redis_conn.delete(response_started_key)
    print(f"🏁 WORKER: Cleared response_started timestamp")
    
    print(f"🎉 WORKER: process_thought completed for user {user_id}")


if __name__ == "__main__":
    worker = SimpleWorker(queues=["default"], connection=redis_conn)
    worker.work()
