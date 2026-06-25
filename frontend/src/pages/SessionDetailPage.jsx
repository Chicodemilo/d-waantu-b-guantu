// Path: src/pages/SessionDetailPage.jsx
// File: SessionDetailPage.jsx
// Created: 2026-06-10
// Purpose: Per-session drill-down at /projects/:pid/sessions/:sid. Renders GET /api/sessions/{id} payload: header (id, status, methods, reasons, headline), open/close datetimes, totals, by_role table, by_ticket table (linked to ticket detail pages), TL/PM/Ad Hoc overhead (always visible on this drill-down, all three null-guarded to 0; ad_hoc_overhead_tokens ships in DWB-353). Polls every 10s while the session is live, freezes when closed. Returns a Session not found view with a back link on 404. Does NOT render captured open_phrase / close_phrase text (privacy: user-typed text is not surfaced).
// Caller: App.jsx (route: /projects/:id/sessions/:sid)
// Callees: react (useState, useEffect, useRef, useCallback, useMemo), react-router-dom (useParams, Link, useLocation), store/useStore, api/sessions (getSession), api/projects (getProject), api/client (ApiError), components/project/SessionSummary, styles/dashboard.css, styles/sessions.css
// Data In: Route params id (project id) and sid (session id), project from store, location.state (recall back-link), the session's project repo_url (fetched for narrative ref links)
// Data Out: Default export SessionDetailPage component
// Last Modified: 2026-06-25 (DWBG-022: clickable narrative refs via repo_url; DWBG-023: source-aware "back to search")
//   DWB-486: render summary write-up + keyword tags

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useParams, Link, useLocation } from 'react-router-dom';
import useStore from '../store/useStore';
import { getSession } from '../api/sessions';
import { getProject } from '../api/projects';
import { ApiError } from '../api/client';
import SessionSummary from '../components/project/SessionSummary';
import '../styles/dashboard.css';
import '../styles/sessions.css';

const POLL_INTERVAL_MS = 10000;

// DWBG-022: turn a bare narrative ref into a repo web URL, or null when we can't.
// `repoUrl` is the session's project repo_url (string | null). null repo_url ->
// return null for every ref so InlineMarkdown falls back to styled, non-clickable
// text exactly as it does today (no broken/undefined links).
//   file or file:line -> {repo_url}/blob/HEAD/{path}#L{line}
//   commit sha (7-40 hex) -> {repo_url}/commit/{sha}
function buildRefHref(repoUrl, ref) {
  if (!repoUrl || !ref) return null;
  const base = String(repoUrl).trim().replace(/\/+$/, '');
  if (!base) return null;
  const r = String(ref).trim();

  // A pure commit sha: 7-40 lowercase hex with no path separators or dots.
  if (/^[0-9a-f]{7,40}$/.test(r)) {
    return `${base}/commit/${r}`;
  }

  // Otherwise treat it as a file ref, optionally suffixed with :line.
  const lineMatch = r.match(/^(.*?):(\d+)$/);
  const path = lineMatch ? lineMatch[1] : r;
  const line = lineMatch ? lineMatch[2] : null;
  const cleanPath = path.replace(/^\/+/, ''); // no leading slash in a blob path
  if (!cleanPath) return null;
  const anchor = line ? `#L${line}` : '';
  return `${base}/blob/HEAD/${cleanPath}${anchor}`;
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
  const location = useLocation();
  const project = useStore((s) => s.getProject(projectId));
  const [detail, setDetail] = useState(null);
  const [status, setStatus] = useState('loading'); // 'loading' | 'ok' | 'not_found' | 'error'
  const [errMsg, setErrMsg] = useState('');
  // DWBG-022: the session's project repo_url, fetched once. string | null.
  // Stays null when the endpoint/field isn't live or the project has no remote,
  // which makes the narrative refs render as styled non-clickable text.
  const [repoUrl, setRepoUrl] = useState(null);
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

  // DWBG-022: fetch the session's project to learn its repo_url for narrative ref
  // links. Best-effort: any failure (endpoint not live yet, no remote, 404) just
  // leaves repoUrl null, and refs render as styled non-clickable text.
  useEffect(() => {
    const pid = detail?.project_id ?? projectId;
    if (pid == null) return undefined;
    let cancelled = false;
    getProject(pid)
      .then((p) => {
        if (cancelled) return;
        setRepoUrl(p && typeof p.repo_url === 'string' ? p.repo_url : null);
      })
      .catch(() => {
        if (cancelled) return;
        setRepoUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [detail?.project_id, projectId]);

  // DWBG-022: resolver passed down to InlineMarkdown. Returns a repo web URL for a
  // bare ref, or null (-> styled text). When repoUrl is null the resolver is null
  // too, so SessionSummary/InlineMarkdown take the existing no-resolver path.
  const refResolver = useMemo(() => {
    if (!repoUrl) return undefined;
    return (ref) => buildRefHref(repoUrl, ref);
  }, [repoUrl]);

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

  // DWBG-023: source-aware "back to search". Only when the user arrived from the
  // cross-project Recall page (SessionResultCard sets location.state.from='recall')
  // do we offer a link back to /sessions with the preserved query + facets. Reaching
  // this page from the per-project sessions list leaves state null, so this affordance
  // is absent there (and the normal "back to sessions" breadcrumb still applies).
  const cameFromRecall = location.state?.from === 'recall';
  const recallSearch = cameFromRecall ? location.state?.recallSearch || '' : '';
  const recallBackLink = cameFromRecall ? (
    <Link to={`/sessions${recallSearch}`} data-testid="back-to-recall">
      {'<- back to search'}
    </Link>
  ) : null;

  if (status === 'loading') {
    return (
      <div className="dashboard" data-testid="session-detail-page">
        <div className="dashboard__breadcrumb">
          {recallBackLink}
          {recallBackLink && <span> / </span>}
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
          {recallBackLink}
          {recallBackLink && <span> / </span>}
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
          {recallBackLink}
          {recallBackLink && <span> / </span>}
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
        {recallBackLink}
        {recallBackLink && <span> / </span>}
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

      {/* DWB-486: session write-up (DWB-483 summary JSON) + keyword tags.
          DWBG-009: + TL-authored narrative with provenance. */}
      <SessionSummary
        summary={detail.summary}
        keywords={detail.keywords}
        narrative={detail.narrative}
        narrativeAuthor={detail.narrative_author}
        narrativeGeneratedAt={detail.narrative_generated_at}
        refResolver={refResolver}
      />

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
