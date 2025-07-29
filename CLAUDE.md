# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

This is a Python-based Telegram bot that uses Redis queues and Docker for deployment:

- **Run locally**: `python -m app.telegram_bot` (bot) + `python -m app.worker` (worker)
- **Docker build**: `docker build .`
- **Docker compose**: `docker-compose up` (includes Redis, bot, and 2 workers)
- **Scale workers**: `docker-compose up --scale worker=N`
- **Test LLM connection**: `python test.py`

## Architecture Overview

This is a **distributed Telegram bot** that processes user messages through a queue-based architecture:

### Core Components

1. **Telegram Bot** (`app/telegram_bot.py`): 
   - Single-instance bot using long-polling
   - Maintains per-user `Chunker` and `SendQueue` instances
   - Cancels in-flight responses when new messages arrive
   - Delegates processing to Redis queue workers

2. **Worker** (`app/worker.py`):
   - RQ workers that process queued "thoughts" 
   - Calls LLM via `LLMGateway` and manages conversation context
   - Horizontally scalable (default: 2 workers)

3. **Chunker** (`core/chunker.py`):
   - Buffers rapid user messages into complete "thoughts"
   - Emits thoughts after 1.5s timeout + conditions
   - Uses Redis to prevent duplicate processing

4. **Context Manager** (`core/context_manager.py`):
   - Rolling 6-hour conversation window (min 100 messages)
   - Stores timestamped user/bot exchanges

5. **Send Queue** (`core/send_queue.py`):
   - Streams multi-part bot replies with human-like typing delays
   - Cancellable to handle interruptions

6. **LLM Gateway** (`services/llm_gateway.py`):
   - Supports both Ollama (port 11434) and OpenAI APIs
   - Uses async HTTP client with connection management

### Key Patterns

- **Per-user state**: Bot maintains separate chunkers/queues per `user_id`
- **Async/sync bridge**: Bot uses `asyncio.run_coroutine_threadsafe()` to bridge telebot (sync) with async components
- **Graceful cancellation**: New user messages cancel in-flight bot responses
- **Queue-based processing**: Heavy LLM work happens in background workers

### Configuration

Environment variables (in `.env`):
- `TG_BOT_TOKEN`: Telegram bot token from BotFather
- `LLM_API_URL`: LLM endpoint (e.g., `http://192.168.0.42:11434` for Ollama)
- `LLM_MODEL`: Model name (e.g., `bettergpt:latest`)
- `REDIS_HOST`: Redis connection (defaults to `redis` in Docker)

### Dependencies

Key Python packages: `pyTelegramBotAPI`, `redis`, `rq`, `httpx`, `pydantic`