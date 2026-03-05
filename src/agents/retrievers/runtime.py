"""
Runtime helpers for retriever agent services.

Each retriever runs as:
1. A background Service Bus worker loop.
2. A lightweight FastAPI process for health checks.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import TypeVar

import uvicorn
from fastapi import FastAPI

from src.agents.retrievers.base_retriever import BaseRetriever
from src.shared.bootstrap import bootstrap_agent
from src.shared.bootstrap.providers import create_session_store
from src.shared.infra.audit import AuditService

logger = logging.getLogger(__name__)

RetrieverT = TypeVar("RetrieverT", bound=BaseRetriever)


def create_retriever_app(
    retriever_cls: type[RetrieverT],
    *,
    agent_name: str,
    default_subscription: str,
) -> FastAPI:
    """Create a FastAPI app that hosts a retriever worker lifecycle."""
    retriever: RetrieverT | None = None
    audit: AuditService | None = None
    worker_thread: threading.Thread | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal retriever, audit, worker_thread

        bootstrap_agent(agent_name=agent_name)

        session_store = create_session_store()
        session_store.ensure_containers()
        audit = AuditService(session_store)

        subscription_name = os.getenv("SERVICE_BUS_SUBSCRIPTION", default_subscription)
        retriever = retriever_cls(cosmos=session_store, audit=audit, subscription_name=subscription_name)

        worker_thread = threading.Thread(
            target=retriever.start,
            name=f"{agent_name}-worker",
            daemon=True,
        )
        worker_thread.start()

        logger.info(
            "Retriever service started",
            extra={"agent": agent_name, "subscription": subscription_name},
        )
        yield

        if retriever is not None:
            retriever.stop()
        if audit is not None:
            audit.shutdown()
        if worker_thread is not None:
            worker_thread.join(timeout=5)

        logger.info("Retriever service stopped", extra={"agent": agent_name})

    app = FastAPI(
        title=f"{agent_name} service",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "healthy", "service": agent_name}

    return app


def run_retriever_service(app: FastAPI) -> None:
    """Run retriever app for local/dev and container startup."""
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
