# ============================================================
# Pharma Agentic AI — Unified Dockerfile (Multi-Stage)
# ============================================================
# Builds: planner, supervisor, executor, retrievers, celery-worker
# Usage:  docker compose build
# ============================================================

FROM python:3.12-slim AS builder

WORKDIR /app

# Install system deps for WeasyPrint (PDF) and psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libffi-dev \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[dev]"

# ── Runtime Stage ──────────────────────────────────────────
FROM python:3.12-slim

# Install runtime deps (WeasyPrint needs these at runtime too)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libcairo2 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser -d /home/appuser -m appuser

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY src/ ./src/
COPY pyproject.toml .

# Ensure src is importable
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

USER appuser

# Default: planner agent (overridden in docker-compose.yml per service)
EXPOSE 8000
CMD ["uvicorn", "src.agents.planner.main:app", "--host", "0.0.0.0", "--port", "8000"]
