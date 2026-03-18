# Frontend Architecture Guide

This guide documents the production-facing architecture of the Next.js frontend (`src/frontend/`) and how it integrates with Azure-hosted backend services.

## 1. Stack and Runtime

- Framework: Next.js + React + TypeScript
- App entry: `src/frontend/src/app/page.tsx`
- Component tree: `src/frontend/src/components/*`
- Data sources: Planner API (`:8000`) and report endpoints

For Azure deployments, frontend traffic should be routed through API Management for auth, rate limiting, and observability consistency.

## 2. Component Organization

Key UI domains are organized by responsibility:

- `components/auth/`: role entry and user identity controls
- `components/chat/`: query composition and session interaction
- `components/orchestration/`: task graph and workflow progress views
- `components/research/`: evidence cards and analysis workspace
- `components/resources/`: visual analytics widgets and metrics views
- `components/shell/`, `components/admin/`: layout and operator/admin panels

This structure mirrors backend workflow stages (`PLANNING` → `RETRIEVING` → `VALIDATING` → `SYNTHESIZING` → `COMPLETED`).

## 3. Data and Session Flow

Typical user flow:

1. Submit query to `POST /api/v1/sessions`.
2. Poll `GET /api/v1/sessions/{session_id}` for workflow state.
3. Consume optional live updates from `WS /ws/sessions/{session_id}`.
4. Retrieve artifacts from `GET /api/v1/sessions/{session_id}/report`.

Production recommendation (Azure):

- Keep backend base URL behind API Management.
- Use short polling intervals with exponential backoff under load.
- Prefer websocket updates when available to reduce read pressure on Cosmos.

## 4. Auth and Access Model

The frontend must pass caller identity in a way compatible with backend auth mode:

- `demo_token`: bearer token from demo login flow
- `header`: `X-User-Id` injected upstream (for trusted gateway/development)
- `anonymous`: demo-only fallback mode

For production, use Entra ID + API Management to issue/validate caller identity, and avoid direct browser-to-service trust.

## 5. Production Hardening (Azure)

- Enforce HTTPS only at ingress.
- Restrict CORS origins to approved frontend domains.
- Route all API calls through API Management policy layer.
- Surface health and latency via Application Insights dashboards.
- Keep frontend environment values secret-free (no API keys in browser bundles).

## 6. Operational Notes

- Keep API contract updates synchronized with `docs/api-integration-guide.md`.
- Keep workflow/service topology updates synchronized with `agents.md`.
- Run `npm run lint`, `npm run typecheck`, and `npm run build` from `src/frontend/` for frontend changes.
