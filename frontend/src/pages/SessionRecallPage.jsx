// Path: src/pages/SessionRecallPage.jsx
// File: SessionRecallPage.jsx
// Created: 2026-06-25
// Purpose: Top-level cross-project Session Recall page (DWBG-012) at /sessions. A search box
//          plus facet filters (project, agent, epic, date range) drive GET /api/sessions/search
//          (DWBG-011 contract). The search is explicit: the user types a query (q is required by
//          the contract) and submits; facets are optional and narrow the query (project omitted
//          => cross-project). Results render as SessionResultCards that link into the existing
//          per-session SessionDetailPage. Handles every async state: loading, error, no-results,
//          and results. Facet options come from the Zustand store (projects/agents/epics already
//          loaded + polled by useAppData), so no extra fetching.
//          DWBG-016: instead of an empty idle state, the DEFAULT view (no query) loads the
//          newest-first recent-sessions feed (GET /api/sessions/recent) so the operator never
//          has to search to find a session. Typing + submitting a query switches to search mode;
//          clearing the query (or the dedicated control) returns to the recent feed. Recent mode
//          degrades gracefully when the endpoint isn't available yet (e.g. before Devin lands it).
//          DWBG-023: the COMMITTED query + facets live in the URL query string
//          (/sessions?q=...&project_id=...&agent_id=...&epic_id=...&from=...&to=...). The URL is
//          the source of truth for what is displayed, so the search survives navigating into a
//          result and back (and a page refresh). Form inputs are local state seeded from the URL;
//          submit/clear/recent rewrite the URL, and a single effect keyed on the URL runs the
//          matching fetch (search when q is present, recent otherwise).
// Caller: App.jsx (route: /sessions)
// Callees: react (useState, useMemo, useRef, useEffect, useCallback), react-router-dom
//          (useSearchParams), store/useStore, api/sessions (searchSessions, getRecentSessions),
//          api/client (ApiError), components/project/SessionResultCard, styles/dashboard.css,
//          styles/sessions.css
// Data In: URL query string (committed q + facets); facet options from the store
// Data Out: default export SessionRecallPage component
// Last Modified: 2026-06-25 (DWBG-023: persist committed query + facets in the URL)

import { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import useStore from '../store/useStore';
import { searchSessions, getRecentSessions } from '../api/sessions';
import { ApiError } from '../api/client';
import SessionResultCard from '../components/project/SessionResultCard';
import '../styles/dashboard.css';
import '../styles/sessions.css';

const RECENT_LIMIT = 25;

// DWBG-023: the facet keys we round-trip through the URL query string. The form
// state below uses camelCase keys; the URL uses snake_case to match the API.
const FACET_PARAMS = [
  ['projectId', 'project_id'],
  ['agentId', 'agent_id'],
  ['epicId', 'epic_id'],
  ['from', 'from'],
  ['to', 'to'],
];

// Read the committed facet values out of a URLSearchParams into camelCase form state.
function facetsFromParams(params) {
  const out = {};
  for (const [stateKey, urlKey] of FACET_PARAMS) {
    out[stateKey] = params.get(urlKey) || '';
  }
  return out;
}

// mode: 'recent' (default feed, no committed query) | 'search' (a query is committed)
// status: 'loading' | 'ok' | 'error'
function SessionRecallPage() {
  const projects = useStore((s) => s.projects);
  const agents = useStore((s) => s.agents);
  const epics = useStore((s) => s.epics);

  // DWBG-023: the URL is the source of truth for the COMMITTED query + facets.
  const [searchParams, setSearchParams] = useSearchParams();
  const committedQ = (searchParams.get('q') || '').trim();
  const committedFacets = useMemo(
    () => facetsFromParams(searchParams),
    [searchParams]
  );

  // Form inputs are local state, seeded once from the URL so a deep-linked /sessions?q=...
  // (e.g. on back-navigation) shows its query + facets in the controls.
  const [q, setQ] = useState(searchParams.get('q') || '');
  const [projectId, setProjectId] = useState(committedFacets.projectId);
  const [agentId, setAgentId] = useState(committedFacets.agentId);
  const [epicId, setEpicId] = useState(committedFacets.epicId);
  const [from, setFrom] = useState(committedFacets.from);
  const [to, setTo] = useState(committedFacets.to);

  const [mode, setMode] = useState(committedQ ? 'search' : 'recent');
  const [status, setStatus] = useState('loading');
  const [results, setResults] = useState([]);
  const [errMsg, setErrMsg] = useState('');

  // Guard against out-of-order responses (later request wins) across BOTH the
  // recent feed and search — a stale recent response must not clobber a search.
  const reqIdRef = useRef(0);

  const loadRecent = useCallback(() => {
    const myReq = ++reqIdRef.current;
    setMode('recent');
    setStatus('loading');
    setErrMsg('');

    getRecentSessions({ limit: RECENT_LIMIT })
      .then((data) => {
        if (myReq !== reqIdRef.current) return;
        setResults(Array.isArray(data) ? data : []);
        setStatus('ok');
      })
      .catch((err) => {
        if (myReq !== reqIdRef.current) return;
        // Endpoint may not exist yet while Devin lands it — degrade gracefully.
        const msg =
          err instanceof ApiError && err.status === 404
            ? 'Recent sessions are not available yet.'
            : err?.message || 'Could not load recent sessions.';
        setErrMsg(msg);
        setResults([]);
        setStatus('error');
      });
  }, []);

  const loadSearch = useCallback((qValue, facets) => {
    const myReq = ++reqIdRef.current;
    setMode('search');
    setStatus('loading');
    setErrMsg('');

    searchSessions({
      q: qValue,
      projectId: facets.projectId || undefined,
      agentId: facets.agentId || undefined,
      epicId: facets.epicId || undefined,
      from: facets.from || undefined,
      to: facets.to || undefined,
    })
      .then((data) => {
        if (myReq !== reqIdRef.current) return;
        setResults(Array.isArray(data) ? data : []);
        setStatus('ok');
      })
      .catch((err) => {
        if (myReq !== reqIdRef.current) return;
        // The endpoint may not exist yet while DWBG-011 lands — degrade gracefully.
        const msg =
          err instanceof ApiError
            ? err.status === 404
              ? 'Session search is not available yet.'
              : err.message
            : err?.message || 'Search failed.';
        setErrMsg(msg);
        setResults([]);
        setStatus('error');
      });
  }, []);

  // DWBG-023: a single effect keyed on the committed URL state drives the fetch.
  // q present -> search; otherwise -> recent. This runs on mount (restoring a
  // deep-linked search after back-navigation or refresh) and whenever the URL changes.
  useEffect(() => {
    if (committedQ) {
      loadSearch(committedQ, committedFacets);
    } else {
      loadRecent();
    }
  }, [committedQ, committedFacets, loadSearch, loadRecent]);

  const projectById = useMemo(() => {
    const m = new Map();
    for (const p of projects) m.set(p.id, p);
    return m;
  }, [projects]);

  // Epics are project-scoped; when a project facet is chosen, narrow the epic list.
  const epicOptions = useMemo(() => {
    if (!projectId) return epics;
    return epics.filter((e) => e.project_id === Number(projectId));
  }, [epics, projectId]);

  const projectLabelFor = (pid) => {
    const p = projectById.get(pid);
    return p ? p.prefix : null;
  };

  const trimmedQ = q.trim();
  const canSearch = trimmedQ !== '';

  // DWBG-023: commit the typed query + chosen facets to the URL. The fetch effect
  // above reacts to the URL change and runs the search, so the state lives in a
  // place that survives navigating into a result and back.
  function runSearch(e) {
    if (e) e.preventDefault();
    if (!canSearch) return;
    const next = new URLSearchParams();
    next.set('q', trimmedQ);
    const facets = { projectId, agentId, epicId, from, to };
    for (const [stateKey, urlKey] of FACET_PARAMS) {
      if (facets[stateKey]) next.set(urlKey, facets[stateKey]);
    }
    setSearchParams(next);
  }

  // DWBG-016/023: drop back to the recent feed by clearing the query from the URL.
  // Facets are dropped too so the recent feed isn't silently narrowed.
  function showRecent() {
    setQ('');
    setSearchParams(new URLSearchParams());
  }

  function clearFacets() {
    setProjectId('');
    setAgentId('');
    setEpicId('');
    setFrom('');
    setTo('');
  }

  return (
    <div className="dashboard" data-testid="session-recall-page">
      <div className="dashboard__breadcrumb">
        <span>session recall</span>
      </div>

      <h1 className="dashboard__title">Session Recall</h1>
      <p className="recall__lede">
        Recent sessions across every project, newest first. Search write-ups, headlines,
        and keywords to narrow them.
      </p>

      <form className="recall__controls" onSubmit={runSearch} data-testid="recall-form">
        <div className="recall__search-row">
          <input
            type="text"
            className="recall__search-input"
            placeholder="search sessions across all projects..."
            value={q}
            onChange={(ev) => setQ(ev.target.value)}
            aria-label="search sessions"
            data-testid="recall-query"
          />
          <button
            type="submit"
            className="recall__search-btn"
            disabled={!canSearch}
            data-testid="recall-submit"
          >
            search
          </button>
        </div>

        <div className="recall__facets" data-testid="recall-facets">
          <label className="recall__facet">
            <span className="recall__facet-label">project</span>
            <select
              className="recall__facet-input"
              value={projectId}
              onChange={(ev) => {
                setProjectId(ev.target.value);
                setEpicId(''); // epic options depend on project; reset to avoid a stale pick
              }}
              data-testid="recall-facet-project"
            >
              <option value="">all projects</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.prefix}
                </option>
              ))}
            </select>
          </label>

          <label className="recall__facet">
            <span className="recall__facet-label">agent</span>
            <select
              className="recall__facet-input"
              value={agentId}
              onChange={(ev) => setAgentId(ev.target.value)}
              data-testid="recall-facet-agent"
            >
              <option value="">all agents</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>

          <label className="recall__facet">
            <span className="recall__facet-label">epic</span>
            <select
              className="recall__facet-input"
              value={epicId}
              onChange={(ev) => setEpicId(ev.target.value)}
              data-testid="recall-facet-epic"
            >
              <option value="">all epics</option>
              {epicOptions.map((ep) => (
                <option key={ep.id} value={ep.id}>
                  {ep.name}
                </option>
              ))}
            </select>
          </label>

          <label className="recall__facet">
            <span className="recall__facet-label">from</span>
            <input
              type="date"
              className="recall__facet-input"
              value={from}
              onChange={(ev) => setFrom(ev.target.value)}
              data-testid="recall-facet-from"
            />
          </label>

          <label className="recall__facet">
            <span className="recall__facet-label">to</span>
            <input
              type="date"
              className="recall__facet-input"
              value={to}
              onChange={(ev) => setTo(ev.target.value)}
              data-testid="recall-facet-to"
            />
          </label>

          <button
            type="button"
            className="recall__clear-btn"
            onClick={clearFacets}
            data-testid="recall-clear"
          >
            clear filters
          </button>
        </div>
      </form>

      <div className="recall__results" data-testid="recall-results">
        {status === 'loading' && (
          <div className="recall__state" data-testid="recall-loading">
            {mode === 'recent' ? 'Loading recent sessions...' : 'Searching...'}
          </div>
        )}

        {status === 'error' && (
          <div className="recall__state recall__state--error" data-testid="recall-error">
            {errMsg}
          </div>
        )}

        {status === 'ok' && results.length === 0 && (
          <div className="recall__state" data-testid="recall-no-results">
            {mode === 'recent'
              ? 'No sessions recorded yet.'
              : `No sessions match "${committedQ}".`}
          </div>
        )}

        {status === 'ok' && results.length > 0 && (
          <>
            <div className="recall__count-row">
              <div className="recall__count" data-testid="recall-count">
                {mode === 'recent'
                  ? `${results.length} recent ${results.length === 1 ? 'session' : 'sessions'}`
                  : `${results.length} ${results.length === 1 ? 'result' : 'results'}`}
              </div>
              {mode === 'search' && (
                <button
                  type="button"
                  className="recall__recent-btn"
                  onClick={showRecent}
                  data-testid="recall-show-recent"
                >
                  ← recent sessions
                </button>
              )}
            </div>
            <div className="recall__list">
              {results.map((row) => (
                <SessionResultCard
                  key={`${row.project_id}-${row.id}`}
                  row={row}
                  projectLabel={projectLabelFor(row.project_id)}
                  recallSearch={`?${searchParams.toString()}`}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default SessionRecallPage;
