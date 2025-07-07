# ========================= app/telegram_bot.py =========================
"""
Telegram bot transport (pytelegrambotapi)

‣ Uses long-polling for dev ease.
‣ One Chunker + one SendQueue per user_id (stored in dicts).
‣ Cancels an in-flight SendQueue whenever a new message from that user arrives.
"""
from __future__ import annotations
import dotenv
import threading, asyncio
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

    # ---------------- cancel an in-flight bot reply ------------------ #
    sq = send_queues.get(user_id)
    if sq:
        sq.cancel()                 # stop any queued parts immediately

    # ---------------- feed text into the user’s chunker -------------- #
    ch = chunkers.setdefault(user_id, Chunker(timeout=1.5, user_id=user_id))
    print("Inited chunker", chunkers)

    # Chunker is async, pytelegrambotapi is sync → delegate to event-loop
    thought = asyncio.run_coroutine_threadsafe(ch.feed(text), loop).result()
    # ch.feed(text)
    print("Fed thought - telebot")

    if thought:                     # a full "thought" is ready
        # enqueue background job for the worker
        rq_queue.enqueue("app.worker.process_thought", user_id, thought)


# --------------------------------------------------------------------- #
#  Start polling (blocking)
# --------------------------------------------------------------------- #
def main():
    print("Bot is polling…")
    bot.infinity_polling()          # will reconnect on errors


if __name__ == "__main__":
    main()
