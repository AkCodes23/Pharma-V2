"""
Pharma Agentic AI — MCP Server.

Exposes the Pharma AI platform to Claude and other MCP clients
via the Model Context Protocol. Allows LLMs to:
  - Create and monitor drug analysis sessions
  - Query FDA and ClinicalTrials databases directly
  - Inspect agent health and registry
  - Retrieve report URLs and streaming events

Server name: pharma_ai_mcp
Transport: streamable HTTP (port 8010) + stdio for local use

Architecture context:
  - Service: MCP gateway
  - Responsibility: External control plane for LLM clients
  - Upstream: MCP clients (Claude, Antigravity, Cursor, etc.)
  - Downstream: Planner API, Agent Registry, Postgres, Redis
  - Failure: All tools fail-safe with structured error responses
  - Security: API key required via X-API-Key header from Claude Desktop

Tool catalogue:
  1.  pharma_create_session        — Start a drug analysis
  2.  pharma_get_session           — Fetch session status + result
  3.  pharma_list_sessions         — List sessions for a drug or user
  4.  pharma_get_agent_status      — Live agent registry snapshot
  5.  pharma_search_fda            — Query FDA drug database
  6.  pharma_search_clinical_trials — Search ClinicalTrials.gov
  7.  pharma_get_report            — Retrieve PDF report URL
  8.  pharma_list_capabilities     — List all A2A capability contracts

Resources:
  pharma://sessions/{session_id}  — Live session document
  pharma://agents/active          — Active agent registry
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mcp.server.fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────
PLANNER_URL = os.getenv("PLANNER_URL", "http://planner:8000")
_API_KEY = os.getenv("PHARMA_INTERNAL_API_KEY", "")
PLANNER_WS_URL = (
    PLANNER_URL.replace("https://", "wss://")
    .replace("http://", "ws://")
    .rstrip("/")
)

# ── Shared HTTP client ────────────────────────────────────
_http: httpx.AsyncClient | None = None


def _get_http() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(
            base_url=PLANNER_URL,
            timeout=httpx.Timeout(connect=3.0, read=60.0, write=5.0, pool=1.0),
            http2=True,
            headers={"X-Internal-Service": "pharma-mcp", "X-API-Key": _API_KEY},
        )
    return _http


def _err(e: Exception) -> str:
    """Consistent actionable error formatting for all tools."""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 404:
            return "Error: Resource not found. Check the ID."
        if code == 429:
            return "Error: Rate limit exceeded. Retry after 60 seconds."
        if code == 422:
            try:
                body = e.response.json()
                return f"Error: Validation failed — {body.get('detail', 'check your inputs')}"
            except Exception:
                pass
        return f"Error: API returned HTTP {code}"
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. The analysis may still be running — use pharma_get_session to check status."
    return f"Error: {type(e).__name__} — {e}"


# ── Lifespan ─────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(server: FastMCP):
    """Initialize shared resources once for the server's lifetime."""
    logger.info("Pharma MCP server starting", extra={"planner_url": PLANNER_URL})
    try:
        yield {"http": _get_http()}
    finally:
        if _http and not _http.is_closed:
            await _http.aclose()
        logger.info("Pharma MCP server shutdown")


# ── FastMCP server init ───────────────────────────────────
mcp = FastMCP("pharma_ai_mcp", lifespan=_lifespan)


# ── Input models ─────────────────────────────────────────

class CreateSessionInput(BaseModel):
    """Input for creating a new drug analysis session."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    drug_name: str = Field(..., min_length=2, max_length=200,
                           description="Drug INN or brand name, e.g. 'Semaglutide'")
    target_market: str = Field(default="US",
                               description="Target launch market: 'US', 'EU', 'IN', 'JP'")
    query: str = Field(default="",
                       description="Natural language analysis question, e.g. 'What is the competitive landscape?'")
    user_id: str = Field(default="mcp_user",
                         description="User identifier for rate limiting and audit")
    priority: int = Field(default=5, ge=1, le=10,
                          description="Priority 1=urgent 10=background")

    @field_validator("target_market")
    @classmethod
    def validate_market(cls, v: str) -> str:
        allowed = {"US", "EU", "IN", "JP", "UK", "CA", "AU"}
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"target_market must be one of: {', '.join(sorted(allowed))}")
        return v


class GetSessionInput(BaseModel):
    """Input for retrieving a session."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    session_id: str = Field(..., min_length=36, max_length=36,
                            description="Session UUID (36-char format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)")
    user_id: str = Field(default="mcp_user", description="User identifier for access-scoped session reads")


