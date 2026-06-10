// Path: src/pages/SessionDetailPage.jsx
// File: SessionDetailPage.jsx
// Created: 2026-06-10
// Purpose: Per-session drill-down at /projects/:pid/sessions/:sid. Renders GET /api/sessions/{id} payload: header (id, status, methods, reasons, headline), open/close datetimes, totals, by_role table, by_ticket table (linked to ticket detail pages), TL/PM/Ad Hoc overhead (always visible on this drill-down, all three null-guarded to 0; ad_hoc_overhead_tokens ships in DWB-353). Polls every 10s while the session is live, freezes when closed. Returns a Session not found view with a back link on 404. Does NOT render captured open_phrase / close_phrase text (privacy: user-typed text is not surfaced).
// Caller: App.jsx (route: /projects/:id/sessions/:sid)
// Callees: react (useState, useEffect, useRef, useCallback), react-router-dom (useParams, Link), store/useStore, api/sessions (getSession), api/client (ApiError), styles/dashboard.css, styles/sessions.css
// Data In: Route params id (project id) and sid (session id), project from store
// Data Out: Default export SessionDetailPage component
// Last Modified: 2026-06-10

import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import { getSession } from '../api/sessions';
import { ApiError } from '../api/client';
import '../styles/dashboard.css';
import '../styles/sessions.css';

const POLL_INTERVAL_MS = 10000;

function formatTokens(n) {
  const v = Number(n) || 0;
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(v);
}

