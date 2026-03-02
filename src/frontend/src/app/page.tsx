'use client';

import { useState, useEffect, useCallback } from 'react';

/* ── Types ──────────────────────────────────────────────── */

interface TaskNode {
  task_id: string;
  pillar: string;
  description: string;
  status: string;
}

interface ConflictDetail {
  conflict_type: string;
  severity: string;
  description: string;
  recommendation: string;
}

interface SessionResponse {
  session_id: string;
  status: string;
  query: string;
  task_graph: TaskNode[];
  agent_results: Record<string, unknown>[];
  validation: {
    is_valid: boolean;
    grounding_score: number;
    conflicts: ConflictDetail[];
  } | null;
  decision: string | null;
  decision_rationale: string | null;
  report_url: string | null;
  created_at: string;
  updated_at: string;
}

/* ── API ────────────────────────────────────────────────── */

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

async function createSession(query: string): Promise<{ session_id: string; tasks: TaskNode[] }> {
  const res = await fetch(`${API_URL}/api/v1/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, user_id: 'demo-user' }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

async function getSession(sessionId: string): Promise<SessionResponse> {
  const res = await fetch(`${API_URL}/api/v1/sessions/${sessionId}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

/* ── Pillar Config ──────────────────────────────────────── */

const PILLAR_CONFIG: Record<string, { icon: string; className: string; label: string }> = {
  LEGAL: { icon: '⚖️', className: 'agent-card__pillar--legal', label: 'Legal' },
  CLINICAL: { icon: '🧪', className: 'agent-card__pillar--clinical', label: 'Clinical' },
  COMMERCIAL: { icon: '📊', className: 'agent-card__pillar--commercial', label: 'Commercial' },
  SOCIAL: { icon: '🛡️', className: 'agent-card__pillar--social', label: 'Social' },
  KNOWLEDGE: { icon: '📚', className: 'agent-card__pillar--knowledge', label: 'Knowledge' },
};

const STATUS_CONFIG: Record<string, { dot: string; label: string }> = {
  QUEUED: { dot: 'status-dot--queued', label: 'Queued' },
  RUNNING: { dot: 'status-dot--running', label: 'Running' },
  COMPLETED: { dot: 'status-dot--completed', label: 'Completed' },
  FAILED: { dot: 'status-dot--failed', label: 'Failed' },
  RETRYING: { dot: 'status-dot--running', label: 'Retrying' },
  DLQ: { dot: 'status-dot--failed', label: 'Dead Letter' },
};

/* ── Suggestion Chips ───────────────────────────────────── */

const SUGGESTIONS = [
  'Assess 2027 generic launch for Keytruda in India',
  'Should we pursue a biosimilar for Humira in the EU?',
  'Evaluate the oncology patent cliff impact for 2026-2030',
  'Market entry analysis for generic Eliquis in the US',
];

/* ── Loading Skeleton Component ─────────────────────────── */

function AgentCardSkeleton() {
  return (
    <div className="glass-card agent-card" style={{ minHeight: '140px' }}>
      <div className="agent-card__header">
        <div className="skeleton skeleton-text--badge" />
        <div className="skeleton" style={{ height: '14px', width: '60px' }} />
      </div>
      <div className="skeleton skeleton-text" />
      <div className="skeleton skeleton-text skeleton-text--short" />
      <div className="agent-card__meta" style={{ marginTop: 'auto' }}>
        <div className="skeleton" style={{ height: '10px', width: '80px' }} />
        <div className="skeleton" style={{ height: '10px', width: '50px' }} />
      </div>
    </div>
  );
}

/* ── Animated Counter Hook ──────────────────────────────── */

function useAnimatedCounter(target: number, duration: number = 600): number {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (target <= 0) return;
    const start = performance.now();
    const animate = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Math.round(target * eased));
      if (progress < 1) requestAnimationFrame(animate);
    };
    requestAnimationFrame(animate);
  }, [target, duration]);
  return value;
}

/* ── Page Component ─────────────────────────────────────── */

