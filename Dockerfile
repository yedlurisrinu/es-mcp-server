# ── Build stage ─────────────────────────────────────────────────────────────
FROM python:3.12.16-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# uv binary, pinned
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Install dependencies first (layer caching): only the manifest and lock
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ── Stage 2: Runtime ──────────────────────────────────────
FROM python:3.12.16-slim AS runtime

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy source code and static files
COPY src/ ./src/

# Set PYTHONPATH so imports resolve cleanly
ENV PYTHONPATH=src

# Non-root user for security
RUN adduser --disabled-password --gecos "" appuser
#Create folder for log files and giving user write permissions
RUN mkdir -p /app/logs/ && chown -R appuser:appuser /app/logs

USER appuser

# App listens on 8009
EXPOSE 8009

CMD ["python", "-m", "uvicorn", "main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8009", "--log-level", "info"]
