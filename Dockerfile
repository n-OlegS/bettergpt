# ─────────────── Dockerfile ───────────────
# Stage 1 ───────────────────────────────────
# “builder” image installs Python wheels in an
# isolated layer, then we copy just the built
# bits into a slim runtime image.

FROM python:3.11-slim AS builder
WORKDIR /build

# system libs for common wheels (lxml, numpy, etc.)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
         build-essential gcc curl && \
    rm -rf /var/lib/apt/lists/*

# keep the layer cache efficient: copy only reqs first
COPY requirements.txt .

# install deps into /install (not into site-packages yet)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2 ───────────────────────────────────
# lightweight runtime image (~150 MB)

FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# copy installed site-packages from builder
COPY --from=builder /install /usr/local

# copy *your* source code
COPY . .

# default command (overridden in docker-compose)
CMD ["python", "-m", "app.telegram_bot"]
# ───────────────────────────────────────────
