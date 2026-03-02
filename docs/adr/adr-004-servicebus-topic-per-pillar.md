# ADR-004: Service Bus Topic–Per–Pillar Routing

**Status:** Accepted  
**Date:** 2026-03-02  
**Decision Makers:** Platform Engineering Team

## Context

The Pharma Agentic AI platform decomposes user queries into parallel tasks across 6 pillars (Legal, Clinical, Commercial, Social, Knowledge, News). Each pillar has a dedicated retriever agent. We need a message routing strategy that:

1. Supports independent scaling per pillar (Clinical may need 20x more capacity than News)
2. Allows adding new pillars without modifying existing agents
3. Provides dead-letter handling per pillar for isolation
4. Enables KEDA-based autoscaling based on queue depth

## Decision

**Use one Azure Service Bus topic per pillar** (e.g., `legal-tasks`, `clinical-tasks`) with one subscription per retriever agent. The Planner publishes to the topic matching each task's `PillarType`, and each retriever subscribes to exactly one topic.

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| Single topic + SQL filters | Simpler Bicep, fewer resources | Filters add latency, shared DLQ, no per-pillar scaling |
| Direct queues (no pub/sub) | Lowest latency | No fan-out, harder to add observers/loggers |
| **Topic-per-pillar** ✅ | Independent scaling, isolated DLQs, KEDA-friendly | More resources to manage |

## Consequences

- Each topic needs a subscription defined in Bicep (6 topics × 1 subscription = 6 resources)
- `ServiceBusPublisher._topic_map` must map every `PillarType` to its topic name
- Adding a new pillar requires: new topic in Bicep, new entry in `_topic_map`, new retriever deployment
- KEDA ScaledObjects target individual topic subscriptions for per-pillar autoscaling
