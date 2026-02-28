'use client';

import { useState, useEffect, useCallback } from 'react';

/* ── Types ──────────────────────────────────────────────── */

interface AuditEntry {
  id: string;
  session_id: string;
  user_id: string;
  agent_type: string;
  action: string;
  timestamp: string;
  payload_hash: string;
}

interface SystemHealth {
  [service: string]: 'healthy' | 'degraded' | 'down';
}

interface AgentMetric {
  agent: string;
  avg_latency_ms: number;
  success_rate: number;
  total_invocations: number;
}

/* ── API Configuration ──────────────────────────────────── */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const HEALTH_ENDPOINTS: Record<string, string> = {
  planner: `${API_BASE}/health`,
  supervisor: `${API_BASE.replace(':8000', ':8001')}/health`,
  executor: `${API_BASE.replace(':8000', ':8002')}/health`,
};

/* ── Page Component ─────────────────────────────────────── */

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState<'audit' | 'health' | 'metrics'>('audit');
  const [auditFilter, setAuditFilter] = useState('');

  // Live state
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([]);
  const [systemHealth, setSystemHealth] = useState<SystemHealth>({});
  const [agentMetrics, setAgentMetrics] = useState<AgentMetric[]>([]);

  const [loadingAudit, setLoadingAudit] = useState(true);
  const [loadingHealth, setLoadingHealth] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch audit trail from API
  const fetchAuditTrail = useCallback(async () => {
    try {
      setLoadingAudit(true);
      const response = await fetch(`${API_BASE}/audit?limit=100`);
      if (!response.ok) throw new Error(`Audit API: ${response.status}`);
      const data = await response.json();
      const entries = data.entries || data || [];
      setAuditEntries(entries.map((e: any, i: number) => ({
        id: e.id || e._id || String(i),
        session_id: e.session_id || '',
        user_id: e.user_id || 'system',
        agent_type: e.agent_type || e.agent_id?.split('-')[0]?.toUpperCase() || '',
        action: e.action || '',
        timestamp: e.timestamp || e.created_at || new Date().toISOString(),
        payload_hash: e.payload_hash || '',
      })));
    } catch (err) {
      console.error('Failed to fetch audit trail:', err);
      setError('Failed to load audit trail');
    } finally {
      setLoadingAudit(false);
    }
  }, []);

  // Fetch system health from service endpoints
  const fetchSystemHealth = useCallback(async () => {
    try {
      setLoadingHealth(true);
      const health: SystemHealth = {};

      const checks = Object.entries(HEALTH_ENDPOINTS).map(async ([service, url]) => {
        try {
          const controller = new AbortController();
          const timeout = setTimeout(() => controller.abort(), 5000);
          const response = await fetch(url, { signal: controller.signal });
          clearTimeout(timeout);
          health[service] = response.ok ? 'healthy' : 'degraded';
        } catch {
          health[service] = 'down';
        }
      });

      await Promise.all(checks);
      setSystemHealth(health);
    } catch (err) {
      console.error('Health check failed:', err);
    } finally {
      setLoadingHealth(false);
    }
  }, []);

  // Fetch agent metrics from API
  const fetchMetrics = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/metrics/agents`);
      if (response.ok) {
        const data = await response.json();
        setAgentMetrics(data.metrics || data || []);
      }
    } catch (err) {
      console.error('Failed to fetch metrics:', err);
    }
  }, []);

  useEffect(() => {
    fetchAuditTrail();
    fetchSystemHealth();
    fetchMetrics();

    // Auto-refresh health every 30s
    const healthInterval = setInterval(fetchSystemHealth, 30_000);
    return () => clearInterval(healthInterval);
  }, [fetchAuditTrail, fetchSystemHealth, fetchMetrics]);

  const filteredAudit = auditEntries.filter(e =>
    !auditFilter || e.agent_type.includes(auditFilter.toUpperCase()) || e.action.includes(auditFilter.toUpperCase())
  );

  const healthStatusColor = (status: string) => {
    if (status === 'healthy') return 'var(--accent-emerald)';
    if (status === 'degraded') return 'var(--accent-amber)';
    return 'var(--accent-red)';
  };

  const healthStatusIcon = (status: string) => {
    if (status === 'healthy') return '✅';
    if (status === 'degraded') return '⚠️';
    return '❌';
  };

  return (
    <div>
      <h1 style={{
        fontSize: '2rem',
        fontWeight: 800,
        background: 'var(--gradient-primary)',
        WebkitBackgroundClip: 'text',
        WebkitTextFillColor: 'transparent',
        backgroundClip: 'text',
        marginBottom: '0.5rem',
      }}>
        Admin Panel
      </h1>
      <p style={{ color: 'var(--text-muted)', marginBottom: '2rem' }}>
        System health, audit trail, and agent performance metrics.
      </p>

      {/* Tab Navigation */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '2rem' }}>
        {(['audit', 'health', 'metrics'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              padding: '0.5rem 1.25rem',
              background: activeTab === tab ? 'var(--accent-indigo)' : 'var(--bg-glass)',
              border: `1px solid ${activeTab === tab ? 'var(--accent-indigo)' : 'var(--border-subtle)'}`,
              borderRadius: 'var(--radius-sm)',
              color: activeTab === tab ? 'white' : 'var(--text-secondary)',
              fontSize: '0.875rem',
              fontWeight: 600,
              cursor: 'pointer',
              fontFamily: 'var(--font-sans)',
              textTransform: 'capitalize',
              transition: 'all var(--transition-fast)',
            }}
          >
            {tab === 'audit' ? '📋 Audit Trail' : tab === 'health' ? '💚 System Health' : '📊 Agent Metrics'}
          </button>
        ))}
      </div>

      {/* ── Audit Trail Tab ───────────────────────────── */}
      {activeTab === 'audit' && (
        <div>
          <div style={{ marginBottom: '1rem', display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <input
              type="text"
              placeholder="Filter by agent type or action..."
              value={auditFilter}
              onChange={e => setAuditFilter(e.target.value)}
              style={{
                width: '100%',
                maxWidth: '400px',
                padding: '0.625rem 1rem',
                background: 'var(--bg-secondary)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-sans)',
                fontSize: '0.875rem',
                outline: 'none',
              }}
            />
            <button
              onClick={fetchAuditTrail}
              style={{
                padding: '0.625rem 1rem',
                background: 'var(--bg-glass)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-secondary)',
                fontSize: '0.875rem',
                cursor: 'pointer',
                fontFamily: 'var(--font-sans)',
                whiteSpace: 'nowrap',
              }}
            >
              🔄 Refresh
            </button>
          </div>

          {loadingAudit ? (
            <div className="glass-card" style={{ textAlign: 'center', padding: '2rem' }}>
              <p style={{ color: 'var(--text-muted)' }}>⏳ Loading audit trail...</p>
            </div>
          ) : error ? (
            <div className="glass-card" style={{ textAlign: 'center', padding: '2rem' }}>
              <p style={{ color: 'var(--accent-red)' }}>{error}</p>
            </div>
          ) : filteredAudit.length === 0 ? (
            <div className="glass-card" style={{ textAlign: 'center', padding: '2rem' }}>
              <p style={{ color: 'var(--text-muted)' }}>No audit entries found.</p>
            </div>
          ) : (
            <div className="glass-card" style={{ overflow: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8125rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <th style={{ textAlign: 'left', padding: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Timestamp</th>
                    <th style={{ textAlign: 'left', padding: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Agent</th>
                    <th style={{ textAlign: 'left', padding: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Action</th>
                    <th style={{ textAlign: 'left', padding: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>User</th>
                    <th style={{ textAlign: 'left', padding: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Session</th>
                    <th style={{ textAlign: 'left', padding: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Hash</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAudit.map(entry => (
                    <tr key={entry.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '0.625rem 0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                        {new Date(entry.timestamp).toLocaleTimeString()}
                      </td>
                      <td style={{ padding: '0.625rem 0.75rem' }}>
                        <span style={{
                          padding: '0.125rem 0.5rem',
                          background: 'var(--bg-glass)',
                          border: '1px solid var(--border-subtle)',
                          borderRadius: '999px',
                          fontSize: '0.6875rem',
                          fontWeight: 600,
                          color: 'var(--accent-indigo)',
                        }}>
                          {entry.agent_type.replace('_', ' ')}
                        </span>
                      </td>
                      <td style={{ padding: '0.625rem 0.75rem', color: 'var(--text-primary)', fontWeight: 500 }}>
                        {entry.action.replace(/_/g, ' ')}
                      </td>
                      <td style={{ padding: '0.625rem 0.75rem', color: 'var(--text-secondary)' }}>{entry.user_id}</td>
                      <td style={{ padding: '0.625rem 0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {entry.session_id.slice(0, 12)}...
                      </td>
                      <td style={{ padding: '0.625rem 0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.6875rem', color: 'var(--accent-purple)' }}>
                        {entry.payload_hash.slice(0, 10)}...
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p style={{ marginTop: '1rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            🔒 Audit entries are immutable. SHA-256 hashes ensure tamper-proof compliance with 21 CFR Part 11.
          </p>
        </div>
      )}

      {/* ── System Health Tab ─────────────────────────── */}
      {activeTab === 'health' && (
        <div>
          {loadingHealth ? (
            <div className="glass-card" style={{ textAlign: 'center', padding: '2rem' }}>
              <p style={{ color: 'var(--text-muted)' }}>⏳ Checking system health...</p>
            </div>
          ) : (
            <>
              <div className="agents-grid">
                {Object.entries(systemHealth).map(([service, status]) => (
                  <div key={service} className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    <div style={{ fontSize: '1.5rem' }}>{healthStatusIcon(status)}</div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '0.9375rem', fontWeight: 600, textTransform: 'capitalize' }}>
                        {service.replace(/_/g, ' ')}
                      </div>
                      <div style={{
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: healthStatusColor(status),
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                      }}>
                        {status}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <p style={{ marginTop: '1rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                ♻️ Auto-refreshing every 30 seconds
              </p>
            </>
          )}
        </div>
      )}

      {/* ── Agent Metrics Tab ─────────────────────────── */}
      {activeTab === 'metrics' && (
        <div>
          {agentMetrics.length === 0 ? (
            <div className="glass-card" style={{ textAlign: 'center', padding: '2rem' }}>
              <p style={{ color: 'var(--text-muted)' }}>📊 No agent metrics available yet.</p>
            </div>
          ) : (
            <div className="glass-card" style={{ overflow: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8125rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <th style={{ textAlign: 'left', padding: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase' }}>Agent</th>
                    <th style={{ textAlign: 'right', padding: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase' }}>Avg Latency</th>
                    <th style={{ textAlign: 'right', padding: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase' }}>Success Rate</th>
                    <th style={{ textAlign: 'right', padding: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase' }}>Invocations</th>
                  </tr>
                </thead>
                <tbody>
                  {agentMetrics.map(m => (
                    <tr key={m.agent} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '0.625rem 0.75rem', fontWeight: 600, color: 'var(--text-primary)' }}>{m.agent}</td>
                      <td style={{ padding: '0.625rem 0.75rem', textAlign: 'right', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
                        {m.avg_latency_ms.toLocaleString()}ms
                      </td>
                      <td style={{ padding: '0.625rem 0.75rem', textAlign: 'right' }}>
                        <span style={{
                          color: m.success_rate >= 99 ? 'var(--accent-emerald)' : m.success_rate >= 97 ? 'var(--accent-amber)' : 'var(--accent-red)',
                          fontWeight: 600,
                          fontFamily: 'var(--font-mono)',
                        }}>
                          {m.success_rate}%
                        </span>
                      </td>
                      <td style={{ padding: '0.625rem 0.75rem', textAlign: 'right', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                        {m.total_invocations.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
