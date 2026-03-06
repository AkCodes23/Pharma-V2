'use client';

import { useEffect, useMemo, useState } from 'react';

import { DistributionMeter, MiniBars, PulseDot, ProgressRing } from '../../components/visuals';
import { ServiceHealth, SessionSummary, getApiUrl, getServiceHealth, listSessions } from '../../lib/demo-api';

function buildServiceBaseUrl(port: string): string {
  return getApiUrl().replace(/:\d+$/, `:${port}`);
}

export default function AdminPage() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [health, setHealth] = useState<Record<string, ServiceHealth | null>>({});
  const [loading, setLoading] = useState(true);
  const [healthLoading, setHealthLoading] = useState(true);

  useEffect(() => {
    let active = true;

    async function loadSessions() {
      setLoading(true);
      try {
        const response = await listSessions(30);
        if (active) {
          setSessions(response.sessions);
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    async function loadHealth() {
      setHealthLoading(true);
      const services = {
        planner: buildServiceBaseUrl('8000'),
        supervisor: buildServiceBaseUrl('8001'),
        executor: buildServiceBaseUrl('8002'),
      };

      const nextHealth: Record<string, ServiceHealth | null> = {};
      await Promise.all(
        Object.entries(services).map(async ([name, url]) => {
          try {
            nextHealth[name] = await getServiceHealth(url);
          } catch {
            nextHealth[name] = null;
          }
        }),
      );

      if (active) {
        setHealth(nextHealth);
        setHealthLoading(false);
      }
    }

    void loadSessions();
    void loadHealth();

    const interval = setInterval(() => {
      void loadHealth();
    }, 30000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  const totals = useMemo(() => {
    const completed = sessions.filter((session) => session.status === 'COMPLETED').length;
    const activeSessions = sessions.filter((session) =>
      ['RETRIEVING', 'VALIDATING', 'SYNTHESIZING'].includes(session.status),
    ).length;
    const withDecision = sessions.filter((session) => Boolean(session.decision)).length;

    return {
      total: sessions.length,
      completed,
      active: activeSessions,
      decisionRate: sessions.length ? Math.round((withDecision / sessions.length) * 100) : 0,
    };
  }, [sessions]);
  const statusDistribution = useMemo(() => {
    const counts = sessions.reduce<Record<string, number>>((accumulator, session) => {
      accumulator[session.status] = (accumulator[session.status] || 0) + 1;
      return accumulator;
    }, {});

    return [
      { label: 'Retrieving', value: counts.RETRIEVING || 0, tone: 'cyan' as const },
      { label: 'Validating', value: counts.VALIDATING || 0, tone: 'gold' as const },
      { label: 'Synthesizing', value: counts.SYNTHESIZING || 0, tone: 'rose' as const },
      { label: 'Completed', value: counts.COMPLETED || 0, tone: 'green' as const },
    ];
  }, [sessions]);
  const recentVelocity = useMemo(
    () =>
      sessions.slice(0, 8).map((session) => {
        if (session.status === 'COMPLETED') {
          return 92;
        }
        if (session.status === 'SYNTHESIZING') {
          return 76;
        }
        if (session.status === 'VALIDATING') {
          return 58;
        }
        if (session.status === 'RETRIEVING') {
          return 42;
        }
        return 24;
      }),
    [sessions],
  );

  return (
    <div className="page-shell">
      <section className="hero-panel hero-panel--compact">
        <div className="hero-panel__content">
          <p className="eyebrow">Operations</p>
          <h1 className="hero-panel__title">A clearer operating picture for the demo stack.</h1>
          <p className="hero-panel__body">
            This page tracks live service availability and the latest user sessions without relying on protected admin-only endpoints.
          </p>
        </div>
      </section>

      <section className="metrics-grid">
        <article className="surface metric-card">
          <span className="metric-card__label">Total sessions</span>
          <strong className="metric-card__value">{totals.total}</strong>
          <p>Recent runs visible to the demo user.</p>
        </article>
        <article className="surface metric-card">
          <span className="metric-card__label">Completed</span>
          <strong className="metric-card__value">{totals.completed}</strong>
          <p>Sessions that produced a synthesized result.</p>
        </article>
        <article className="surface metric-card">
          <span className="metric-card__label">In flight</span>
          <strong className="metric-card__value">{totals.active}</strong>
          <p>Sessions still progressing through retrieval or synthesis.</p>
        </article>
        <article className="surface metric-card">
          <span className="metric-card__label">Decision rate</span>
          <strong className="metric-card__value">{totals.decisionRate}%</strong>
          <p>Runs that reached a recorded outcome.</p>
        </article>
      </section>

      <section className="signal-grid">
        <article className="surface signal-card">
          <div className="signal-card__header">
            <div>
              <p className="eyebrow">Runtime distribution</p>
              <h2>Session state mix</h2>
            </div>
            <span className="tiny-label">Last {sessions.length || 0} sessions</span>
          </div>
          <DistributionMeter items={statusDistribution} />
        </article>

        <article className="surface signal-card">
          <div className="signal-card__header">
            <div>
              <p className="eyebrow">Throughput</p>
              <h2>Recent workflow velocity</h2>
            </div>
            <span className="tiny-label">Most recent runs</span>
          </div>
          <MiniBars values={recentVelocity.length ? recentVelocity : [26, 48, 62, 74, 84]} tone="rose" />
        </article>

        <article className="surface signal-card signal-card--ring">
          <div className="signal-card__header">
            <div>
              <p className="eyebrow">Completion</p>
              <h2>Decision yield</h2>
            </div>
            <span className="tiny-label">Sessions with a conclusion</span>
          </div>
          <ProgressRing
            value={totals.decisionRate}
            tone={totals.decisionRate >= 70 ? 'green' : totals.decisionRate >= 40 ? 'gold' : 'rose'}
            label="yield"
            caption="This is the share of visible sessions that reached a stored decision."
          />
        </article>
      </section>

      <section className="section-heading">
        <div>
          <p className="eyebrow">Service mesh</p>
          <h2>Live health</h2>
        </div>
        <span className="tiny-label">{healthLoading ? 'Refreshing...' : 'Refreshes every 30 seconds'}</span>
      </section>

      <section className="capability-grid">
        {Object.entries(health).map(([name, service]) => (
          <article key={name} className="surface capability-card">
            <p className="eyebrow">{name}</p>
            <h3>{service?.service || 'Unavailable'}</h3>
            <p>{service ? `Reported status: ${service.status}` : 'Service is not responding to health checks.'}</p>
            <PulseDot
              label="health"
              status={service?.status || 'down'}
              tone={service?.status === 'healthy' ? 'green' : 'rose'}
            />
          </article>
        ))}
      </section>

      <section className="section-heading">
        <div>
          <p className="eyebrow">Workflow monitor</p>
          <h2>Latest sessions</h2>
        </div>
      </section>

      <section className="surface table-panel">
        {loading ? (
          <div className="empty-panel">Loading current session history...</div>
        ) : sessions.length === 0 ? (
          <div className="empty-panel">No demo sessions have been created yet.</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Session</th>
                <th>Drug</th>
                <th>Market</th>
                <th>Status</th>
                <th>Decision</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => (
                <tr key={session.session_id}>
                  <td>{session.session_id.slice(0, 12)}</td>
                  <td>{session.drug_name || 'Strategy query'}</td>
                  <td>{session.target_market || 'Global'}</td>
                  <td>
                    <span className={`status-chip status-chip--${session.status.toLowerCase()}`}>
                      {session.status.toLowerCase()}
                    </span>
                  </td>
                  <td>{session.decision || 'Pending'}</td>
                  <td>{new Date(session.updated_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