export default function Dashboard() {
  const [query, setQuery] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);

  const groundingScoreAnimated = useAnimatedCounter(
    session?.validation ? Math.round(session.validation.grounding_score * 100) : 0
  );

  /* ── Submit Query ───────────────────────────────────── */

  const handleSubmit = useCallback(async () => {
    if (!query.trim() || loading) return;

    setLoading(true);
    setError(null);
    setSession(null);

    try {
      const result = await createSession(query);
      setSessionId(result.session_id);
      setPolling(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create session');
    } finally {
      setLoading(false);
    }
  }, [query, loading]);

  /* ── Keyboard Shortcut (Ctrl+Enter / Cmd+Enter) ───── */

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSubmit();
    } else if (e.key === 'Enter') {
      handleSubmit();
    }
  }, [handleSubmit]);

  /* ── Poll for Updates ───────────────────────────────── */

  useEffect(() => {
    if (!polling || !sessionId) return;

    const interval = setInterval(async () => {
      try {
        const data = await getSession(sessionId);
        setSession(data);
        if (['COMPLETED', 'FAILED'].includes(data.status)) {
          setPolling(false);
        }
      } catch {
        // Silently retry on poll failure
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [polling, sessionId]);

  /* ── Render ─────────────────────────────────────────── */

  const progress = session
    ? (session.task_graph.filter(t => t.status === 'COMPLETED').length / Math.max(session.task_graph.length, 1)) * 100
    : 0;

  return (
    <div>
      {/* Hero Section */}
      <section style={{ textAlign: 'center', margin: '3rem 0 2rem' }}>
        <h1 style={{
          fontSize: '2.5rem',
          fontWeight: 900,
          background: 'var(--gradient-primary)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          backgroundClip: 'text',
          marginBottom: '0.5rem',
        }}>
          Strategic Intelligence Engine
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '1.0625rem', maxWidth: '600px', margin: '0 auto' }}>
          Deploy an agent swarm for real-time pharmaceutical market-entry analysis.
          100% citation-grounded. Zero hallucinations.
        </p>
      </section>

      {/* Query Input */}
      <section className="query-section">
        <div className="query-input-wrapper">
          <input
            type="text"
            className="query-input"
            placeholder='Enter your strategic query... (e.g., "Should we launch a generic for Keytruda in India by 2027?")'
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
            aria-label="Strategic query input"
          />
          <button
            className="query-submit-btn"
            onClick={handleSubmit}
            disabled={loading || !query.trim()}
            aria-label="Submit strategic query"
          >
            {loading ? '⏳ Deploying...' : '🚀 Analyze'}
          </button>
        </div>

        {/* Suggestion Chips */}
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '1rem' }}>
          {SUGGESTIONS.map((s, i) => (
            <button
              key={i}
              onClick={() => setQuery(s)}
              aria-label={`Use suggestion: ${s}`}
              style={{
                padding: '0.375rem 0.875rem',
                background: 'var(--bg-glass)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-secondary)',
                fontSize: '0.75rem',
                cursor: 'pointer',
                fontFamily: 'var(--font-sans)',
                transition: 'all var(--transition-fast)',
              }}
              onMouseEnter={(e) => {
                (e.target as HTMLButtonElement).style.borderColor = 'var(--accent-indigo)';
                (e.target as HTMLButtonElement).style.color = 'var(--accent-indigo)';
              }}
              onMouseLeave={(e) => {
                (e.target as HTMLButtonElement).style.borderColor = 'var(--border-subtle)';
                (e.target as HTMLButtonElement).style.color = 'var(--text-secondary)';
              }}
            >
              {s}
            </button>
          ))}
        </div>

        <p style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
          💡 Press <kbd style={{ padding: '1px 4px', background: 'var(--bg-glass)', borderRadius: '3px', fontFamily: 'var(--font-mono)', fontSize: '0.625rem' }}>Ctrl</kbd>+<kbd style={{ padding: '1px 4px', background: 'var(--bg-glass)', borderRadius: '3px', fontFamily: 'var(--font-mono)', fontSize: '0.625rem' }}>Enter</kbd> to submit
        </p>
      </section>

      {/* Error with Retry */}
      {error && (
        <div style={{
          padding: '1rem 1.5rem',
          background: 'rgba(239, 68, 68, 0.08)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          borderRadius: 'var(--radius-md)',
          color: 'var(--accent-red)',
          margin: '1rem 0',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <span>❌ {error}</span>
          <button
            onClick={handleSubmit}
            style={{
              padding: '0.375rem 0.875rem',
              background: 'rgba(239, 68, 68, 0.15)',
              border: '1px solid rgba(239, 68, 68, 0.4)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--accent-red)',
              fontSize: '0.8125rem',
              fontWeight: 600,
              cursor: 'pointer',
              fontFamily: 'var(--font-sans)',
            }}
          >
            🔄 Retry
          </button>
        </div>
      )}

      {/* Loading Skeletons (before first poll response) */}
      {loading && !session && (
        <div>
          <div style={{ margin: '2rem 0 1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
              <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>Deploying Agent Swarm...</span>
            </div>
            <div className="progress-bar"><div className="progress-bar__fill" style={{ width: '10%' }} /></div>
          </div>
          <div className="agents-grid">
            {[1, 2, 3, 4, 5].map(i => <AgentCardSkeleton key={i} />)}
          </div>
        </div>
      )}

      {/* Session Progress */}
      {session && (
        <>
          {/* Progress Bar */}
          <div style={{ margin: '2rem 0 1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
              <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>
                Agent Swarm Progress
              </span>
              <span style={{ fontSize: '0.875rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                {Math.round(progress)}%
              </span>
            </div>
            <div className="progress-bar">
              <div className="progress-bar__fill" style={{ width: `${progress}%` }} />
            </div>
          </div>

          {/* Agent Status Grid */}
          <div className="agents-grid">
            {session.task_graph.map((task) => {
              const pillar = PILLAR_CONFIG[task.pillar] || { icon: '🔄', className: '', label: task.pillar };
              const status = STATUS_CONFIG[task.status] || { dot: 'status-dot--queued', label: task.status };
              return (
                <div key={task.task_id} className="glass-card agent-card">
                  <div className="agent-card__header">
                    <span className={`agent-card__pillar ${pillar.className}`}>
                      {pillar.icon} {pillar.label}
                    </span>
                    <div className="agent-card__status">
                      <span className={`status-dot ${status.dot}`} />
                      {status.label}
                    </div>
                  </div>
                  <p className="agent-card__description">{task.description}</p>
                  <div className="agent-card__meta">
                    <span>{task.task_id.slice(0, 8)}...</span>
                    <span>{task.status}</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Decision Banner */}
          {session.decision && (
            <div className={`decision-banner decision-banner--${
              session.decision === 'GO' ? 'go' :
              session.decision === 'NO_GO' ? 'no-go' : 'conditional'
            }`}>
              <div className="decision-banner__icon">
                {session.decision === 'GO' ? '✅' :
                 session.decision === 'NO_GO' ? '🚫' : '⚠️'}
              </div>
              <div className="decision-banner__text">
                <div className="decision-banner__title">
                  Decision: {session.decision.replace('_', ' ')}
                </div>
                <div className="decision-banner__rationale">
                  {session.decision_rationale}
                </div>
              </div>
            </div>
          )}

          {/* Conflicts / Strategic Risks */}
          {session.validation?.conflicts && session.validation.conflicts.length > 0 && (
            <div style={{ margin: '2rem 0' }}>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '1rem' }}>
                🔴 Strategic Risks Detected
              </h2>
              {session.validation.conflicts.map((conflict, i) => (
                <div
                  key={i}
                  className={`conflict-card ${conflict.severity === 'CRITICAL' ? 'conflict-card--critical' : ''}`}
                >
                  <div className="conflict-card__severity">
                    {conflict.severity} — {conflict.conflict_type.replace(/_/g, ' ')}
                  </div>
                  <div className="conflict-card__title">{conflict.description}</div>
                  <div className="conflict-card__description">
                    💡 {conflict.recommendation}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Grounding Score (Animated Counter) */}
          {session.validation && (
            <div className="glass-card" style={{ margin: '1rem 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Citation Grounding Score
                </div>
                <div style={{
                  fontSize: '2rem',
                  fontWeight: 800,
                  background: 'var(--gradient-primary)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  backgroundClip: 'text',
                }}>
                  {groundingScoreAnimated}%
                </div>
              </div>
              <div style={{
                padding: '0.5rem 1rem',
                background: session.validation.is_valid ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                border: `1px solid ${session.validation.is_valid ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.875rem',
                fontWeight: 600,
                color: session.validation.is_valid ? 'var(--accent-emerald)' : 'var(--accent-red)',
              }}>
                {session.validation.is_valid ? '✓ Validated' : '✗ Issues Found'}
              </div>
            </div>
          )}
        </>
      )}

      {/* Empty State */}
      {!session && !loading && (
        <div style={{ textAlign: 'center', margin: '4rem 0', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>🧬</div>
          <h3 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
            Ready to Analyze
          </h3>
          <p style={{ fontSize: '0.875rem', maxWidth: '400px', margin: '0 auto' }}>
            Enter a strategic pharma query above to deploy the agent swarm.
            Each agent will independently retrieve, validate, and synthesize intelligence.
          </p>
        </div>
      )}
    </div>
  );
}
