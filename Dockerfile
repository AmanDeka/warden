FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies into the system Python (no venv needed inside the container)
RUN uv pip install --system --no-cache .

# Copy application source
COPY bot/ ./bot/

# Persistent volume mount point for SQLite
VOLUME ["/data"]

ENV DB_PATH=/data/warden.db

CMD ["python", "-m", "bot.main"]
