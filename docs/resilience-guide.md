# Resilience and Failure Modes Guide

This guide describes the platform resilience behavior used in retriever-heavy workflows and how to operate it in Azure.

## 1. Core Mechanisms

Implemented controls (primarily in `src/agents/retrievers/base_retriever.py`):

- Circuit breaker per retriever
- Timeout-controlled tool execution
- Retry loop with bounded attempts
- DLQ transition for unrecoverable failures
- Partial/degraded session progression support

## 2. Circuit Breaker Behavior

Retriever circuit breaker states:

- `CLOSED`: normal operation
- `OPEN`: request short-circuit after failure threshold
- `HALF_OPEN`: probation state after cooldown

Operational defaults (verify against current settings):

- Failure threshold: 3 consecutive failures
- Cooldown window: 60 seconds

## 3. Retry and DLQ Model

When tool execution fails:

1. Task transitions to `RETRYING` while attempts remain.
2. Backoff is applied for transient errors.
3. On max retries, task transitions to `DLQ`.
4. Audit trail records retry/failure/DLQ events.

In Azure, DLQ subscriptions should be monitored as a first-class SRE signal.

## 4. Timeout and Degraded Operation

Retriever calls are bounded by execution timeout. On timeout or upstream outage, retrievers should:

- return partial evidence where feasible,
- surface reduced confidence,
- preserve citations for available evidence,
- allow session-level degraded path handling.

This prevents full workflow collapse due to single-source failures.

## 5. Failure Mode Playbook

### A) Session stuck in `RETRIEVING`

- Check retriever health endpoints.
- Verify `SERVICE_BUS_SUBSCRIPTION` values.
- Check queue depth and DLQ growth.

### B) Sudden drop in evidence count

- Inspect source API status and error rates.
- Confirm circuit breakers are not broadly `OPEN`.
- Validate cached fallback freshness policy.

### C) High retriever latency

- Inspect timeout values and external API SLAs.
- Scale retriever replicas (Container Apps/KEDA).
- Reduce oversized payloads if source APIs throttle.

## 6. Azure Operations Guidance

- Use alerts on DLQ depth, retriever failure rate, and timeout spikes.
- Track `pharma.tasks.failed` and latency histograms in telemetry.
- Configure autoscaling for queue depth and CPU pressure.
- Run controlled chaos drills in non-production environments.

## 7. Verification Checklist

- [ ] Circuit breaker transitions observed and recover correctly
- [ ] Retry caps enforced
- [ ] DLQ routing works for repeated failures
- [ ] Sessions can complete with degraded evidence path
- [ ] Alerts fire for sustained error conditions
