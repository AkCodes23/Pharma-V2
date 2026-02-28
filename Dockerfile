# Pharma Agentic AI — Multi-stage Dockerfile
# Builds all Python services (Planner, Supervisor, Executor, Retriever Worker)
# Single Dockerfile with build target selection.

# ── Base stage ────────────────────────────────────────────
FROM python:3.12-slim AS base

WORKDIR /app

# OS-level dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[all]"

# Copy application code
COPY src/ ./src/

# Non-root user for security
RUN useradd --create-home appuser
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# ── Planner Agent ─────────────────────────────────────────
FROM base AS planner
ENV PORT=8000
EXPOSE 8000
CMD ["uvicorn", "src.agents.planner.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Supervisor Agent ──────────────────────────────────────
FROM base AS supervisor
ENV PORT=8001
EXPOSE 8001
CMD ["uvicorn", "src.agents.supervisor.main:app", "--host", "0.0.0.0", "--port", "8001"]

# ── Executor Agent ────────────────────────────────────────
FROM base AS executor
ENV PORT=8002
EXPOSE 8002
CMD ["uvicorn", "src.agents.executor.main:app", "--host", "0.0.0.0", "--port", "8002"]

# ── Retriever Worker ──────────────────────────────────────
FROM base AS retriever-worker
CMD ["python", "-m", "src.agents.retrievers.worker"]