function formatDuration(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m ${String(sec).padStart(2, '0')}s`;
  if (m > 0) return `${m}m ${String(sec).padStart(2, '0')}s`;
  return `${sec}s`;
}

function parseUtc(iso) {
  if (!iso) return null;
  const ts = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z';
  const d = new Date(ts);
  return isNaN(d.getTime()) ? null : d;
}

function formatFullDateTime(iso) {
  const d = parseUtc(iso);
  if (!d) return '-';
  const date = d.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' });
  return `${date} ${time}`;
}

function SessionDetailPage() {
  const { id: projectId, sid } = useParams();
  const project = useStore((s) => s.getProject(projectId));
  const [detail, setDetail] = useState(null);
  const [status, setStatus] = useState('loading'); // 'loading' | 'ok' | 'not_found' | 'error'
  const [errMsg, setErrMsg] = useState('');
  const pollRef = useRef(null);
  const cancelledRef = useRef(false);

  const load = useCallback(async () => {
    try {
      const d = await getSession(sid);
      if (cancelledRef.current) return d;
      if (d) {
        setDetail(d);
        setStatus('ok');
      } else {
        setStatus('not_found');
      }
      return d;
    } catch (err) {
      if (cancelledRef.current) return null;
      if (err instanceof ApiError && err.status === 404) {
        setStatus('not_found');
      } else {
        setStatus('error');
        setErrMsg(err?.message || 'failed to load session');
      }
      return null;
    }
  }, [sid]);

  // Initial load.
  useEffect(() => {
    cancelledRef.current = false;
    setStatus('loading');
    setDetail(null);
    load();
    return () => {
      cancelledRef.current = true;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [load]);

  // Polling: only while session is open / live. Freeze on close.
  useEffect(() => {
    if (!detail) return undefined;
    const isOpen = detail.status === 'open' || detail.live === true || detail.closed_at == null;
    if (!isOpen) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return undefined;
    }
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(() => {
      load();
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [detail, load]);

  const backHref = `/projects/${projectId}/sessions`;

  if (status === 'loading') {
    return (
      <div className="dashboard" data-testid="session-detail-page">
        <div className="dashboard__breadcrumb">
          <Link to={backHref}>{'<- back to sessions'}</Link>
        </div>
        <div className="session-panel__empty">Loading session #{sid}...</div>
      </div>
    );
  }

  if (status === 'not_found') {
    return (
      <div className="dashboard" data-testid="session-detail-page">
        <div className="dashboard__breadcrumb">
          <Link to={backHref}>{'<- back to sessions'}</Link>
        </div>
        <div className="session-panel__empty" data-testid="session-not-found">
          Session #{sid} not found.
        </div>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div className="dashboard" data-testid="session-detail-page">
        <div className="dashboard__breadcrumb">
          <Link to={backHref}>{'<- back to sessions'}</Link>
        </div>
        <div className="session-panel__empty">Error loading session: {errMsg}</div>
      </div>
    );
  }

  const isOpen = detail.status === 'open' || detail.live === true || detail.closed_at == null;
  const projectLabel = project ? project.prefix : `project ${projectId}`;
  const byRole = Array.isArray(detail.by_role) ? detail.by_role : [];
  const byTicket = Array.isArray(detail.by_ticket) ? detail.by_ticket : [];

  return (
    <div className="dashboard" data-testid="session-detail-page">
      <div className="dashboard__breadcrumb">
        <Link to={`/projects/${projectId}`}>{projectLabel}</Link>
        <span> / </span>
        <Link to={backHref}>sessions</Link>
        <span> / #{detail.id}</span>
      </div>

      <h1 className="dashboard__title">DWB Session #{detail.id}</h1>

      <div className="session-detail__meta">
        <span
          className={`session-panel__dot${isOpen ? '' : ' session-panel__dot--closed'}`}
          aria-hidden="true"
        />
        <span
          className={`session-panel__state session-panel__state--${isOpen ? 'open' : 'closed'}`}
        >
          {isOpen ? 'OPEN' : 'CLOSED'}
        </span>
        {detail.open_method && (
          <span className="session-panel__method">open via {detail.open_method}</span>
        )}
        {!isOpen && detail.close_method && (
          <span className="session-panel__method">close via {detail.close_method}</span>
        )}
        {!isOpen && detail.close_reason && (
          <span className="session-panel__method">reason: {detail.close_reason}</span>
        )}
        {detail.headline && (
          <span className="session-panel__headline" data-testid="session-detail-headline">
            {detail.headline}
          </span>
        )}
      </div>

      <div className="session-detail__grid">
        <div className="session-detail__cell">
          <div className="session-panel__stat-label">Opened</div>
          <div className="session-detail__cell-value">{formatFullDateTime(detail.opened_at)}</div>
        </div>
        <div className="session-detail__cell">
          <div className="session-panel__stat-label">Closed</div>
          <div className="session-detail__cell-value">
            {detail.closed_at ? formatFullDateTime(detail.closed_at) : <span className="session-panel__row--empty">still open</span>}
          </div>
        </div>
        <div className="session-detail__cell">
          <div className="session-panel__stat-label">Duration</div>
          <div className="session-detail__cell-value">{formatDuration(detail.total_time_seconds)}</div>
        </div>
        <div className="session-detail__cell">
          <div className="session-panel__stat-label">Total tokens</div>
          <div className="session-detail__cell-value">{formatTokens(detail.total_tokens)}</div>
        </div>
      </div>

      <div className="session-panel__section">
        <div className="session-panel__section-title">By role</div>
        <div className="session-panel__table">
          <div className="session-panel__row session-panel__row-header">
            <span>Agent</span>
            <span>Role</span>
            <span className="session-panel__col-tokens">Tokens</span>
            <span className="session-panel__col-time">Time</span>
          </div>
          {byRole.length === 0 ? (
            <div className="session-panel__row--empty">no role activity recorded</div>
          ) : (
            byRole.map((r) => (
              <div key={`${r.agent_id}-${r.role}`} className="session-panel__row">
                <span className="session-panel__col-name">
                  {r.agent_id ? (
                    <Link to={`/projects/${projectId}/agents/${r.agent_id}`}>{r.agent_name}</Link>
                  ) : (
                    r.agent_name
                  )}
                </span>
                <span className="session-panel__col-role">{r.role}</span>
                <span className="session-panel__col-tokens">{formatTokens(r.tokens)}</span>
                <span className="session-panel__col-time">{formatDuration(r.time_seconds)}</span>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="session-panel__section">
        <div className="session-panel__section-title">By ticket</div>
        <div className="session-panel__table">
          <div className="session-panel__row session-panel__row--ticket session-panel__row-header">
            <span>Key</span>
            <span>Title</span>
            <span className="session-panel__col-tokens">Tokens</span>
            <span className="session-panel__col-time">Time</span>
          </div>
          {byTicket.length === 0 ? (
            <div className="session-panel__row--empty">no ticket activity recorded</div>
          ) : (
            byTicket.map((t) => (
              <div key={t.ticket_id} className="session-panel__row session-panel__row--ticket">
                <span className="session-panel__col-key">
                  <Link to={`/projects/${projectId}/tickets/${t.ticket_id}`}>{t.ticket_key}</Link>
                </span>
                <span className="session-panel__col-title" title={t.title}>
                  {t.title}
                </span>
                <span className="session-panel__col-tokens">{formatTokens(t.tokens)}</span>
                <span className="session-panel__col-time">{formatDuration(t.time_seconds)}</span>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="session-panel__overhead" data-testid="session-detail-overhead">
        <span>
          TL overhead:
          <span className="session-panel__overhead-value">
            {formatTokens(detail.tl_overhead_tokens || 0)}
          </span>
        </span>
        <span>
          PM overhead:
          <span className="session-panel__overhead-value">
            {formatTokens(detail.pm_overhead_tokens || 0)}
          </span>
        </span>
        <span data-testid="session-detail-ad-hoc-overhead">
          Ad Hoc:
          <span className="session-panel__overhead-value">
            {formatTokens(detail.ad_hoc_overhead_tokens || 0)}
          </span>
        </span>
      </div>
    </div>
  );
}

export default SessionDetailPage;
