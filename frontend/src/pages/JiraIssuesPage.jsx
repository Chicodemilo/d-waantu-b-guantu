// Path: src/pages/JiraIssuesPage.jsx
// File: JiraIssuesPage.jsx
// Created: 2026-05-27
// Purpose: Unified Jira table for a project (DWB-342). Renders the 10-column snapshot-backed view (DWB id/sprint/status + Jira id/sprint/status/assignee + created/updated + title), with a debounced fuzzy search box, sortable column headers, a manual sync button + canonical .tooltip-trigger info affordance describing the read-only ingestion, and row navigation to the DWB ticket detail page. Created/Updated columns format as dd-mm-yy hh:mm (24h, local TZ). Read-only Jira ingestion - nothing in this page modifies Jira. Null-guards jira_sprint and jira_reporter pending DWB-356 normalizer fix.
// Caller: App.jsx (route: /projects/:id/jira)
// Callees: react, react-router-dom (useParams, useNavigate), store/useStore, api/jira (getProjectJiraTickets, triggerProjectJiraSync, getProjectJiraSyncStatus), api/client (ApiError), styles/jira.css
// Data In: Route param :id (DWB project id)
// Data Out: Default export JiraIssuesPage component
// Last Modified: 2026-06-10

import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import useStore from '../store/useStore';
import {
  getProjectJiraTickets,
  triggerProjectJiraSync,
  getProjectJiraSyncStatus,
} from '../api/jira';
import { ApiError } from '../api/client';
import '../styles/jira.css';

const DASH = '-';
const PAGE_LIMIT = 200;
const SEARCH_DEBOUNCE_MS = 250;
const SYNC_POLL_MS = 1000;

const COLUMNS = [
  { key: 'dwb_key',       label: 'DWB',          align: 'left'  },
  { key: 'dwb_sprint',    label: 'DWB Sprint',   align: 'left'  },
  { key: 'dwb_status',    label: 'DWB Status',   align: 'left'  },
  { key: 'jira_key',      label: 'Jira',         align: 'left'  },
  { key: 'jira_sprint',   label: 'Jira Sprint',  align: 'left'  },
  { key: 'jira_status',   label: 'Jira Status',  align: 'left'  },
  { key: 'jira_issue_type', label: 'Type',       align: 'left'  },
  { key: 'jira_parent_key', label: 'Parent',     align: 'left'  },
  { key: 'jira_epic_key',   label: 'Epic',       align: 'left'  },
  { key: 'jira_assignee', label: 'Assignee',     align: 'left'  },
  { key: 'created_at',    label: 'Created',      align: 'right' },
  { key: 'updated_at',    label: 'Updated',      align: 'right' },
  { key: 'title',         label: 'Title',        align: 'left'  },
];

function parseUtc(iso) {
  if (!iso) return null;
  const ts = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z';
  const d = new Date(ts);
  return isNaN(d.getTime()) ? null : d;
}

// Fixed format dd-mm-yy hh:mm (24h), local TZ. Used for Created and Updated
// columns so every row reads identically and dates aren't ambiguous.
function formatDateShort(iso) {
  const d = parseUtc(iso);
  if (!d) return DASH;
  const pad = (n) => String(n).padStart(2, '0');
  const dd = d.getDate();
  const mm = d.getMonth() + 1;
  const yy = pad(d.getFullYear() % 100);
  const hh = d.getHours();
  const mi = pad(d.getMinutes());
  return `${dd}-${mm}-${yy} ${hh}:${mi}`;
}

function formatSyncTimestamp(iso) {
  const d = parseUtc(iso);
  if (!d) return 'never';
  return d.toLocaleString([], {
    month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
  });
}

function JiraIssuesPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const project = useStore((s) => s.getProject(id));

  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [sort, setSort] = useState('updated_at');
  const [order, setOrder] = useState('desc');

  // Sync state: status enum from backend ('idle' | 'running' | 'done' | 'error')
  // plus last_synced_at + counts. Polled while running.
  const [syncStatus, setSyncStatus] = useState('idle');
  const [lastSyncedAt, setLastSyncedAt] = useState(null);
  const [syncCounts, setSyncCounts] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const pollRef = useRef(null);

  const isJiraLinked = !!project?.jira_project_key;

  // Debounce the search input.
  useEffect(() => {
    const id = setTimeout(() => setDebouncedQ(q), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [q]);

  // Fetch rows whenever sort/order/q/project changes.
  const fetchRows = useCallback(async () => {
    if (!project || !isJiraLinked) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getProjectJiraTickets(project.id, {
        q: debouncedQ || undefined,
        sort,
        order,
        limit: PAGE_LIMIT,
        offset: 0,
      });
      setRows(Array.isArray(data?.rows) ? data.rows : []);
      setTotal(data?.total || 0);
    } catch (err) {
      setError(err?.message || 'failed to load Jira table');
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [project, isJiraLinked, debouncedQ, sort, order]);

  useEffect(() => {
    fetchRows();
  }, [fetchRows]);

  // Initial sync-status probe.
  useEffect(() => {
    if (!project || !isJiraLinked) return;
    getProjectJiraSyncStatus(project.id)
      .then((data) => {
        setSyncStatus(data?.status || 'idle');
        setLastSyncedAt(data?.last_synced_at || null);
        setSyncCounts(data?.counts || null);
      })
      .catch(() => {});
  }, [project, isJiraLinked]);

  // Sync polling lifecycle.
  const startPolling = useCallback(() => {
    if (!project) return;
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const data = await getProjectJiraSyncStatus(project.id);
        setSyncStatus(data?.status || 'idle');
        setLastSyncedAt(data?.last_synced_at || null);
        setSyncCounts(data?.counts || null);
        if (data?.status !== 'running') {
          clearInterval(pollRef.current);
          pollRef.current = null;
          setSyncing(false);
          // Refetch rows after a completed sync so the table picks up new data.
          if (data?.status === 'done') fetchRows();
        }
      } catch {
        // Tolerated: poll failures stop the loop but keep the prior status.
        clearInterval(pollRef.current);
        pollRef.current = null;
        setSyncing(false);
      }
    }, SYNC_POLL_MS);
  }, [project, fetchRows]);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  const handleSync = async () => {
    if (!project || syncing) return;
    setSyncing(true);
    try {
      await triggerProjectJiraSync(project.id);
      // v1 backend is synchronous: POST returns when sync completes. Re-read
      // status to surface fresh counts + timestamp, then refetch table rows.
      const data = await getProjectJiraSyncStatus(project.id);
      setSyncStatus(data?.status || 'done');
      setLastSyncedAt(data?.last_synced_at || null);
      setSyncCounts(data?.counts || null);
      setSyncing(false);
      fetchRows();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Another caller raced us. Switch to poll mode until they finish.
        setSyncStatus('running');
        startPolling();
        return;
      }
      setError(err?.message || 'sync failed');
      setSyncing(false);
    }
  };

  const handleSort = (colKey) => {
    if (sort === colKey) {
      setOrder(order === 'asc' ? 'desc' : 'asc');
    } else {
      setSort(colKey);
      setOrder('desc');
    }
  };

  const handleRowClick = (row) => {
    navigate(`/projects/${project.id}/tickets/${row.ticket_id}`);
  };

  const syncSummary = useMemo(() => {
    if (syncing || syncStatus === 'running') return 'sync running...';
    if (syncStatus === 'error') return 'last sync failed';
    if (!lastSyncedAt) return 'never synced';
    const counts = syncCounts || {};
    const added = counts.added ?? counts.created ?? 0;
    const updated = counts.updated ?? 0;
    const unchanged = counts.unchanged ?? 0;
    return `synced ${formatSyncTimestamp(lastSyncedAt)} - ${added} added / ${updated} updated / ${unchanged} unchanged`;
  }, [syncing, syncStatus, lastSyncedAt, syncCounts]);

  if (!project) {
    return <div className="empty-state" data-testid="jira-page">Project not found</div>;
  }

  if (!isJiraLinked) {
    return (
      <div className="jira-page" data-testid="jira-page">
        <h1 className="page-title">Jira</h1>
        <div className="empty-state">
          This project is not linked to a Jira project. Enable Jira from the project tools panel.
        </div>
      </div>
    );
  }

  return (
    <div className="jira-page" data-testid="jira-page">
      <div className="jira-page__title-row">
        <h1 className="page-title">
          {project.prefix} Jira - {project.jira_project_key}
        </h1>
        <div className="jira-page__sync">
          <button
            className="sync-btn"
            onClick={handleSync}
            disabled={syncing || syncStatus === 'running'}
            data-testid="jira-sync-button"
          >
            {(syncing || syncStatus === 'running') ? '$ syncing...' : '$ sync'}
          </button>
          <span className="tooltip-trigger" data-testid="jira-sync-info">
            ?
            <span className="tooltip-content">
              Pulls data from Jira into DWB. Read-only - never modifies Jira.
            </span>
          </span>
          <span className="jira-page__sync-summary" data-testid="jira-sync-summary">
            {syncSummary}
          </span>
        </div>
      </div>

      <div className="jira-page__search-row">
        <input
          type="text"
          className="jira-page__search"
          placeholder="search any column (case-insensitive, token-order-agnostic)"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          spellCheck={false}
          data-testid="jira-search-input"
        />
        <span className="jira-page__count">
          {loading ? 'loading...' : `${rows.length} of ${total} rows`}
        </span>
      </div>

      {error && (
        <div className="jira-error" data-testid="jira-error">
          {error}
        </div>
      )}

      {!loading && rows.length === 0 && !error && (
        <div className="empty-state" data-testid="jira-empty-state">
          {debouncedQ
            ? `no rows match "${debouncedQ}"`
            : 'no Jira-linked tickets for this project yet. Run a sync to pull current snapshots.'}
        </div>
      )}

      {rows.length > 0 && (
        <div className="jira-table" role="table" data-testid="jira-table">
          <div className="jira-table__row jira-table__row--header" role="row">
            {COLUMNS.map((col) => {
              const isSorted = sort === col.key;
              const arrow = isSorted ? (order === 'asc' ? ' ^' : ' v') : '';
              return (
                <button
                  type="button"
                  key={col.key}
                  className={`jira-table__cell jira-table__cell--header jira-table__cell--${col.align}${isSorted ? ' jira-table__cell--sorted' : ''}`}
                  onClick={() => handleSort(col.key)}
                  role="columnheader"
                  data-testid={`jira-col-${col.key}`}
                >
                  {col.label}{arrow}
                </button>
              );
            })}
          </div>
          {rows.map((r) => (
            <div
              key={r.ticket_id}
              className="jira-table__row jira-table__row--data"
              role="row"
              onClick={() => handleRowClick(r)}
              data-testid="jira-row"
            >
              <span className="jira-table__cell jira-table__cell--key">{r.dwb_key || DASH}</span>
              <span className="jira-table__cell">{r.dwb_sprint || DASH}</span>
              <span className="jira-table__cell jira-table__cell--status">{r.dwb_status || DASH}</span>
              <span className="jira-table__cell jira-table__cell--key">{r.jira_key || DASH}</span>
              <span className="jira-table__cell">{r.jira_sprint || DASH}</span>
              <span className="jira-table__cell jira-table__cell--status">{r.jira_status || DASH}</span>
              <span className="jira-table__cell">{r.jira_issue_type || DASH}</span>
              <span className="jira-table__cell jira-table__cell--key">{r.jira_parent_key || DASH}</span>
              <span className="jira-table__cell jira-table__cell--key" title={r.jira_epic_name || ''}>{r.jira_epic_key || DASH}</span>
              <span className="jira-table__cell jira-table__cell--assignee">{r.jira_assignee || DASH}</span>
              <span className="jira-table__cell jira-table__cell--right jira-table__cell--date">{formatDateShort(r.created_at)}</span>
              <span className="jira-table__cell jira-table__cell--right jira-table__cell--date">{formatDateShort(r.updated_at)}</span>
              <span className="jira-table__cell jira-table__cell--title" title={r.title || ''}>
                {r.title || DASH}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default JiraIssuesPage;
