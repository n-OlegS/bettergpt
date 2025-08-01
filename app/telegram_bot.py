# ========================= app/telegram_bot.py =========================
"""
Telegram bot transport (pytelegrambotapi)

‣ Uses long-polling for dev ease.
‣ One Chunker + one SendQueue per user_id (stored in dicts).
‣ Cancels an in-flight SendQueue whenever a new message from that user arrives.
"""
from __future__ import annotations
import dotenv
import threading, asyncio, time
from typing import Dict

import telebot
from redis import Redis
from rq import Queue

from core.chunker import Chunker
from core.send_queue import SendQueue

# --------------------------------------------------------------------- #
#  Config
# --------------------------------------------------------------------- #
dotenv.load_dotenv()
BOT_TOKEN = dotenv.get_key("../.env", "TG_BOT_TOKEN")         # botfather token
redis = Redis()
rq_queue = Queue(connection=redis)

loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# Per-user state
chunkers: Dict[int, Chunker] = {}
send_queues: Dict[int, SendQueue] = {}

# --------------------------------------------------------------------- #
#  Helper to send a message (telebot is sync, so wrap in loop.run_in_executor)
# --------------------------------------------------------------------- #


def _sync_send(user_id: int, text: str):
    """Blocking send; runs in threadpool, so we don't block asyncio loop."""
    bot.send_message(user_id, text)


def _sync_reset_elapsed(user_id: int):
    chunkers[user_id].reset_elapsed()


async def send_part_old(user_id: int, text: str):
    await loop.run_in_executor(None, _sync_send, user_id, text)


async def reset_elapsed(user_id: int):
    cur_loop = asyncio.get_running_loop()
    cur_loop.run_in_executor(None, _sync_reset_elapsed, user_id)


async def send_part(user_id: int, text: str):
    # always get the loop that’s actually running this coroutine
    cur_loop = asyncio.get_running_loop()
    await cur_loop.run_in_executor(None, _sync_send, user_id, text)

# --------------------------------------------------------------------- #
#  Incoming message handler
# --------------------------------------------------------------------- #
@bot.message_handler(content_types=["text"])
def on_message(message: telebot.types.Message):
    user_id = message.from_user.id
    text = message.text
    print(f"📥 BOT: Received message from user {user_id}: '{text}'")

    # ---------------- cancel an in-flight bot reply ------------------ #
    sq = send_queues.get(user_id)
    cancel_key = f"cancel_reply:{user_id}"
    
    # Check if there's an active response 
    last_ai_time_key = f"last_ai_reply:{user_id}"
    response_started_key = f"response_started:{user_id}"
    response_in_progress = False
    
    # Check for response currently being streamed
    if redis.exists(response_started_key):
        response_started_time = float(redis.get(response_started_key).decode())
        print(f"🔄 BOT: Response currently streaming (started {time.time() - response_started_time:.1f}s ago)")
        response_in_progress = True
    # Check for recent completed response that might still be relevant
    elif redis.exists(last_ai_time_key):
        last_ai_time = float(redis.get(last_ai_time_key).decode())
        # Consider response in progress if it was within last 30 seconds
        if time.time() - last_ai_time < 30:
            response_in_progress = True
            print(f"🔄 BOT: Recent response detected (last AI reply {time.time() - last_ai_time:.1f}s ago)")
    
    if sq:
        print(f"❌ BOT: Cancelling existing SendQueue for user {user_id}")
        sq.cancel()                 # stop any queued parts immediately
        # Also set Redis cancellation signal for worker's SendQueue
        redis.set(cancel_key, "1", ex=10)  # expires in 10 seconds
        print(f"🚩 BOT: Set Redis cancel signal '{cancel_key}' (expires in 10s)")
    elif response_in_progress:
        print(f"❌ BOT: No local SendQueue but response in progress, setting cancel signal")
        # Set Redis cancellation signal for worker's SendQueue
        redis.set(cancel_key, "1", ex=10)  # expires in 10 seconds
        print(f"🚩 BOT: Set Redis cancel signal '{cancel_key}' (expires in 10s)")
    else:
        print(f"ℹ️ BOT: No response in progress, not setting cancel signal")

    # ---------------- feed text into the user's chunker -------------- #
    ch = chunkers.setdefault(user_id, Chunker(timeout=1.5, user_id=user_id))
    print(f"🧠 BOT: Using chunker for user {user_id}")

    # Chunker is async, pytelegrambotapi is sync → delegate to event-loop
    print(f"🔄 BOT: Feeding text to chunker...")
    thought = asyncio.run_coroutine_threadsafe(ch.feed(text), loop).result()
    print(f"🔄 BOT: Chunker.feed() completed")

    if thought:                     # a full "thought" is ready
        print(f"💡 BOT: Thought formed: '{thought}'")
        # enqueue background job for the worker
        job = rq_queue.enqueue("app.worker.process_thought", user_id, thought)
        print(f"📋 BOT: Enqueued job {job.id} for worker")
    else:
        print(f"⏳ BOT: No thought formed yet, waiting for more input...")


# --------------------------------------------------------------------- #
#  Start polling (blocking)
# --------------------------------------------------------------------- #
def main():
    print("Bot is polling…")
    bot.infinity_polling()          # will reconnect on errors


if __name__ == "__main__":
    main()
