// Path: src/components/layout/SessionFooter.jsx
// File: SessionFooter.jsx
// Created: 2026-06-10
// Purpose: Single persistent app-shell footer row. LEFT: session dot + title + open-since label for the current project's DWB session (or "no DWB session" / "no project context"). RIGHT: global polling status (polling | idle, interval, last-updated) + infra warning count if any. Pulls the right-side polling info from the Zustand store, replacing the standalone polling Footer component. Whole bar is a Link to /projects/:id/sessions when scoped to a project; renders an inert strip on non-project routes. Five session dot states: active (green pulse), closed (slate), error (red pulse), idle-warning (amber pulse), none (hollow gray). Does NOT render captured open_phrase / close_phrase text.
// Caller: AppShell.jsx
// Callees: react (useState, useEffect, useRef, useCallback), react-router-dom (Link, useMatch), api/sessions (getProjectSessions), store/useStore (polling + infraWarnings), styles/session-footer.css
// Data In: Resolves project_id from the route; pulls polling + infraWarnings from the Zustand store
// Data Out: Default export SessionFooter component
// Last Modified: 2026-06-10

import { useState, useEffect, useRef, useCallback } from 'react';
import { Link, useMatch } from 'react-router-dom';
import { getProjectSessions } from '../../api/sessions';
import useStore from '../../store/useStore';
import '../../styles/session-footer.css';

const POLL_INTERVAL_MS = 10000;
const IDLE_WARNING_THRESHOLD_MS = 50 * 60 * 1000; // 50 min, sweeper auto-closes at 60
const TITLE_TRUNCATE = 60;

const INFRA_SEVERITY_COLORS = {
  critical: 'var(--red)',
  warning: 'var(--orange)',
  info: 'var(--blue)',
};

function parseUtc(iso) {
  if (!iso) return null;
  const ts = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z';
  const d = new Date(ts);
  return isNaN(d.getTime()) ? null : d;
}

function formatRelativeElapsed(opened) {
  const d = parseUtc(opened);
  if (!d) return '';
  const elapsed = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  const min = Math.floor(elapsed / 60);
  if (min < 1) return 'open just now';
  if (min < 60) return `open ${min} min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `open ${h}h ${m}m`;
}

function formatClock(iso) {
  const d = parseUtc(iso);
  if (!d) return '';
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function formatClockSeconds(iso) {
  const d = parseUtc(iso);
  if (!d) return '';
  return d.toLocaleTimeString('en-US', { hour12: false });
}

function truncate(text, max = TITLE_TRUNCATE) {
  if (!text) return '';
  const s = String(text);
  return s.length <= max ? s : s.slice(0, max - 1) + '...';
}

// Pick the dot state from the latest session row + last-fetch outcome.
function pickState({ row, fetchError, now }) {
  if (fetchError) return 'error';
  if (!row) return 'none';
  const isOpen = row.status === 'open' || row.closed_at == null;
  if (!isOpen) return 'closed';
  const opened = parseUtc(row.opened_at);
  if (opened && now - opened.getTime() > IDLE_WARNING_THRESHOLD_MS) return 'idle-warning';
  return 'active';
}

function titleFor(row) {
  if (!row) return 'no DWB session';
  // headline ships in DWB-346, null-guarded.
  if (row.headline) return truncate(row.headline);
  return `SESSION #${row.id}`;
}

function SessionFooter() {
  const projectMatch = useMatch('/projects/:id/*') || useMatch('/projects/:id');
  const projectId = projectMatch?.params?.id || null;

  const polling = useStore((s) => s.polling);
  const infraWarnings = useStore((s) => s.infraWarnings);

  const [row, setRow] = useState(null);
  const [fetchError, setFetchError] = useState(false);
  const pollRef = useRef(null);
  const cancelledRef = useRef(false);

  const fetchSession = useCallback(async (pid) => {
    if (!pid) return;
    try {
      const list = await getProjectSessions(pid);
      if (cancelledRef.current) return;
      setFetchError(false);
      if (!Array.isArray(list) || list.length === 0) {
        setRow(null);
        return;
      }
      const open = list.find((s) => s.status === 'open' || s.closed_at == null);
      setRow(open || list[0]);
    } catch {
      if (cancelledRef.current) return;
      setFetchError(true);
    }
  }, []);

  useEffect(() => {
    cancelledRef.current = false;
    setRow(null);
    setFetchError(false);

    if (!projectId) {
      return () => {
        cancelledRef.current = true;
      };
    }

    fetchSession(projectId);

    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(() => {
      fetchSession(projectId);
    }, POLL_INTERVAL_MS);

    return () => {
      cancelledRef.current = true;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [projectId, fetchSession]);

  const worstSeverity = infraWarnings.length > 0
    ? infraWarnings.some((w) => w.severity === 'critical')
      ? 'critical'
      : infraWarnings.some((w) => w.severity === 'warning')
        ? 'warning'
        : 'info'
    : null;

  // Right side renders the global polling status (replaces the old standalone
  // Footer component). On session-fetch error, swap the polling text for a
  // retry indicator so the user knows something is off; the global polling
  // info is still implicit via the "last updated" timestamp.
  const renderRight = () => {
    const intervalSec = Math.round(polling.interval / 1000);
    const lastUpdated = formatClockSeconds(polling.lastUpdated);
    return (
      <>
        {fetchError && (
          <span className="session-footer__error">poll failed; retrying</span>
        )}
        {infraWarnings.length > 0 && (
          <span
            className="session-footer__infra"
            title={infraWarnings.map((w) => w.message).join('\n')}
            style={{ color: INFRA_SEVERITY_COLORS[worstSeverity] }}
          >
            {infraWarnings.length} infra warning{infraWarnings.length !== 1 ? 's' : ''}
          </span>
        )}
        <span className="session-footer__poll">
          {polling.isActive ? 'polling' : 'idle'} &middot; {intervalSec}s interval &middot; last updated: {lastUpdated}
        </span>
      </>
    );
  };

  if (!projectId) {
    return (
      <div className="session-footer session-footer--inert" data-testid="session-footer">
        <div className="session-footer__left">
          <span className="session-footer__dot session-footer__dot--none" />
          <span className="session-footer__title">no project context</span>
        </div>
        <div className="session-footer__right">{renderRight()}</div>
      </div>
    );
  }

  const now = Date.now();
  const state = pickState({ row, fetchError, now });
  const title = titleFor(row);
  const isOpen = row && (row.status === 'open' || row.closed_at == null);
  const startLabel = row && row.opened_at
    ? (isOpen
        ? `${formatRelativeElapsed(row.opened_at)} (since ${formatClock(row.opened_at)})`
        : `closed at ${formatClock(row.closed_at)}`)
    : '';

  return (
    <Link
      to={`/projects/${projectId}/sessions`}
      className={`session-footer session-footer--${state}`}
      data-testid="session-footer"
      data-state={state}
    >
      <div className="session-footer__left">
        <span className={`session-footer__dot session-footer__dot--${state}`} aria-hidden="true" />
        <span className="session-footer__title">{title}</span>
        {startLabel && <span className="session-footer__time">{startLabel}</span>}
      </div>
      <div className="session-footer__right">{renderRight()}</div>
    </Link>
  );
}

export default SessionFooter;
