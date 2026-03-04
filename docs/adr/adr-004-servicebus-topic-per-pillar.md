# ADR-004: Service Bus Topic-Per-Pillar Routing

Status: Accepted
Date: 2026-03-02
Decision owners: Platform Engineering

## Context

The platform executes independent retriever workloads per pillar. These workloads have different latency and failure profiles, and must scale independently.

Requirements:
1. independent consumer scaling by pillar
2. isolated failure and retry behavior
3. clear routing from planner task pillar to consumer queue/subscription
4. compatibility with local Kafka development mode

## Decision

Use one Service Bus topic per pillar in Azure:
- `legal-tasks`
- `clinical-tasks`
- `commercial-tasks`
- `social-tasks`
- `knowledge-tasks`
- `news-tasks`

Use one primary subscription per retriever:
- `retriever-legal-sub`
- `retriever-clinical-sub`
- `retriever-commercial-sub`
- `retriever-social-sub`
- `retriever-knowledge-sub`
- `retriever-news-sub`

Use one monitoring subscription per topic for dead-letter visibility:
- `retriever-*-dlq-sub`

Legacy alias support (`pharma.tasks.*`) remains in compatibility mapping layers where needed, but is not the source of truth.

## Alternatives Considered

1. Single shared topic with filters
- Pros: fewer resources
- Cons: shared blast radius, harder per-pillar tuning, complex filter management

2. Queue-per-pillar without topics
- Pros: simple direct routing
- Cons: weaker fan-out extensibility for observers/aux consumers

3. Topic-per-pillar (chosen)
- Pros: clean pillar isolation, explicit contracts, straightforward scale control
- Cons: more resources to provision and manage

## Consequences

Positive:
- predictable routing and subscriptions
- cleaner operational troubleshooting
- easy addition of future pillars

Tradeoffs:
- IaC must stay synchronized with code subscription defaults
- additional resources increase configuration surface area

## Verification

Verify in IaC and runtime:
1. `infra/bicep/main.bicep` defines all topics/subscriptions.
2. retriever `default_subscription` values match Bicep names.
3. retriever deployment env `SERVICE_BUS_SUBSCRIPTION` overrides are set explicitly.

## Rollback

If a naming migration breaks consumers:
1. restore previous mapping aliases in broker/client code
2. redeploy with old subscription env values
3. backfill docs and migration notes before retrying cutover
