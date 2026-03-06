export interface TaskNode {
  task_id: string;
  pillar: string;
  description: string;
  status: string;
}

export interface ConflictDetail {
  conflict_type: string;
  severity: string;
  description: string;
  recommendation: string;
}

export interface SessionValidation {
  is_valid: boolean;
  grounding_score: number;
  conflicts: ConflictDetail[];
}

export interface AgentResult {
  task_id: string;
  session_id: string;
  agent_type: string;
  pillar: string;
  findings: Record<string, unknown>;
  confidence: number;
  execution_time_ms: number;
}

export interface SessionResponse {
  session_id: string;
  status: string;
  query: string;
  task_graph: TaskNode[];
  agent_results: AgentResult[];
  validation: SessionValidation | null;
  decision: string | null;
  decision_rationale: string | null;
  report_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface SessionSummary {
  session_id: string;
  drug_name: string | null;
  target_market: string | null;
  status: string;
  decision: string | null;
  created_at: string;
  updated_at: string;
}

export interface SessionListResponse {
  total: number;
  limit: number;
  offset: number;
  sessions: SessionSummary[];
}

export interface SessionReportSummary {
  session_id: string;
  query: string;
  decision: string | null;
  decision_rationale: string | null;
  grounding_score: number | null;
  conflict_count: number;
  report_url: string | null;
}

export interface ServiceHealth {
  status: string;
  service: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";
const DEMO_USER = "demo-user";

function withDemoHeaders(init?: RequestInit): RequestInit {
  const headers = new Headers(init?.headers);
  headers.set("X-Demo-User", DEMO_USER);

  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  return {
    ...init,
    headers,
    cache: "no-store",
  };
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, withDemoHeaders(init));
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getApiUrl(): string {
  return API_URL;
}

export function getWsUrl(): string {
  return WS_URL;
}

export async function createSession(query: string): Promise<{ session_id: string; tasks: TaskNode[] }> {
  return fetchJson(`${API_URL}/api/v1/sessions`, {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}

export async function getSession(sessionId: string): Promise<SessionResponse> {
  return fetchJson(`${API_URL}/api/v1/sessions/${sessionId}`);
}

export async function listSessions(limit: number = 24): Promise<SessionListResponse> {
  return fetchJson(`${API_URL}/api/v1/sessions?limit=${limit}&offset=0`);
}

export async function getSessionReportSummary(sessionId: string): Promise<SessionReportSummary> {
  return fetchJson(`${API_URL}/api/v1/sessions/${sessionId}/report?format=summary`);
}

export async function getServiceHealth(serviceBaseUrl: string): Promise<ServiceHealth> {
  const response = await fetch(`${serviceBaseUrl}/health`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Health request failed with status ${response.status}`);
  }
  return response.json() as Promise<ServiceHealth>;
}
