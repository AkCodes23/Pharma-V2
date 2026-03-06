# Azure Removal Matrix (Standalone Demo Branch)

| Capability | Production Dependency | Demo Replacement | Notes |
|---|---|---|---|
| Session state + audit | Azure Cosmos DB | PostgreSQL (`PostgresSessionStore`) | JSON payload persisted in `demo_sessions` and `demo_audit`. |
| Task bus | Azure Service Bus topics/subscriptions | Kafka topics (`*-tasks`) | Topics created by `kafka-init` container using the same pillar routing contract as production. |
| Report artifact storage | Azure Blob Storage | MinIO bucket (`reports`) | S3-compatible upload path. |
| Intent decomposition | Azure OpenAI chat completions | Fixture decomposer | Deterministic fixture selection by query token match. |
| Report synthesis | Azure OpenAI report prompt | Fixture report generator | Deterministic decision logic + markdown template. |
| Semantic validation assist | Azure OpenAI LLM-as-judge | Disabled in demo | Rule-based validation retained. |
| Knowledge retrieval | Azure AI Search | Fixture knowledge payloads | No network calls in demo mode. |
| News retrieval | Tavily + web egress | Fixture news payloads | Predictable static signals for demos. |
| Authentication | Entra-aligned headers | Anonymous demo auth middleware | `X-Demo-User` optional override. |

## Guardrails
- `APP_MODE=standalone_demo` with `DEMO_OFFLINE=true` is required.
- `assert_url_allowed_for_demo` blocks Azure-domain HTTP requests when offline demo mode is active.
- Production Azure deployment assets remain unchanged and are not removed from the repository.
