# Agent-to-Agent (A2A) Protocol Guide

This guide expands the A2A runtime contract defined in `src/shared/a2a/protocol.py` for production use.

## 1. Protocol Purpose

A2A enables controlled inter-agent coordination for:

- capability discovery,
- delegated task execution,
- structured result reporting,
- human escalation for low-confidence outcomes.

## 2. Message Types

Defined in `A2AMessageType`:

- `discover`
- `delegate`
- `report`
- `escalate`
- `heartbeat`
- `ack`
- `negotiate`
- `invoke`

Envelope model: `A2AMessage`.

## 3. Transport and Topics

Current protocol implementation publishes to:

- `pharma.events.a2a`

Transport abstraction supports:

- Kafka/Event Hubs in event mode
- Service Bus via broker abstraction in production-oriented flows

Maintain one canonical contract regardless of transport backend.

## 4. Reliability Controls

- Include `session_id` and `correlation_id` for traceability.
- Use `ttl_seconds` to bound stale work.
- Record `execution_time_ms` and confidence in `report` payloads.
- Route low-confidence outputs through `escalate` path.

## 5. Azure Production Guidance

- Use managed identity/authenticated broker access.
- Restrict topic send/receive permissions by agent role.
- Emit A2A events to centralized telemetry and audit stores.
- Alert on escalation spikes and expired message rates.

## 6. Integration Checklist

- [ ] Agent capabilities are explicitly declared
- [ ] Delegation payload schemas are validated
- [ ] Correlation IDs propagate across services
- [ ] Escalation handlers and human review queues are configured
- [ ] A2A metrics are exported to dashboards
