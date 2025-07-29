# app/worker.py
import time

import requests
import asyncio
import dotenv
import json

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
ctx = ContextManager()


def process_thought(user_id: int, thought: str):
    print("Processing thought")
    ctx.add(f"user: {thought}")
    prompt = ctx.get_context()
    print(f"Context: {prompt}")
    reply_text = asyncio.run(llm.chat(prompt))
    print(f"Reply: {reply_text}")

    parts = [p.strip()[p.find(":") + 1:] for p in reply_text.split("\n") if p.strip()]
    sendq = SendQueue(lambda txt: asyncio.ensure_future(send_part(user_id, txt)))
    asyncio.run(sendq.flush(parts))
    redis_conn.set(f"last_ai_reply:{user_id}", time.time())
    for p in parts:
        ctx.add(f"bot: {p}")


if __name__ == "__main__":
    worker = SimpleWorker(queues=["default"], connection=redis_conn)
    worker.work()
