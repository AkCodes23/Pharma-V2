"""
Pharma Agentic AI — Celery Application.

Async task queue for background workloads: PDF generation,
RAG document indexing, analytics pipeline, and materialized
view refresh.

Architecture context:
  - Service: Background workers (Celery)
  - Responsibility: Offload heavy/slow tasks from the hot path
  - Upstream: Executor Agent, API endpoints, Celery Beat scheduler
  - Downstream: Blob Storage (PDFs), PostgreSQL (analytics), Vector Store (RAG)
  - Broker: Redis (low-latency, same instance as cache)
  - Result backend: PostgreSQL (durable, queryable)

Performance optimizations:
  - Queue routing: Separate queues for PDF, RAG, analytics
  - Concurrency: 4 workers default, configurable per queue
  - Max tasks per child: 100 (prevents memory leaks)
  - Task acks late: True (at-least-once delivery)
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

from src.shared.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# ── Celery App Configuration ──────────────────────────────

app = Celery(
    "pharma_agentic_ai",
    broker=settings.celery.broker_url,
    backend=settings.celery.result_backend,
)

app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Reliability
    task_acks_late=True,       # Ack AFTER task completes (at-least-once)
    worker_prefetch_multiplier=1,  # Fair scheduling
    task_reject_on_worker_lost=True,

    # Concurrency
    worker_concurrency=4,
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks (memory hygiene)

    # Queue routing
    task_routes={
        "src.shared.tasks.pdf_task.*": {"queue": "pharma.pdf"},
        "src.shared.tasks.rag_task.*": {"queue": "pharma.rag"},
        "src.shared.tasks.analytics_task.*": {"queue": "pharma.analytics"},
    },

    # Default queue for unrouted tasks
    task_default_queue="celery",

    # Result expiration (7 days)
    result_expires=timedelta(days=7),

    # Task time limits
    task_soft_time_limit=300,   # 5 min soft limit
    task_time_limit=600,        # 10 min hard limit

    # Beat schedule (periodic tasks)
    beat_schedule={
        "refresh-materialized-views": {
            "task": "src.shared.tasks.analytics_task.refresh_materialized_views",
            "schedule": timedelta(minutes=15),
            "options": {"queue": "pharma.analytics"},
        },
        "cleanup-stale-sessions": {
            "task": "src.shared.tasks.analytics_task.cleanup_stale_sessions",
            "schedule": timedelta(hours=1),
            "options": {"queue": "pharma.analytics"},
        },
        "rag-reindex": {
            "task": "src.shared.tasks.rag_task.reindex_documents",
            "schedule": crontab(hour=2, minute=0),  # Daily at 2 AM UTC
            "options": {"queue": "pharma.rag"},
        },
        "agent-health-check": {
            "task": "src.shared.tasks.analytics_task.check_agent_health",
            "schedule": timedelta(minutes=5),
            "options": {"queue": "pharma.analytics"},
        },
    },
)

# Auto-discover tasks in these modules
app.autodiscover_tasks(["src.shared.tasks"])
