'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import { DistributionMeter, MiniBars, ProgressRing } from '../components/visuals';
import { AgentResult, SessionResponse, createSession, getSession, getWsUrl } from '../lib/demo-api';

const SUGGESTIONS = [
  'Assess 2027 generic launch for Keytruda in India',
  'Evaluate a biosimilar entry strategy for Humira in the EU',
  'Analyze the oncology patent cliff impact for 2026 to 2030',
  'Market-entry analysis for a generic Eliquis launch in the US',
];

const SESSION_STAGES = ['PLANNING', 'RETRIEVING', 'VALIDATING', 'SYNTHESIZING', 'COMPLETED'] as const;

const PILLAR_LABELS: Record<string, string> = {
  LEGAL: 'Legal barrier scan',
  CLINICAL: 'Clinical landscape',
  COMMERCIAL: 'Market opportunity',
  SOCIAL: 'Safety signal scan',
  KNOWLEDGE: 'Internal knowledge',
  NEWS: 'Recent developments',
};

function formatDecision(value: string | null): string {
  return value ? value.replace(/_/g, ' ') : 'Pending';
}

function formatStatus(value: string): string {
  return value.toLowerCase().replace(/_/g, ' ');
}

function summarizeFindings(result: AgentResult): string[] {
  return Object.entries(result.findings)
    .slice(0, 3)
    .map(([key, rawValue]) => {
      const value =
        typeof rawValue === 'string'
          ? rawValue
          : Array.isArray(rawValue)
            ? `${rawValue.length} items`
            : typeof rawValue === 'object' && rawValue !== null
              ? `${Object.keys(rawValue).length} fields`
              : String(rawValue);
      return `${key.replace(/_/g, ' ')}: ${value}`;
    });
}

function phaseCopy(session: SessionResponse | null): { title: string; body: string } {
  if (!session) {
    return {
      title: 'Local strategy orchestration',
      body: 'Run planner, retrievers, validation, and synthesis locally with offline fixtures and downloadable report artifacts.',
    };
  }

  if (session.status === 'RETRIEVING') {
    return {
      title: 'Retrievers are assembling evidence',
      body: 'Pillar workers are collecting deterministic findings and citations for the current strategy run.',
    };
  }

  if (session.status === 'VALIDATING') {
    return {
      title: 'Supervisor is checking grounding',
      body: 'Cross-pillar consistency and citation quality are being validated before the final report is generated.',
    };
  }

  if (session.status === 'SYNTHESIZING') {
    return {
      title: 'Executor is packaging the report',
      body: 'Decision logic, rationale, and artifact generation are now in the final synthesis pass.',
    };
  }

  if (session.status === 'COMPLETED') {
    return {
      title: 'Report package is ready',
      body: 'The session has completed and the report artifact is available from local object storage.',
    };
  }

  return {
    title: 'Session requires attention',
    body: 'The run stopped before completion. Inspect the task board and reports library for the latest state.',
  };
}

