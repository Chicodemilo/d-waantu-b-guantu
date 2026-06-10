// Path: src/components/project/SessionsTable.jsx
// File: SessionsTable.jsx
// Created: 2026-06-10
// Purpose: Full DWB sessions table for a project — every session by default (no slice), scannable rows. Columns: # | Start | End | Duration | Tokens | Tix Made | Tix Done | Summary (headline -> ticket_summary fallback). Aggregate fields are null-guarded for the DWB-346 transition. Rows link to the per-session detail page. Renamed from RecentSessionsStrip after DWB-349 made this the primary content of SessionsPage. Accepts optional `limit` to cap the row count (e.g. when embedding a small recent-only widget elsewhere). Duration column ticks live (every 10s) for any row whose closed_at is null — derived from (now - opened_at) — so the open session matches the elapsed display in the SessionFooter. Closed rows use the frozen total_time_seconds from the API.
// Caller: SessionsPage.jsx
// Callees: react (useState, useEffect), react-router-dom (Link), api/sessions (getProjectSessions), styles/sessions.css
// Data In: projectId prop, optional limit prop (default undefined = all rows)
// Data Out: Default export SessionsTable component
// Last Modified: 2026-06-10

import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { getProjectSessions } from '../../api/sessions';
import '../../styles/sessions.css';

const DASH = '-';

function parseUtc(iso) {
  if (!iso) return null;
  const ts = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z';
  const d = new Date(ts);
  return isNaN(d.getTime()) ? null : d;
}

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
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`;
  if (m > 0) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

// Friendly time: clock for today, "yesterday H:MM AM/PM" for yesterday,
// "Mon DD H:MM AM/PM" for older. Honors local TZ.
function formatWhen(iso) {
  const d = parseUtc(iso);
  if (!d) return DASH;
  const now = new Date();
  const sameDay = (a, b) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);

  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  if (sameDay(d, now)) return `today ${time}`;
  if (sameDay(d, yesterday)) return `yesterday ${time}`;

  const diffDays = Math.abs((now - d) / (1000 * 60 * 60 * 24));
  if (diffDays < 7) {
    const weekday = d.toLocaleDateString([], { weekday: 'short' });
    return `${weekday} ${time}`;
  }
  const datePart = d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  return `${datePart} ${time}`;
}

function whatLabel(row) {
  // DWB-346 will add headline + ticket_summary. Null-guard both.
  if (row.headline) return row.headline;
  if (row.ticket_summary) return row.ticket_summary;
  return DASH;
}

const DURATION_TICK_MS = 10000;

function SessionsTable({ projectId, limit }) {
  const [rows, setRows] = useState(null); // null = loading, [] = empty
  const [error, setError] = useState(null);
  const [now, setNow] = useState(() => Date.now());

  // 10s tick so the Duration column for open sessions stays live (matches the
  // SessionFooter's elapsed display). Closed rows ignore `now` and keep using
  // their frozen total_time_seconds.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), DURATION_TICK_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const all = await getProjectSessions(projectId);
        if (cancelled) return;
        if (!Array.isArray(all)) {
          setRows([]);
          return;
        }
        // Sort by opened_at desc as a defensive measure; API ordering may
        // change but the UI contract is most-recent first.
        const sorted = [...all].sort((a, b) => {
          const ta = parseUtc(a.opened_at)?.getTime() || 0;
          const tb = parseUtc(b.opened_at)?.getTime() || 0;
          return tb - ta;
        });
        setRows(limit ? sorted.slice(0, limit) : sorted);
      } catch (err) {
        if (!cancelled) setError(err?.message || 'failed to load sessions');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, limit]);

  if (error) {
    return (
      <div className="recent-sessions">
        <div className="recent-sessions__empty">Error loading sessions: {error}</div>
      </div>
    );
  }

  if (rows === null) {
    return (
      <div className="recent-sessions">
        <div className="recent-sessions__empty">Loading...</div>
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="recent-sessions">
        <div className="recent-sessions__empty">No prior sessions yet.</div>
      </div>
    );
  }

  return (
    <div className="recent-sessions">
      <div className="recent-sessions__row recent-sessions__row--header">
        <span>#</span>
        <span>Start</span>
        <span>End</span>
        <span className="recent-sessions__col-num">Duration</span>
        <span className="recent-sessions__col-num">Tokens</span>
        <span className="recent-sessions__col-num">Tix Made</span>
        <span className="recent-sessions__col-num">Tix Done</span>
        <span>Summary</span>
      </div>
      {rows.map((r) => {
        const ticketsMade = r.tickets_made == null ? DASH : r.tickets_made;
        const ticketsDone = r.tickets_completed == null ? DASH : r.tickets_completed;
        // Live duration for open rows (recompute each 10s tick); frozen
        // total_time_seconds for closed rows.
        let durationSec = r.total_time_seconds;
        if (r.closed_at == null && r.opened_at) {
          const opened = parseUtc(r.opened_at);
          if (opened) durationSec = Math.floor((now - opened.getTime()) / 1000);
        }
        return (
          <Link
            key={r.id}
            to={`/projects/${projectId}/sessions/${r.id}`}
            className="recent-sessions__row recent-sessions__row--data"
            data-testid="recent-session-row"
          >
            <span className="recent-sessions__col-id">#{r.id}</span>
            <span>{formatWhen(r.opened_at)}</span>
            <span>{r.closed_at ? formatWhen(r.closed_at) : DASH}</span>
            <span className="recent-sessions__col-num">{formatDuration(durationSec)}</span>
            <span className="recent-sessions__col-num">{formatTokens(r.total_tokens)}</span>
            <span className="recent-sessions__col-num">{ticketsMade}</span>
            <span className="recent-sessions__col-num">{ticketsDone}</span>
            <span className="recent-sessions__col-what" title={whatLabel(r)}>
              {whatLabel(r)}
            </span>
          </Link>
        );
      })}
    </div>
  );
}

export default SessionsTable;
