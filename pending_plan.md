# Pending Plan - Detailed Execution Roadmap

Last updated: 2026-03-02

This document tracks remaining work required to move from current state to stable demo and release readiness.

## 1. Current State Summary

Core architecture is implemented and running:
- Planner, Supervisor, Executor are service-hosted APIs.
- Retrievers run as worker-services with health endpoints.
- Service Bus topics/subscriptions are provisioned in Bicep.
- Session management, caching, audit, websocket lifecycle, and broker mapping have been aligned.
- Main documentation set has been rewritten and synchronized.

Remaining work is now concentrated in validation depth, security hardening, deployment automation maturity, and optional optimization paths.

## 2. Priority Model

- P0: demo/release blockers
- P1: near-term reliability and operational safety
- P2: scale/performance/security enhancements
- P3: optional platform expansion and optimization

## 3. Workstreams

## 3.1 P0 - Demo and Contract Blockers

### P0-1: End-to-end smoke test automation
Status: Pending
Owner: Platform

Goal:
- create one command/script to verify full flow in local compose:
  - health checks
  - session create
  - status progression
  - report retrieval

Acceptance criteria:
- script exits non-zero on failure
- script outputs session id and terminal status
- script verifies at least one retriever result is present

### P0-2: Frontend websocket utilization path validation
Status: Pending
Owner: Frontend + Platform

Goal:
- ensure UI actually uses planner websocket endpoint for live progress (or clearly documents polling-only behavior)

Acceptance criteria:
- no path mismatch (`/ws/sessions/{id}`)
- fallback to polling behaves correctly

### P0-3: Environment boot checklist for demo operators
Status: Pending
Owner: Platform

Goal:
- produce one page with exact environment values and startup commands for reproducible demo setup

Acceptance criteria:
- includes required env vars
- includes expected healthy service list
- includes recovery steps

## 3.2 P1 - Reliability and Ops Hardening

### P1-1: Test environment parity for unit collection
Status: Pending
Owner: QA

Current known blockers:
- missing local packages (for example `respx`, Azure SDKs)
- missing OpenAI env values during test import

Goal:
- make default test setup deterministic for contributors

Acceptance criteria:
- test collection passes in standard dev setup
- dependency instructions are codified

### P1-2: API auth/rate-limit policy consolidation
Status: Pending
Owner: Backend

Goal:
- standardize auth and rate-limit expectations across planner and MCP integration paths

Acceptance criteria:
- documented auth strategy
- explicit behavior for unauthorized and throttled requests

### P1-3: Runbook-backed incident drills
Status: Pending
Owner: Ops

Goal:
- execute dry-run playbooks for:
  - retriever subscription mismatch
  - websocket stream degradation
  - Cosmos write failures

Acceptance criteria:
- incident steps validated against current stack
- runbook corrections applied after drills

### P1-4: CI pipeline simplification and gating
Status: Pending
Owner: DevEx

Goal:
- ensure one canonical CI path, avoid duplicate/conflicting workflows

Acceptance criteria:
- single required workflow for merge gate
- static checks + tests + image build validation included

## 3.3 P2 - Security, Scale, and Performance

### P2-1: Managed identity and secret flow full production validation
Status: Pending
Owner: Cloud

Goal:
- validate end-to-end Key Vault + identity access in deployed environment

Acceptance criteria:
- no hardcoded production secrets
- service startup succeeds with key vault-backed config path

### P2-2: Network boundary hardening in deployed topology
Status: Pending
Owner: Cloud Security

Goal:
- align deployment with stated private networking posture

Acceptance criteria:
- documented target network model
- implemented controls verified per environment

### P2-3: Load and throughput benchmarking
Status: Pending
Owner: Performance

Goal:
- quantify throughput and latency under representative concurrency

Acceptance criteria:
- baseline metrics captured (p50/p95)
- bottlenecks identified and prioritized

### P2-4: Long-run stability test
Status: Pending
Owner: Platform

Goal:
- execute soak test for session processing and resource stability

Acceptance criteria:
- no critical memory growth trend
- no uncontrolled error accumulation

## 3.4 P3 - Platform Expansion

### P3-1: Additional E2E scenarios
Status: Pending
Owner: QA

Goal:
- add multiple domain scenarios beyond single sample flow

Acceptance criteria:
- positive and negative path coverage expanded

### P3-2: MCP feature expansion
Status: Pending
Owner: Integrations

Goal:
- add advanced tools/resources as needed for client workflows

Acceptance criteria:
- versioned tool contract documentation
- compatibility validation for existing clients

### P3-3: DPO/ML pipeline operationalization
Status: Pending
Owner: ML Platform

Goal:
- move DPO path from implementation-complete to reproducible training/evaluation workflow

Acceptance criteria:
- data prep, training, and evaluation documented and testable

## 4. Immediate Next Sprint Proposal

Recommended sprint scope:
1. P0-1 smoke test automation
2. P0-2 websocket path validation in frontend
3. P1-1 deterministic test setup
4. P1-4 CI simplification

Expected outcome:
- reliable demo execution
- lower regression risk
- faster contributor onboarding

## 5. Detailed Task Checklist

### 5.1 Tooling and QA
- [ ] add `scripts/smoke_e2e.ps1` for compose flow verification
- [ ] add minimal test bootstrap script for dev dependencies
- [ ] add CI check for endpoint path contract drift

### 5.2 Frontend and UX
- [ ] verify websocket usage in dashboard flow
- [ ] display clear state transitions and terminal status
- [ ] confirm report retrieval UX for completed sessions

### 5.3 Backend and Contracts
- [ ] ensure planner endpoint docs remain source-aligned
- [ ] verify supervisor/executor invocation contract is stable
- [ ] add guard checks for unsupported report format requests

### 5.4 Infrastructure
- [ ] verify service bus subscriptions in deployed namespace
- [ ] verify retriever containers set explicit `SERVICE_BUS_SUBSCRIPTION`
- [ ] verify health probes map to actual bound ports

### 5.5 Security and Ops
- [ ] define and implement auth baseline for external API surfaces
- [ ] define secret rotation operational process
- [ ] define alert thresholds for session failures and DLQ growth

## 6. Exit Criteria for "Release Ready"

Minimum criteria:
1. automated smoke test passes in clean environment
2. all critical services healthy and observable
3. end-to-end session succeeds with report output
4. key runbooks validated by dry run
5. required docs synchronized with deployed behavior

## 7. Change Management Rules

Whenever changing contracts or infrastructure:
- update code
- update docs in same PR
- include migration note in PR description
- include rollback steps for high-impact changes

## 8. Risks and Mitigations

Risk: contract drift between planner, MCP, frontend
- Mitigation: add contract tests and one source-of-truth endpoint map

Risk: test instability due environment prerequisites
- Mitigation: bootstrap script + locked dev dependency set

Risk: demo failure from configuration mismatch
- Mitigation: pre-demo checklist and smoke script execution

Risk: hidden performance bottlenecks
- Mitigation: scheduled load tests and tracked baseline metrics

## 9. Ownership Matrix

- Platform Core: planner/retriever/supervisor/executor runtime
- Cloud/IaC: bicep, deployment surfaces, identity/network
- Frontend: dashboard UX and streaming behavior
- QA: test harness and regression coverage
- DevEx: CI/CD and developer workflow
- Security: auth and secret governance

## 10. Notes

- This plan supersedes older broad inventory sections and focuses on actionable next steps.
- Historical completed work is documented in commit history and updated docs.
