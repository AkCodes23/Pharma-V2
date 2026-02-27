ARG AGENT_MODULE=legal

FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

FROM python:3.12-slim

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ ./src/

ARG AGENT_MODULE
ENV AGENT_MODULE=${AGENT_MODULE}

USER appuser
EXPOSE 8001

CMD python -m src.agents.retrievers.${AGENT_MODULE}.main
