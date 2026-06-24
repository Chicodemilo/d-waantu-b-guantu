// Path: src/pages/InterAgentCommsPage.jsx
// File: InterAgentCommsPage.jsx
// Created: 2026-06-24
// Purpose: Project-level Inter-Agent Comms glance view (DWB-451). Dense, newest-first log of captured inter-agent messages: from -> to, timestamp, and a body truncated to a single line. Inline-text-confirm Clear wipes the project's rows. Polls the GET list endpoint every 3s. Backend: Barry DWB-447/448.
// Caller: App.jsx (route: /projects/:id/comms)
// Callees: react (useState, useEffect, useRef), react-router-dom (useParams), api/agentMessages (getAgentMessages, clearAgentMessages), ../styles/agent-comms.css
// Data In: Route param (id)
// Data Out: Default export InterAgentCommsPage component
// Last Modified: 2026-06-24

import { useState, useEffect, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { getAgentMessages, clearAgentMessages } from '../api/agentMessages';
import '../styles/agent-comms.css';

const POLL_MS = 3000;
const PAGE_LIMIT = 50;

function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function InterAgentCommsPage() {
  const { id } = useParams();
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);
  const timerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    const poll = () => {
      getAgentMessages(id, { limit: PAGE_LIMIT, offset: 0 })
        .then((data) => {
          if (cancelled) return;
          const list = (data && Array.isArray(data.rows)) ? data.rows : [];
          setRows(list);
          setTotal(data && typeof data.total === 'number' ? data.total : list.length);
          setErrored(false);
        })
        .catch(() => {
          if (!cancelled) setErrored(true);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    };

    poll();
    timerRef.current = setInterval(poll, POLL_MS);

    return () => {
      cancelled = true;
      clearInterval(timerRef.current);
    };
  }, [id]);

  const handleClear = async () => {
    setClearing(true);
    try {
      await clearAgentMessages(id);
      setRows([]);
      setTotal(0);
      setConfirmClear(false);
    } catch {
      // next poll tick will refresh from the server
    } finally {
      setClearing(false);
    }
  };

  return (
    <div>
      <div className="agent-comms__head">
        <span className="agent-comms__title">Inter-Agent Comms</span>
        {total > 0 && <span className="agent-comms__count">{total} message{total !== 1 ? 's' : ''}</span>}
        {rows.length > 0 && (
          <span className="agent-comms__clear">
            {!confirmClear ? (
              <button
                className="agent-comms__clear-link"
                onClick={() => setConfirmClear(true)}
              >
                clear
              </button>
            ) : (
              <span className="agent-comms__confirm">
                confirm?{' '}
                <button
                  className="agent-comms__confirm-yes"
                  onClick={handleClear}
                  disabled={clearing}
                >
                  {clearing ? 'clearing...' : 'yes'}
                </button>
                {' / '}
                <button
                  className="agent-comms__confirm-cancel"
                  onClick={() => setConfirmClear(false)}
                  disabled={clearing}
                >
                  cancel
                </button>
              </span>
            )}
          </span>
        )}
      </div>

      {loading ? (
        <div className="agent-comms__empty">Loading...</div>
      ) : errored && rows.length === 0 ? (
        <div className="agent-comms__empty">Comms log unavailable.</div>
      ) : rows.length === 0 ? (
        <div className="agent-comms__empty">No inter-agent messages captured yet.</div>
      ) : (
        <div className="agent-comms">
          <div className="agent-comms__header">
            <span>From -&gt; To</span>
            <span>Time</span>
            <span>Message</span>
          </div>
          <div className="agent-comms__scroll">
            {rows.map((m) => (
              <div key={m.id} className="agent-comms__row">
                <span className="agent-comms__pair">
                  <span className="agent-comms__from">{m.from_agent_name || `#${m.from_agent_id ?? '?'}`}</span>
                  <span className="agent-comms__arrow">-&gt;</span>
                  <span className="agent-comms__to">{m.to_agent_name || `#${m.to_agent_id ?? '?'}`}</span>
                </span>
                <span className="agent-comms__created">{formatTime(m.created_at)}</span>
                <span className="agent-comms__body" title={m.body || m.summary || ''}>
                  {m.summary || m.body || ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default InterAgentCommsPage;