class ListSessionsInput(BaseModel):
    """Input for listing sessions."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    drug_name: str = Field(default="", description="Filter by drug name (partial match)")
    user_id: str = Field(default="", description="Filter by user ID")
    status: str = Field(default="", description="Filter by status: PENDING, RUNNING, COMPLETED, FAILED")
    limit: int = Field(default=10, ge=1, le=50, description="Max results to return")
    offset: int = Field(default=0, ge=0, description="Pagination offset")


class SearchFDAInput(BaseModel):
    """Input for FDA drug database search."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    drug_name: str = Field(..., min_length=2, max_length=200,
                           description="Drug name to search in FDA Orange/Purple Book")
    search_type: str = Field(default="brand_or_generic",
                             description="'brand_or_generic', 'nda_anda', 'approval_date'")
    limit: int = Field(default=10, ge=1, le=50)


class SearchClinicalTrialsInput(BaseModel):
    """Input for ClinicalTrials.gov search."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    drug_name: str = Field(..., min_length=2, max_length=200,
                           description="Drug or intervention name")
    phase: str = Field(default="", description="Trial phase: 'Phase 1', 'Phase 2', 'Phase 3', 'Phase 4'")
    status: str = Field(default="RECRUITING",
                        description="Trial status: 'RECRUITING', 'COMPLETED', 'ACTIVE_NOT_RECRUITING'")
    limit: int = Field(default=10, ge=1, le=50)


class GetReportInput(BaseModel):
    """Input for retrieving a generated report."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    session_id: str = Field(..., min_length=36, max_length=36,
                            description="Session UUID to retrieve report for")
    format: str = Field(default="pdf", description="Report format: 'pdf', 'json', 'summary'")
    user_id: str = Field(default="mcp_user", description="User identifier for access-scoped report reads")


# ── Tools ─────────────────────────────────────────────────

