-- ============================================================
-- Pharma Agentic AI — PostgreSQL Init Script
-- ============================================================
-- Runs on first 'docker compose up' only (idempotent).
-- Creates the analytics schema alongside the celery results DB.
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Sessions Table ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         VARCHAR(255) NOT NULL,
    query           TEXT NOT NULL,
    drug_name       VARCHAR(255),
    brand_name      VARCHAR(255),
    target_market   VARCHAR(100),
    time_horizon    VARCHAR(50),
    therapeutic_area VARCHAR(255),
    status          VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    decision        VARCHAR(50),
    decision_rationale TEXT,
    report_url      TEXT,
    excel_url       TEXT,
    grounding_score FLOAT,
    conflict_count  INTEGER DEFAULT 0,
    total_tasks     INTEGER DEFAULT 0,
    completed_tasks INTEGER DEFAULT 0,
    failed_tasks    INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_drug ON sessions(drug_name);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at DESC);

-- ── Tasks Table ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    pillar          VARCHAR(50) NOT NULL,
    description     TEXT,
    status          VARCHAR(50) NOT NULL DEFAULT 'QUEUED',
    retry_count     INTEGER DEFAULT 0,
    error_message   TEXT,
    execution_time_ms INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_tasks_pillar ON tasks(pillar);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

