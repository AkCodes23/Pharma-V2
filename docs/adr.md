# ADR-001: Dual Graph Backend (Neo4j + Cosmos Gremlin)

## Status

Accepted

## Context

The platform uses a knowledge graph to store pharmaceutical entities (drugs, companies, indications) and their relationships. The original implementation used Neo4j with Cypher queries. The Azure migration requires moving to Cosmos DB Gremlin API in production while keeping Neo4j available for local development.

## Decision

Implement a **feature-flagged dual-backend** `GraphClient` that supports both Neo4j (Cypher) and Cosmos Gremlin (Gremlin traversal language) in the same class. The backend is selected at startup via `GREMLIN_USE_GREMLIN=true`.

## Consequences

- All entity ingestion and query methods have parallel implementations for both backends
- `_escape()` utility handles Gremlin string escaping to prevent injection
- NER service integration moved from returning 0 to actual entity extraction
- Testing requires both paths to be validated
- Rollback: Set `GREMLIN_USE_GREMLIN=false` to revert to Neo4j

---

# ADR-002: Real API Integrations with Graceful Fallback

## Status

Accepted

## Context

All 5 retriever agents initially used mock/placeholder data. For production readiness, each must call real external APIs. However, these APIs (IPO, CDSCO in particular) may be unreliable — scraping government websites is inherently fragile.

## Decision

Replace all mocks with real API calls. For web-scraped sources (IPO, CDSCO), implement **explicit `DATA_UNAVAILABLE` fallback records** instead of returning mock data. This ensures the downstream Supervisor can make informed decisions about data quality.

## Consequences

- Legal: IPO returns `DATA_UNAVAILABLE` on scrape failure with `data_source: 'ipo_fallback'`
- Clinical: CDSCO returns `DATA_UNAVAILABLE` on failure with `data_source: 'cdsco_fallback'`
- Commercial: SEC EDGAR + Yahoo Finance are resilient (free APIs with high uptime)
- Social: PubMed E-utilities is very reliable (NCBI API)
- Supervisor can distinguish real data from unavailable data in quality assessment

---

# ADR-003: Azure Web PubSub vs. In-Memory WebSocket

## Status

Accepted

## Context

Real-time session updates need to reach frontend clients. In development, a simple in-memory WebSocket manager with Redis Pub/Sub fan-out works. In production with multiple AKS pods, a managed solution is needed.

## Decision

Use **Azure Web PubSub** in production (feature-flagged via `WEB_PUBSUB_USE_AZURE`). The `WebPubSubManager` uses REST API for server→client push. Clients connect directly to the PubSub endpoint using a negotiated token. The local `ConnectionManager` is preserved for development with replay buffers and heartbeat timeout.

## Consequences

- Clients must call `GET /ws/negotiate` to get PubSub connection URL + token in production
- Server broadcasts via Web PubSub REST API (no WebSocket connection from server)
- Local development unchanged — still uses in-process WebSocket
