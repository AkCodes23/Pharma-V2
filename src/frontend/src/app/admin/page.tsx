'use client';

import { useState, useEffect } from 'react';

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
  cosmos_db: 'healthy' | 'degraded' | 'down';
  service_bus: 'healthy' | 'degraded' | 'down';
  openai: 'healthy' | 'degraded' | 'down';
  search: 'healthy' | 'degraded' | 'down';
}

/* ── Mock Data for MVP ──────────────────────────────────── */

const MOCK_AUDIT_ENTRIES: AuditEntry[] = [
  { id: '1', session_id: 'sess-abc123', user_id: 'dr.aditi', agent_type: 'PLANNER', action: 'QUERY_SUBMITTED', timestamp: '2026-02-26T00:45:00Z', payload_hash: 'a3f2b8c1...' },
  { id: '2', session_id: 'sess-abc123', user_id: 'system', agent_type: 'LEGAL_RETRIEVER', action: 'TASK_STARTED', timestamp: '2026-02-26T00:45:02Z', payload_hash: 'b7d4e9f2...' },
  { id: '3', session_id: 'sess-abc123', user_id: 'system', agent_type: 'CLINICAL_RETRIEVER', action: 'TASK_STARTED', timestamp: '2026-02-26T00:45:02Z', payload_hash: 'c1a3f5d8...' },
  { id: '4', session_id: 'sess-abc123', user_id: 'system', agent_type: 'COMMERCIAL_RETRIEVER', action: 'TASK_STARTED', timestamp: '2026-02-26T00:45:02Z', payload_hash: 'd9b2c7e4...' },
  { id: '5', session_id: 'sess-abc123', user_id: 'system', agent_type: 'SOCIAL_RETRIEVER', action: 'TASK_STARTED', timestamp: '2026-02-26T00:45:02Z', payload_hash: 'e5f1a8b3...' },
  { id: '6', session_id: 'sess-abc123', user_id: 'system', agent_type: 'LEGAL_RETRIEVER', action: 'TASK_COMPLETED', timestamp: '2026-02-26T00:45:18Z', payload_hash: 'f2c4d6e8...' },
  { id: '7', session_id: 'sess-abc123', user_id: 'system', agent_type: 'SUPERVISOR', action: 'VALIDATION_PASSED', timestamp: '2026-02-26T00:45:45Z', payload_hash: 'a1b2c3d4...' },
  { id: '8', session_id: 'sess-abc123', user_id: 'system', agent_type: 'EXECUTOR', action: 'REPORT_GENERATED', timestamp: '2026-02-26T00:46:10Z', payload_hash: 'e5f6a7b8...' },
];

const MOCK_HEALTH: SystemHealth = {
  cosmos_db: 'healthy',
  service_bus: 'healthy',
  openai: 'healthy',
  search: 'healthy',
};

const AGENT_METRICS = [
  { agent: 'Planner', avg_latency_ms: 1200, success_rate: 99.8, total_invocations: 1247 },
  { agent: 'Legal Retriever', avg_latency_ms: 3400, success_rate: 97.2, total_invocations: 1180 },
  { agent: 'Clinical Retriever', avg_latency_ms: 2800, success_rate: 98.5, total_invocations: 1195 },
  { agent: 'Commercial Retriever', avg_latency_ms: 1500, success_rate: 99.1, total_invocations: 1210 },
  { agent: 'Social Retriever', avg_latency_ms: 2100, success_rate: 98.9, total_invocations: 1190 },
  { agent: 'Knowledge Retriever', avg_latency_ms: 800, success_rate: 99.5, total_invocations: 982 },
  { agent: 'Supervisor', avg_latency_ms: 4200, success_rate: 99.9, total_invocations: 1150 },
  { agent: 'Executor', avg_latency_ms: 8500, success_rate: 99.6, total_invocations: 1140 },
];

/* ── Page Component ─────────────────────────────────────── */

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState<'audit' | 'health' | 'metrics'>('audit');
  const [auditFilter, setAuditFilter] = useState('');

  const filteredAudit = MOCK_AUDIT_ENTRIES.filter(e =>
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
          <div style={{ marginBottom: '1rem' }}>
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
          </div>

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
                      {entry.payload_hash}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p style={{ marginTop: '1rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            🔒 Audit entries are immutable. SHA-256 hashes ensure tamper-proof compliance with 21 CFR Part 11.
          </p>
        </div>
      )}

      {/* ── System Health Tab ─────────────────────────── */}
      {activeTab === 'health' && (
        <div>
          <div className="agents-grid">
            {Object.entries(MOCK_HEALTH).map(([service, status]) => (
              <div key={service} className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                <div style={{ fontSize: '1.5rem' }}>{healthStatusIcon(status)}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '0.9375rem', fontWeight: 600, textTransform: 'capitalize' }}>
                    {service.replace('_', ' ')}
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
        </div>
      )}

      {/* ── Agent Metrics Tab ─────────────────────────── */}
      {activeTab === 'metrics' && (
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
              {AGENT_METRICS.map(m => (
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
  );
}
