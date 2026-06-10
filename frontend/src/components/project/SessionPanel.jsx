// Path: src/components/project/SessionPanel.jsx
// File: SessionPanel.jsx
// Created: 2026-06-10
// Purpose: Live view of the current DWB session for a project — header (open/closed state, method, headline), totals, by_role + by_ticket mini-tables, TL/PM/Ad Hoc overhead (ad_hoc_overhead_tokens null-guarded to 0 pending DWB-353). Polls every 10s while open, freezes on close. Does NOT render captured open_phrase / close_phrase text (privacy: user-typed text is not surfaced).
// Caller: ProjectPage.jsx
// Callees: react (useState, useEffect, useRef), api/sessions (getProjectSessions, getSession), styles/sessions.css
// Data In: projectId prop
// Data Out: Default export SessionPanel component
// Last Modified: 2026-06-10

import { useState, useEffect, useRef, useCallback } from 'react';
import { getProjectSessions, getSession } from '../../api/sessions';
import '../../styles/sessions.css';

const POLL_INTERVAL_MS = 10000;
const TRUNCATE_DEFAULT = 80;

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

function formatTime(iso) {
  if (!iso) return '';
  const ts = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return '';
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

function truncate(text, max = TRUNCATE_DEFAULT) {
  if (!text) return '';
  const s = String(text);
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + '...';
}

function SessionPanel({ projectId }) {
  const [sessionId, setSessionId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const pollRef = useRef(null);
  const cancelledRef = useRef(false);

  // Resolve the current session id (most recent row from list).
  // Open sessions come first because the list orders by opened_at desc.
  const resolveSessionId = useCallback(async () => {
    try {
      const list = await getProjectSessions(projectId);
      if (!Array.isArray(list) || list.length === 0) {
        return null;
      }
      // Prefer an open session if there is one, else the most recent.
      const open = list.find((s) => s.status === 'open' || s.closed_at == null);
      if (open) return open.id;
      return list[0].id;
    } catch {
      return null;
    }
  }, [projectId]);

  const loadDetail = useCallback(async (sid) => {
    if (sid == null) {
      setDetail(null);
      return null;
    }
    try {
      const d = await getSession(sid);
      if (!cancelledRef.current) setDetail(d);
      return d;
    } catch {
      return null;
    }
  }, []);

  // Initial mount: resolve session id, fetch detail.
  useEffect(() => {
    cancelledRef.current = false;
    let done = false;
    (async () => {
      const sid = await resolveSessionId();
      if (cancelledRef.current) return;
      setSessionId(sid);
      await loadDetail(sid);
      if (!done && !cancelledRef.current) setLoaded(true);
    })();
    return () => {
      done = true;
      cancelledRef.current = true;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [projectId, resolveSessionId, loadDetail]);

  // Polling: tick every 10s while detail is open. Re-resolve session id each tick
  // so a fresh open on the project surfaces without remount; freeze on close.
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
    pollRef.current = setInterval(async () => {
      const sid = await resolveSessionId();
      if (cancelledRef.current) return;
      if (sid !== sessionId) setSessionId(sid);
      await loadDetail(sid);
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [detail, sessionId, resolveSessionId, loadDetail]);

  if (!loaded) {
    return (
      <div className="session-panel" data-testid="session-panel">
        <div className="session-panel__empty">Loading session...</div>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="session-panel" data-testid="session-panel">
        <div className="session-panel__empty">No active DWB session.</div>
        <div className="session-panel__empty-hint">
          Open one with: "you are archie, read the playbook"
        </div>
      </div>
    );
  }

  const isOpen = detail.status === 'open' || detail.live === true || detail.closed_at == null;
  const headline = detail.headline || null; // null-guarded: ships in DWB-346
  const openLabel = detail.opened_at ? formatTime(detail.opened_at) : '?';
  const closeLabel = detail.closed_at ? formatTime(detail.closed_at) : '';
  const byRole = Array.isArray(detail.by_role) ? detail.by_role : [];
  const byTicket = Array.isArray(detail.by_ticket) ? detail.by_ticket : [];

  return (
    <div className="session-panel" data-testid="session-panel">
      <div className="session-panel__header">
        <span
          className={`session-panel__dot${isOpen ? '' : ' session-panel__dot--closed'}`}
          aria-hidden="true"
        />
        <span className="session-panel__id">SESSION #{detail.id}</span>
        <span
          className={`session-panel__state session-panel__state--${isOpen ? 'open' : 'closed'}`}
        >
          {isOpen ? `open since ${openLabel}` : `closed at ${closeLabel}`}
        </span>
        {detail.open_method && (
          <span className="session-panel__method">
            open: {detail.open_method}
            {!isOpen && detail.close_method ? ` / close: ${detail.close_method}` : ''}
          </span>
        )}
        {headline && (
          <span className="session-panel__headline" data-testid="session-headline">
            {truncate(headline, 120)}
          </span>
        )}
      </div>

      <div className="session-panel__body">
        <div>
          <div className="session-panel__stat-label">Total tokens</div>
          <div className="session-panel__stat-value">{formatTokens(detail.total_tokens)}</div>
        </div>
        <div>
          <div className="session-panel__stat-label">Total time</div>
          <div className="session-panel__stat-value">
            {formatDuration(detail.total_time_seconds)}
          </div>
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
            <div className="session-panel__row--empty">no role activity yet</div>
          ) : (
            byRole.map((r) => (
              <div key={`${r.agent_id}-${r.role}`} className="session-panel__row">
                <span className="session-panel__col-name">{r.agent_name}</span>
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
            <div className="session-panel__row--empty">no ticket activity yet</div>
          ) : (
            byTicket.map((t) => (
              <div key={t.ticket_id} className="session-panel__row session-panel__row--ticket">
                <span className="session-panel__col-key">{t.ticket_key}</span>
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

      {(detail.tl_overhead_tokens > 0 || detail.pm_overhead_tokens > 0 || (detail.ad_hoc_overhead_tokens || 0) > 0) && (
        <div className="session-panel__overhead">
          <span>
            TL overhead:
            <span className="session-panel__overhead-value">
              {formatTokens(detail.tl_overhead_tokens)}
            </span>
          </span>
          <span>
            PM overhead:
            <span className="session-panel__overhead-value">
              {formatTokens(detail.pm_overhead_tokens)}
            </span>
          </span>
          <span data-testid="session-panel-ad-hoc-overhead">
            Ad Hoc:
            <span className="session-panel__overhead-value">
              {formatTokens(detail.ad_hoc_overhead_tokens || 0)}
            </span>
          </span>
        </div>
      )}
    </div>
  );
}

export default SessionPanel;