-- ── Agent Results Table ───────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_results (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agent_type      VARCHAR(50) NOT NULL,
    pillar          VARCHAR(50) NOT NULL,
    findings        JSONB NOT NULL DEFAULT '{}',
    citation_count  INTEGER DEFAULT 0,
    confidence      FLOAT NOT NULL DEFAULT 0.0,
    execution_time_ms INTEGER NOT NULL DEFAULT 0,
    raw_api_response_url TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_results_session ON agent_results(session_id);
CREATE INDEX IF NOT EXISTS idx_results_pillar ON agent_results(pillar);
CREATE INDEX IF NOT EXISTS idx_results_agent ON agent_results(agent_type);

-- ── Citations Table ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS citations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    result_id       UUID NOT NULL REFERENCES agent_results(id) ON DELETE CASCADE,
    source_name     VARCHAR(255) NOT NULL,
    source_url      TEXT NOT NULL,
    data_hash       VARCHAR(64) NOT NULL,
    excerpt         TEXT,
    retrieved_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_citations_result ON citations(result_id);
CREATE INDEX IF NOT EXISTS idx_citations_source ON citations(source_name);

-- ── Audit Trail Table ─────────────────────────────────────
-- Mirrors Cosmos DB audit_trail for analytics queries
CREATE TABLE IF NOT EXISTS audit_trail (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      UUID NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id         VARCHAR(255) NOT NULL,
    agent_id        VARCHAR(255) NOT NULL,
    agent_type      VARCHAR(50) NOT NULL,
    action          VARCHAR(50) NOT NULL,
    payload_hash    VARCHAR(64) NOT NULL,
    details         JSONB DEFAULT '{}',
    ip_address      VARCHAR(45),
    correlation_id  VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_trail(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_trail(action);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_trail(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_trail(user_id);

-- ── Analytics Materialized Views ──────────────────────────

-- Session duration analytics
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_session_analytics AS
SELECT
    date_trunc('hour', created_at) AS hour_bucket,
    COUNT(*) AS total_sessions,
    COUNT(*) FILTER (WHERE status = 'COMPLETED') AS completed_sessions,
    COUNT(*) FILTER (WHERE status = 'FAILED') AS failed_sessions,
    AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) AS avg_duration_seconds,
    AVG(grounding_score) AS avg_grounding_score,
    COUNT(*) FILTER (WHERE decision = 'GO') AS go_decisions,
    COUNT(*) FILTER (WHERE decision = 'NO_GO') AS no_go_decisions,
    COUNT(*) FILTER (WHERE decision = 'CONDITIONAL_GO') AS conditional_go_decisions
FROM sessions
GROUP BY hour_bucket
ORDER BY hour_bucket DESC;

-- Pillar performance analytics
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_pillar_performance AS
SELECT
    pillar,
    COUNT(*) AS total_tasks,
    COUNT(*) FILTER (WHERE status = 'COMPLETED') AS completed_tasks,
    COUNT(*) FILTER (WHERE status = 'FAILED') AS failed_tasks,
    COUNT(*) FILTER (WHERE status = 'DLQ') AS dlq_tasks,
    AVG(execution_time_ms) AS avg_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY execution_time_ms) AS p95_latency_ms,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY execution_time_ms) AS p99_latency_ms
FROM tasks
WHERE execution_time_ms IS NOT NULL
GROUP BY pillar;

-- Drug analysis frequency
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_drug_frequency AS
SELECT
    drug_name,
    target_market,
    COUNT(*) AS query_count,
    COUNT(*) FILTER (WHERE decision = 'GO') AS go_count,
    COUNT(*) FILTER (WHERE decision = 'NO_GO') AS no_go_count,
    MAX(created_at) AS last_queried_at
FROM sessions
WHERE drug_name IS NOT NULL
GROUP BY drug_name, target_market
ORDER BY query_count DESC;

-- ── Agent Registry (for A2A Protocol) ─────────────────────
CREATE TABLE IF NOT EXISTS agent_registry (
    agent_id        VARCHAR(255) PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    agent_type      VARCHAR(50) NOT NULL,
    capabilities    JSONB NOT NULL DEFAULT '[]',
    input_schema    JSONB DEFAULT '{}',
    output_schema   JSONB DEFAULT '{}',
    endpoint        VARCHAR(500),
    health_check    VARCHAR(500),
    status          VARCHAR(50) DEFAULT 'ACTIVE',
    last_heartbeat  TIMESTAMPTZ DEFAULT NOW(),
    registered_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_registry_type ON agent_registry(agent_type);
CREATE INDEX IF NOT EXISTS idx_registry_status ON agent_registry(status);

-- ── Reflection Log (SPAR Framework) ──────────────────────
CREATE TABLE IF NOT EXISTS reflection_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      UUID NOT NULL,
    agent_type      VARCHAR(50) NOT NULL,
    reflection_type VARCHAR(50) NOT NULL,  -- 'citation_valid', 'timeout_detected', 'decision_consistent'
    score           FLOAT,
    findings        JSONB DEFAULT '{}',
    improvements    JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reflection_session ON reflection_log(session_id);
CREATE INDEX IF NOT EXISTS idx_reflection_type ON reflection_log(reflection_type);

-- ── RAG Document Store ────────────────────────────────────
CREATE TABLE IF NOT EXISTS rag_documents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename        VARCHAR(500) NOT NULL,
    content_hash    VARCHAR(64) NOT NULL UNIQUE,
    doc_type        VARCHAR(50),  -- 'pdf', 'csv', 'html'
    chunk_count     INTEGER DEFAULT 0,
    metadata        JSONB DEFAULT '{}',
    status          VARCHAR(50) DEFAULT 'PENDING',  -- PENDING, INDEXED, FAILED
    indexed_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    content         TEXT NOT NULL,
    content_hash    VARCHAR(64) NOT NULL,
    token_count     INTEGER,
    metadata        JSONB DEFAULT '{}',
    embedding_model VARCHAR(100),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON rag_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON rag_chunks(content_hash);

-- ── Long-Term Memory ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_memory (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         VARCHAR(255) NOT NULL,
    memory_type     VARCHAR(50) NOT NULL,  -- 'preference', 'query_pattern', 'decision_history'
    key             VARCHAR(255) NOT NULL,
    value           JSONB NOT NULL,
    access_count    INTEGER DEFAULT 0,
    last_accessed   TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, memory_type, key)
);

CREATE INDEX IF NOT EXISTS idx_memory_user ON user_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_memory_type ON user_memory(memory_type);

-- ── Celery Results DB ─────────────────────────────────────
CREATE DATABASE celery_results;

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO pharma;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO pharma;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✓ Pharma AI PostgreSQL schema initialized successfully';
END $$;
