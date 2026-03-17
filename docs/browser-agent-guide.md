# Browser Agent and Web Retrieval Security Guide

This repository currently ships retriever agents and does **not** expose a first-party `browser_agent` service in `src/`.

When introducing browser automation for regulated-source capture, use this guide to align implementation with Azure production controls.

## 1. Security Objectives

- Prevent server-side request forgery (SSRF)
- Prevent data exfiltration to private networks
- Preserve auditable source provenance
- Enforce least-privilege execution

## 2. Network Guard Requirements

Before enabling browser fetch execution, block private and link-local ranges at minimum:

- `127.0.0.0/8`
- `10.0.0.0/8`
- `172.16.0.0/12`
- `192.168.0.0/16`
- `169.254.0.0/16`

Also block metadata endpoints and non-HTTP(S) schemes unless explicitly allow-listed.

## 3. Identity and Access (Azure)

- Place browser execution API behind API Management.
- Require Entra-authenticated caller identity.
- Enforce role-based authorization for script execution.
- Use managed identity for any downstream Azure resource access.

## 4. Execution Model

Recommended controls:

- Allow-list executable script IDs (no arbitrary code execution)
- Limit request timeout and concurrent sessions
- Sandbox filesystem and network egress
- Emit audit records for invocation, target host, and output hash

## 5. Data Handling

- Persist only required evidence artifacts.
- Hash captured payloads for tamper detection.
- Apply retention and encryption policies consistent with audit requirements.

## 6. Operations Checklist

- [ ] Host/domain allow-list configured
- [ ] Private-IP and metadata blocks validated
- [ ] Per-user rate limiting enabled
- [ ] Audit logs searchable by session and actor
- [ ] Incident response path documented for blocked/abusive requests