export default function Dashboard() {
  const [query, setQuery] = useState('');
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeSessionId) {
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        const nextSession = await getSession(activeSessionId);
        if (cancelled) {
          return;
        }
        setSession(nextSession);

        if (nextSession.status === 'COMPLETED' || nextSession.status === 'FAILED') {
          setIsPolling(false);
          return;
        }

        timer = setTimeout(() => {
          void poll();
        }, 2500);
      } catch (requestError) {
        if (cancelled) {
          return;
        }
        setError(requestError instanceof Error ? requestError.message : 'Unable to refresh session state');
        setIsPolling(false);
      }
    };

    setIsPolling(true);
    void poll();

    return () => {
      cancelled = true;
      if (timer) {
        clearTimeout(timer);
      }
    };
  }, [activeSessionId]);

  const completedTasks = useMemo(() => {
    if (!session) {
      return 0;
    }
    return session.task_graph.filter((task) => task.status === 'COMPLETED').length;
  }, [session]);

  const totalTasks = session?.task_graph.length || 0;
  const progress = totalTasks === 0 ? 0 : Math.round((completedTasks / totalTasks) * 100);
  const validationScore = session?.validation ? Math.round(session.validation.grounding_score * 100) : 0;
  const phase = phaseCopy(session);
  const activeStageIndex = session ? SESSION_STAGES.indexOf(session.status as (typeof SESSION_STAGES)[number]) : -1;
  const taskMix = useMemo(() => {
    if (!session) {
      return [
        { label: 'Queued', value: 2, tone: 'gold' as const },
        { label: 'Running', value: 2, tone: 'cyan' as const },
        { label: 'Done', value: 1, tone: 'green' as const },
      ];
    }

    const counts = session.task_graph.reduce(
      (accumulator, task) => {
        if (task.status === 'COMPLETED') {
          accumulator.completed += 1;
        } else if (task.status === 'RUNNING' || task.status === 'RETRIEVING' || task.status === 'VALIDATING') {
          accumulator.running += 1;
        } else {
          accumulator.queued += 1;
        }
        return accumulator;
      },
      { queued: 0, running: 0, completed: 0 },
    );

    return [
      { label: 'Queued', value: counts.queued, tone: 'gold' as const },
      { label: 'Running', value: counts.running, tone: 'cyan' as const },
      { label: 'Done', value: counts.completed, tone: 'green' as const },
    ];
  }, [session]);
  const confidenceBars = useMemo(
    () => (session?.agent_results.length ? session.agent_results.map((result) => Math.round(result.confidence * 100)) : [46, 62, 71, 68, 79, 74]),
    [session],
  );
  const confidenceLabels = useMemo(
    () => (session?.agent_results.length ? session.agent_results.map((result) => result.pillar.slice(0, 3)) : ['LEG', 'CLI', 'COM', 'SOC', 'KNO', 'NEW']),
    [session],
  );

  async function handleSubmit() {
    if (!query.trim() || isSubmitting) {
      return;
    }

    setIsSubmitting(true);
    setError(null);
    setSession(null);

    try {
      const response = await createSession(query.trim());
      setActiveSessionId(response.session_id);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Unable to create session');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="page-shell">
      <section className="hero-panel">
        <div className="hero-panel__content">
          <p className="eyebrow">Standalone demo console</p>
          <h1 className="hero-panel__title">A sharper local front end for the strategy workflow.</h1>
          <p className="hero-panel__body">{phase.body}</p>

          <div className="composer surface">
            <div className="composer__header">
              <div>
                <p className="eyebrow">Launch a session</p>
                <h2>{phase.title}</h2>
              </div>
              <span className={`status-chip status-chip--${session ? session.status.toLowerCase() : 'ready'}`}>
                {session ? formatStatus(session.status) : 'ready'}
              </span>
            </div>

            <textarea
              className="field-textarea"
              value={query}
              placeholder="Describe the strategic question you want the demo stack to analyze."
              onChange={(event) => setQuery(event.target.value)}
            />

            <div className="composer__actions">
              <button type="button" className="button button--primary" onClick={() => void handleSubmit()} disabled={isSubmitting}>
                {isSubmitting ? 'Starting session...' : 'Run analysis'}
              </button>
              <Link className="button button--ghost" href="/reports">
                Open report library
              </Link>
              <span className="tiny-label">WebSocket: {getWsUrl()}</span>
            </div>

            <div className="suggestions-row">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  className="suggestion-chip"
                  onClick={() => setQuery(suggestion)}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>

          {error ? <div className="inline-alert inline-alert--error">{error}</div> : null}
        </div>

        <aside className="hero-panel__aside surface">
          <p className="eyebrow">Local runtime</p>
          <div className="hero-stack">
            <div className="hero-stack__item">
              <span>State</span>
              <strong>PostgreSQL + Redis</strong>
            </div>
            <div className="hero-stack__item">
              <span>Task bus</span>
              <strong>Kafka topics</strong>
            </div>
            <div className="hero-stack__item">
              <span>Artifacts</span>
              <strong>MinIO object store</strong>
            </div>
            <div className="hero-stack__item">
              <span>Reasoning</span>
              <strong>Offline fixtures</strong>
            </div>
          </div>
        </aside>
      </section>

      <section className="metrics-grid">
        <article className="surface metric-card">
          <span className="metric-card__label">Session progress</span>
          <strong className="metric-card__value">{progress}%</strong>
          <div className="progress-track">
            <div className="progress-track__fill" style={{ width: `${progress}%` }} />
          </div>
        </article>
        <article className="surface metric-card">
          <span className="metric-card__label">Completed tasks</span>
          <strong className="metric-card__value">{completedTasks}</strong>
          <p>{totalTasks === 0 ? 'No active session' : `${totalTasks - completedTasks} still running`}</p>
        </article>
        <article className="surface metric-card">
          <span className="metric-card__label">Grounding score</span>
          <strong className="metric-card__value">{session?.validation ? `${validationScore}%` : '--'}</strong>
          <p>{session?.validation?.is_valid ? 'Validation passed' : 'Awaiting validation output'}</p>
        </article>
        <article className="surface metric-card">
          <span className="metric-card__label">Decision</span>
          <strong className="metric-card__value">{formatDecision(session?.decision || null)}</strong>
          <p>{session?.updated_at ? new Date(session.updated_at).toLocaleString() : 'No session activity yet'}</p>
        </article>
      </section>

      <section className="signal-grid">
        <article className="surface signal-card">
          <div className="signal-card__header">
            <div>
              <p className="eyebrow">Execution mix</p>
              <h2>Workflow load</h2>
            </div>
            <span className="tiny-label">{totalTasks || 5} tracked tasks</span>
          </div>
          <DistributionMeter items={taskMix} />
        </article>

        <article className="surface signal-card">
          <div className="signal-card__header">
            <div>
              <p className="eyebrow">Evidence shape</p>
              <h2>Pillar confidence</h2>
            </div>
            <span className="tiny-label">Deterministic output profile</span>
          </div>
          <MiniBars values={confidenceBars} labels={confidenceLabels} tone="cyan" />
        </article>

        <article className="surface signal-card signal-card--ring">
          <div className="signal-card__header">
            <div>
              <p className="eyebrow">Quality signal</p>
              <h2>Grounding posture</h2>
            </div>
            <span className="tiny-label">{session?.validation?.is_valid ? 'Validated' : 'Awaiting review'}</span>
          </div>
          <ProgressRing
            value={session?.validation ? validationScore : 72}
            tone={session?.validation?.is_valid ? 'green' : 'gold'}
            label="grounded"
            caption="Grounding is derived from the supervisor pass before synthesis is finalized."
          />
        </article>
      </section>

      <section className="stage-strip">
        {SESSION_STAGES.map((stage, index) => {
          const normalized = stage.toLowerCase();
          const isComplete = activeStageIndex > index || (!session && stage === 'PLANNING');
          const isActive = activeStageIndex === index || (!session && stage === 'PLANNING');

          return (
            <article
              key={stage}
              className={`surface stage-card ${isActive ? 'stage-card--active' : ''} ${isComplete ? 'stage-card--complete' : ''}`}
            >
              <div className="stage-card__top">
                <span className={`stage-dot stage-dot--${normalized}`} />
                <span className="tiny-label">{String(index + 1).padStart(2, '0')}</span>
              </div>
              <h3>{formatStatus(stage)}</h3>
              <p>
                {stage === 'PLANNING' && 'Parse the strategy query and route work to the right pillars.'}
                {stage === 'RETRIEVING' && 'Run deterministic evidence gathering across the local agent mesh.'}
                {stage === 'VALIDATING' && 'Score grounding and identify cross-pillar conflicts before synthesis.'}
                {stage === 'SYNTHESIZING' && 'Assemble the final recommendation and report artifact package.'}
                {stage === 'COMPLETED' && 'Expose the decision, rationale, and downloadable report output.'}
              </p>
            </article>
          );
        })}
      </section>

      {!session ? (
        <section className="capability-grid">
          <article className="surface capability-card">
            <p className="eyebrow">Planner</p>
            <h3>Structured decomposition</h3>
            <p>Translate one strategic question into deterministic pillar tasks and kick off the local workflow in one action.</p>
          </article>
          <article className="surface capability-card">
            <p className="eyebrow">Retrievers</p>
            <h3>Visible execution board</h3>
            <p>Track each pillar from queue to completion with a board that reads like an operations room instead of a generic form.</p>
          </article>
          <article className="surface capability-card">
            <p className="eyebrow">Supervisor</p>
            <h3>Grounding-first decisions</h3>
            <p>Surface conflicts, grounding quality, and execution state before you ever open the report artifact.</p>
          </article>
          <article className="surface capability-card">
            <p className="eyebrow">Executor</p>
            <h3>Downloadable local reports</h3>
            <p>Publish report artifacts from MinIO with a clean handoff into the reports library and operations pages.</p>
          </article>
        </section>
      ) : (
        <>
          <section className="section-heading">
            <div>
              <p className="eyebrow">Task board</p>
              <h2>Current session</h2>
            </div>
            <div className="section-heading__actions">
              <span className="tiny-label">Session {session.session_id.slice(0, 12)}</span>
              {session.report_url ? (
                <a className="button button--primary" href={session.report_url} target="_blank" rel="noreferrer">
                  Download report
                </a>
              ) : null}
            </div>
          </section>

          <section className="task-grid">
            {session.task_graph.map((task) => (
              <article key={task.task_id} className="surface task-card">
                <div className="task-card__row">
                  <span className={`pillar-badge pillar-badge--${task.pillar.toLowerCase()}`}>
                    {PILLAR_LABELS[task.pillar] || task.pillar}
                  </span>
                  <span className={`status-chip status-chip--${task.status.toLowerCase()}`}>
                    {formatStatus(task.status)}
                  </span>
                </div>
                <h3>{task.description}</h3>
                <div className="task-card__footer">
                  <span>{task.task_id.slice(0, 10)}</span>
                  <span>{task.pillar}</span>
                </div>
              </article>
            ))}
          </section>

          <section className="section-heading">
            <div>
              <p className="eyebrow">Findings snapshot</p>
              <h2>Agent output</h2>
            </div>
            <Link className="button button--ghost" href="/admin">
              Open operations
            </Link>
          </section>

          <section className="results-grid">
            {session.agent_results.length === 0 ? (
              <div className="surface empty-panel">Agent findings will appear here as each retriever completes.</div>
            ) : (
              session.agent_results.map((result) => (
                <article key={`${result.task_id}-${result.pillar}`} className="surface result-card">
                  <div className="task-card__row">
                    <span className={`pillar-badge pillar-badge--${result.pillar.toLowerCase()}`}>
                      {PILLAR_LABELS[result.pillar] || result.pillar}
                    </span>
                    <span className="tiny-label">{Math.round(result.confidence * 100)}% confidence</span>
                  </div>
                  <ul className="detail-list">
                    {summarizeFindings(result).map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </article>
              ))
            )}
          </section>

          {session.decision ? (
            <section className={`surface verdict-panel verdict-panel--${session.decision.toLowerCase().replace(/_/g, '-')}`}>
              <div>
                <p className="eyebrow">Outcome</p>
                <h2>{formatDecision(session.decision)}</h2>
                <p>{session.decision_rationale || 'Decision rationale has not been provided yet.'}</p>
              </div>
              <div className="verdict-panel__actions">
                {session.report_url ? (
                  <a className="button button--primary" href={session.report_url} target="_blank" rel="noreferrer">
                    Open report artifact
                  </a>
                ) : null}
                <Link className="button button--ghost" href="/reports">
                  Review all sessions
                </Link>
              </div>
            </section>
          ) : null}

          {session.validation?.conflicts.length ? (
            <section className="conflict-list">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Strategic risks</p>
                  <h2>Conflict register</h2>
                </div>
              </div>
              {session.validation.conflicts.map((conflict) => (
                <article key={`${conflict.conflict_type}-${conflict.description}`} className="surface conflict-card">
                  <div className="task-card__row">
                    <span className="pill-label">{conflict.conflict_type.replace(/_/g, ' ')}</span>
                    <span className={`status-chip status-chip--${conflict.severity.toLowerCase()}`}>
                      {conflict.severity}
                    </span>
                  </div>
                  <h3>{conflict.description}</h3>
                  <p>{conflict.recommendation}</p>
                </article>
              ))}
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}
