# Standalone Demo Dependency Map

This document inventories Azure-linked dependencies in production codepaths and the standalone demo replacements used on `feature/standalone-demo`.

## Planner / Orchestration
- Azure OpenAI decomposition (`src/agents/planner/decomposer.py`) -> `FixtureDecomposer` via provider factory.
- Azure Service Bus publisher (`src/shared/infra/servicebus_client.py`) -> `KafkaTaskBusPublisher`.
- Azure Cosmos DB session persistence (`src/shared/infra/cosmos_client.py`) -> `PostgresSessionStore`.

## Retriever Runtime
- Azure Service Bus consumer (`src/shared/infra/servicebus_client.py`) -> `KafkaTaskBusConsumer`.
- External pillar APIs (FDA, ClinicalTrials, Tavily, etc.) -> fixture loader responses when `DEMO_OFFLINE=true`.
- Cosmos result writes -> PostgreSQL JSON session document updates.

## Supervisor
- LLM semantic validation via Azure OpenAI -> deterministic rule-based validation only in demo mode.
- Cosmos validation persistence -> PostgreSQL session store.

## Executor
- Azure OpenAI report generation (`src/agents/executor/report_generator.py`) -> `FixtureReportGenerator`.
- Azure Blob report upload (`src/agents/executor/pdf_engine.py`) -> `MinioObjectStore` upload.

## Auth
- Entra/header-based identity assumptions -> anonymous demo middleware (`src/shared/infra/demo_auth.py`) with `X-Demo-User` override.

## Health/Infra Checks
- Azure-specific deep health checks -> provider-aware checks for PostgreSQL, Redis, Kafka, MinIO in demo mode.

## Production Assets Preserved
- `infra/bicep/`
- Azure-oriented workflows under `.github/`
- Azure client modules retained for non-demo provider selections.