@mcp.tool(
    name="pharma_create_session",
    annotations={
        "title": "Create Drug Analysis Session",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def pharma_create_session(params: CreateSessionInput, ctx: Context) -> str:
    """
    Start a new drug market analysis session on the Pharma AI platform.

    Triggers a full multi-agent analysis pipeline across 6 pillars:
    Legal (FDA), Clinical (trials), Commercial (market), Social (sentiment),
    Knowledge (patents), and News (real-time).

    The session runs asynchronously. Use pharma_get_session to poll status.
    Typical completion time: 30-120 seconds depending on data availability.

    Args:
        params (CreateSessionInput): Session parameters including drug name, market, query.

    Returns:
        str: JSON with session_id, status, and estimated_completion_seconds.
             session_id is a UUID to use with other tools.

    Error responses:
        "Error: Rate limit exceeded" — too many sessions from this user_id
        "Error: Validation failed" — invalid drug_name or target_market
    """
    await ctx.report_progress(0.1, f"Creating session for {params.drug_name}...")
    try:
        http = _get_http()
        resp = await http.post(
            "/api/v1/sessions",
            json={
                "drug_name": params.drug_name,
                "target_market": params.target_market,
                "query": params.query or f"Full market analysis for {params.drug_name} in {params.target_market}",
                "user_id": params.user_id,
                "priority": params.priority,
            },
            headers={"X-User-Id": params.user_id},
        )
        resp.raise_for_status()
        data = resp.json()
        await ctx.report_progress(1.0, "Session created")
        return json.dumps({
            "session_id": data.get("session_id"),
            "status": data.get("status", "PENDING"),
            "drug_name": params.drug_name,
            "target_market": params.target_market,
            "estimated_completion_seconds": 60,
            "poll_with": "pharma_get_session",
            "stream_events_at": f"{PLANNER_WS_URL}/ws/sessions/{data.get('session_id')}",
        }, indent=2)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="pharma_get_session",
    annotations={
        "title": "Get Session Status & Results",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def pharma_get_session(params: GetSessionInput, ctx: Context) -> str:
    """
    Get the current status and results of a drug analysis session.

    Returns full session data including agent results, decision, grounding
    score, and citations when the session is COMPLETED.

    Args:
        params (GetSessionInput): Session UUID to retrieve.

    Returns:
        str: JSON session document with fields:
            - session_id (str): UUID
            - status (str): PENDING | RUNNING | COMPLETED | FAILED
            - decision (str): GO | NO_GO | CONDITIONAL (when COMPLETED)
            - grounding_score (float): 0.0-1.0 evidence quality
            - agent_results (list): Per-pillar retrieval results
            - report_url (str): PDF report URL (when COMPLETED)

    Error responses:
        "Error: Resource not found" — invalid session_id
    """
    try:
        http = _get_http()
        resp = await http.get(
            f"/api/v1/sessions/{params.session_id}",
            headers={"X-User-Id": params.user_id},
        )
        resp.raise_for_status()
        data = resp.json()

        # Surface key fields for LLM readability
        status = data.get("status", "UNKNOWN")
        summary = {
            "session_id": params.session_id,
            "status": status,
            "drug_name": data.get("drug_name"),
            "target_market": data.get("target_market"),
            "created_at": data.get("created_at"),
        }
        if status == "COMPLETED":
            summary.update({
                "decision": data.get("decision"),
                "grounding_score": data.get("grounding_score"),
                "report_url": data.get("report_url"),
                "pillar_summaries": {
                    r.get("pillar"): r.get("confidence")
                    for r in data.get("agent_results", [])
                },
            })
        elif status in {"PLANNING", "RETRIEVING", "VALIDATING", "SYNTHESIZING"}:
            summary["completed_pillars"] = [
                r.get("pillar") for r in data.get("agent_results", [])
            ]

        return json.dumps(summary, indent=2, default=str)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="pharma_list_sessions",
    annotations={
        "title": "List Drug Analysis Sessions",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def pharma_list_sessions(params: ListSessionsInput) -> str:
    """
    List drug analysis sessions with optional filters.

    Use to find past sessions for a drug, check running sessions,
    or audit sessions by user.

    Args:
        params (ListSessionsInput): Filters: drug_name, user_id, status, limit, offset.

    Returns:
        str: JSON with total count, sessions list (id, drug, status, created_at, decision).
    """
    try:
        http = _get_http()
        query_params: dict[str, Any] = {"limit": params.limit, "offset": params.offset}
        if params.drug_name:
            query_params["drug_name"] = params.drug_name
        if params.user_id:
            query_params["user_id"] = params.user_id
        if params.status:
            query_params["status"] = params.status

        resp = await http.get(
            "/api/v1/sessions",
            params=query_params,
            headers={"X-User-Id": params.user_id},
        )
        resp.raise_for_status()
        data = resp.json()

        sessions = data.get("sessions", [])
        return json.dumps({
            "total": data.get("total", len(sessions)),
            "offset": params.offset,
            "count": len(sessions),
            "has_more": data.get("total", 0) > params.offset + len(sessions),
            "sessions": [
                {
                    "session_id": s.get("session_id"),
                    "drug_name": s.get("drug_name"),
                    "status": s.get("status"),
                    "decision": s.get("decision"),
                    "created_at": s.get("created_at"),
                }
                for s in sessions
            ],
        }, indent=2)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="pharma_get_agent_status",
    annotations={
        "title": "Get Live Agent Registry Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def pharma_get_agent_status() -> str:
    """
    Get a snapshot of all active agents in the registry.

    Shows which agents are alive (heartbeat within last 60s),
    their capabilities, endpoints, and circuit breaker states.
    Use to diagnose pipeline issues or understand system capacity.

    Returns:
        str: JSON with active_count and agents list:
            - agent_id, name, agent_type, capabilities (list)
            - endpoint (str), status ('healthy'|'degraded')
    """
    try:
        from src.shared.infra.redis_client import RedisClient
        redis = RedisClient()
        agents = redis.get_active_agents()

        return json.dumps({
            "active_count": len(agents),
            "agents": [
                {
                    "agent_id": a.get("agent_id"),
                    "name": a.get("name"),
                    "agent_type": a.get("agent_type"),
                    "capabilities": a.get("capabilities", []),
                    "endpoint": a.get("endpoint"),
                    "status": "healthy",
                }
                for a in agents
            ],
        }, indent=2)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="pharma_search_fda",
    annotations={
        "title": "Search FDA Drug Database",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pharma_search_fda(params: SearchFDAInput, ctx: Context) -> str:
    """
    Query the FDA OpenFDA API for drug approvals, NDAs, ANDAs, and Orange Book entries.

    Use to check if a drug is approved, find the approval date,
    look up the applicant, or find generic competition.

    Args:
        params (SearchFDAInput): drug_name, search_type, limit.

    Returns:
        str: JSON with fda_results list containing:
            - brand_name, generic_name, applicant
            - approval_date, application_number (NDA/ANDA)
            - route, dosage_form, marketing_status
    """
    await ctx.report_progress(0.2, f"Searching FDA for {params.drug_name}...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://api.fda.gov/drug/drugsfda.json",
                params={
                    "search": f"openfda.brand_name:\"{params.drug_name}\"+openfda.generic_name:\"{params.drug_name}\"",
                    "limit": params.limit,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for r in data.get("results", []):
            openfda = r.get("openfda", {})
            for product in r.get("products", [])[:3]:
                results.append({
                    "brand_name": openfda.get("brand_name", [""])[0] if openfda.get("brand_name") else "",
                    "generic_name": openfda.get("generic_name", [""])[0] if openfda.get("generic_name") else "",
                    "applicant": r.get("sponsor_name", ""),
                    "application_number": r.get("application_number", ""),
                    "approval_date": next(
                        (h.get("action_date") for h in r.get("submissions", [])
                         if h.get("submission_type") == "ORIG"), ""
                    ),
                    "dosage_form": product.get("dosage_form", ""),
                    "route": product.get("route", ""),
                    "marketing_status": product.get("marketing_status", ""),
                })

        await ctx.report_progress(1.0, f"Found {len(results)} FDA records")
        return json.dumps({
            "query": params.drug_name,
            "total_found": data.get("meta", {}).get("results", {}).get("total", len(results)),
            "fda_results": results,
            "source": "FDA OpenFDA API",
        }, indent=2)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="pharma_search_clinical_trials",
    annotations={
        "title": "Search ClinicalTrials.gov",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pharma_search_clinical_trials(params: SearchClinicalTrialsInput, ctx: Context) -> str:
    """
    Search ClinicalTrials.gov for active and completed trials for a drug.

    Use to assess clinical pipeline strength, find Phase 3 readouts,
    and understand patient enrollment activity.

    Args:
        params (SearchClinicalTrialsInput): drug_name, phase, status, limit.

    Returns:
        str: JSON with trials list containing:
            - nct_id, title, phase, status
            - enrollment (int), start_date, completion_date
            - conditions (list), sponsor, results_available (bool)
    """
    await ctx.report_progress(0.2, f"Searching ClinicalTrials for {params.drug_name}...")
    try:
        query_filter = f"AREA[InterventionName]{params.drug_name}"
        if params.phase:
            query_filter += f" AND AREA[Phase]{params.phase}"
        if params.status:
            query_filter += f" AND AREA[OverallStatus]{params.status}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://clinicaltrials.gov/api/v2/studies",
                params={
                    "query.cond": params.drug_name,
                    "query.intr": params.drug_name,
                    "filter.overallStatus": params.status or "RECRUITING",
                    "pageSize": params.limit,
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        trials = []
        for study in data.get("studies", []):
            proto = study.get("protocolSection", {})
            id_mod = proto.get("identificationModule", {})
            status_mod = proto.get("statusModule", {})
            design_mod = proto.get("designModule", {})
            enroll = design_mod.get("enrollmentInfo", {})
            sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
            cond_mod = proto.get("conditionsModule", {})

            trials.append({
                "nct_id": id_mod.get("nctId", ""),
                "title": id_mod.get("briefTitle", "")[:120],
                "status": status_mod.get("overallStatus", ""),
                "phase": design_mod.get("phases", []),
                "enrollment": enroll.get("count", 0),
                "start_date": status_mod.get("startDateStruct", {}).get("date", ""),
                "completion_date": status_mod.get("completionDateStruct", {}).get("date", ""),
                "conditions": cond_mod.get("conditions", [])[:3],
                "sponsor": sponsor_mod.get("leadSponsor", {}).get("name", ""),
                "results_available": bool(study.get("hasResults")),
            })

        await ctx.report_progress(1.0, f"Found {len(trials)} trials")
        return json.dumps({
            "query": params.drug_name,
            "filter_status": params.status,
            "filter_phase": params.phase,
            "trial_count": len(trials),
            "trials": trials,
            "source": "ClinicalTrials.gov API v2",
        }, indent=2)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="pharma_get_report",
    annotations={
        "title": "Get Generated Analysis Report",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def pharma_get_report(params: GetReportInput) -> str:
    """
    Retrieve the generated report for a completed session.

    Returns the download URL for the PDF report, or inline JSON/summary
    depending on the format requested.

    Args:
        params (GetReportInput): session_id and format ('pdf', 'json', 'summary').

    Returns:
        str: JSON with report_url (for pdf) or inline report_data (for json/summary).

    Error responses:
        "Error: Resource not found" — no report yet (session may not be COMPLETED)
    """
    try:
        http = _get_http()
        resp = await http.get(
            f"/api/v1/sessions/{params.session_id}/report",
            params={"format": params.format},
            headers={"X-User-Id": params.user_id},
        )
        resp.raise_for_status()
        data = resp.json()

        if params.format == "pdf":
            return json.dumps({
                "session_id": params.session_id,
                "report_url": data.get("report_url"),
                "generated_at": data.get("generated_at"),
                "file_size_kb": data.get("file_size_kb"),
            }, indent=2)
        return json.dumps(data, indent=2, default=str)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="pharma_list_capabilities",
    annotations={
        "title": "List All A2A Capability Contracts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def pharma_list_capabilities() -> str:
    """
    List all registered A2A capability contracts in the platform.

    Returns the full capability catalogue: what each agent can do,
    its SLA tier, input/output schemas, and endpoint for direct invocation.
    Use to understand which capabilities are available for orchestration.

    Returns:
        str: JSON with capability_count and contracts list:
            - capability_id, capability_name, category
            - sla_tier, max_latency_ms, supports_streaming
            - invoke_endpoint, input_fields (list), output_fields (list)
    """
    from src.shared.a2a.capability_contract import list_contracts
    contracts = list_contracts()
    return json.dumps({
        "capability_count": len(contracts),
        "contracts": [
            {
                "capability_id": c["capability_id"],
                "capability_name": c["capability_name"],
                "category": c["category"],
                "sla_tier": c["sla_tier"],
                "max_latency_ms": c["max_latency_ms"],
                "supports_streaming": c["supports_streaming"],
                "invoke_endpoint": c["invoke_endpoint"],
                "input_fields": [f["name"] for f in c.get("input_schema", {}).get("fields", [])],
                "output_fields": [f["name"] for f in c.get("output_schema", {}).get("fields", [])],
            }
            for c in contracts
        ],
    }, indent=2)


# ── Resources ─────────────────────────────────────────────

@mcp.resource("pharma://sessions/{session_id}")
async def session_resource(session_id: str) -> str:
    """
    Live session document as an MCP resource.

    Access pattern: pharma://sessions/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    Returns the raw session JSON from the Planner API.
    Useful for agents that need rich session context without calling a tool.
    """
    try:
        http = _get_http()
        resp = await http.get(f"/api/v1/sessions/{session_id}")
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.resource("pharma://agents/active")
async def active_agents_resource() -> str:
    """
    Live snapshot of the active agent registry.

    Returns all agents with active heartbeats (< 60s old).
    More efficient than calling pharma_get_agent_status as a tool
    when the caller just needs the raw data for context.
    """
    try:
        from src.shared.infra.redis_client import RedisClient
        redis = RedisClient()
        agents = redis.get_active_agents()
        return json.dumps({"active_count": len(agents), "agents": agents}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Entry points ──────────────────────────────────────────

if __name__ == "__main__":
    import sys
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if transport == "http":
        mcp.run(transport="streamable-http", host="0.0.0.0", port=8010)
    else:
        mcp.run()  # stdio for local Claude Desktop
