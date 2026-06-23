// Path: src/pages/ArchieChannelPage.jsx
// File: ArchieChannelPage.jsx
// Created: 2026-06-23
// Purpose: Cross-project team-lead (Archie) messaging channel view (DWB-440). Read-only table of DIRECT and BROADCAST messages between team-lead agents across every project. Polls the GET list endpoint every 3s. Sending happens via slash command / API (archie-only), not here. Backend: Barry DWB-436/437/438.
// Caller: App.jsx (route: /archie-channel, global nav)
// Callees: react (useState, useEffect, useRef), api/tlChannel (getTLChannel), ../styles/tl-channel.css
// Data In: None (global page)
// Data Out: Default export ArchieChannelPage component
// Last Modified: 2026-06-23

import { useState, useEffect, useRef } from 'react';
import { getTLChannel } from '../api/tlChannel';
import '../styles/tl-channel.css';

const POLL_MS = 3000;

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

// Single binding point for the frozen GET /api/tl-channel contract (DWB-437,
// canonical shape per Archie's decision + Barry's 2026-06-23 correction). Every
// field the table reads is resolved here so the rest of the component never
// touches a raw API key. If the backend shape changes, rebind ONLY this function.
//
// Per-message shape (array, most-recent-first; GET list takes ?limit only, no
// viewer param):
//   id, from_agent_id, from_agent_name, from_project_id, from_project_prefix,
//   to_agent_id (null => broadcast), to_agent_name (null when broadcast),
//   is_broadcast (true exactly when to_agent_id is null), body,
//   created_at (ISO string),
//   read_by: [{agent_id, agent_name, read_at}]  (empty [] => nobody has read it).
//
// Read-state shows the reader names from read_by (the ticket asks for "who has
// read it"); an empty list renders "unread".
function normalizeMessage(raw) {
  const r = raw || {};
  const isBroadcast = r.is_broadcast === true || r.to_agent_id == null;

  const readers = (Array.isArray(r.read_by) ? r.read_by : []).map((x) => {
    const o = x || {};
    return {
      name: o.agent_name || o.name || `agent #${o.agent_id ?? '?'}`,
      at: o.read_at || null,
    };
  });

  return {
    id: r.id,
    body: r.body || '',
    created_at: r.created_at || null,
    from: { name: r.from_agent_name || 'unknown', project: r.from_project_prefix || '' },
    isBroadcast,
    to: isBroadcast ? null : { name: r.to_agent_name || 'unknown' },
    readers,
  };
}

function ReadState({ readers }) {
  if (!readers || readers.length === 0) {
    return <span className="tl-channel__unread">unread</span>;
  }
  return (
    <span className="tl-channel__readers">
      {readers.map((rd, i) => (
        <span key={i} className="tl-channel__reader" title={rd.at ? formatTime(rd.at) : ''}>
          {rd.name}
        </span>
      ))}
    </span>
  );
}

function ArchieChannelPage() {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);
  const timerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    const poll = () => {
      getTLChannel()
        .then((data) => {
          if (cancelled) return;
          const rows = Array.isArray(data) ? data : (data && data.messages) || [];
          setMessages(rows.map(normalizeMessage));
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
  }, []);

  return (
    <div>
      <div className="page-title">Archie Channel</div>
      <p className="tl-channel__subtitle">
        Cross-project team-lead messaging. Read-only. Messages are sent by archies via slash command or API.
      </p>

      {loading ? (
        <div className="tl-channel__empty">Loading channel...</div>
      ) : errored && messages.length === 0 ? (
        <div className="tl-channel__empty">Channel unavailable.</div>
      ) : messages.length === 0 ? (
        <div className="tl-channel__empty">No messages yet.</div>
      ) : (
        <div className="tl-channel">
          <div className="tl-channel__header">
            <span className="tl-channel__col-from">From</span>
            <span className="tl-channel__col-to">To</span>
            <span className="tl-channel__col-body">Body</span>
            <span className="tl-channel__col-created">Created</span>
            <span className="tl-channel__col-read">Read</span>
          </div>
          <div className="tl-channel__scroll">
            {messages.map((m) => (
              <div
                key={m.id}
                className={`tl-channel__row${m.isBroadcast ? ' tl-channel__row--broadcast' : ' tl-channel__row--direct'}`}
              >
                <span className="tl-channel__col-from">
                  <span className="tl-channel__sender">{m.from.name}</span>
                  {m.from.project && (
                    <span className="tl-channel__project">{m.from.project}</span>
                  )}
                </span>
                <span className="tl-channel__col-to">
                  {m.isBroadcast ? (
                    <span className="tl-channel__broadcast-tag">ALL</span>
                  ) : (
                    <span className="tl-channel__recipient">{m.to.name}</span>
                  )}
                </span>
                <span className="tl-channel__col-body">{m.body}</span>
                <span className="tl-channel__col-created">{formatTime(m.created_at)}</span>
                <span className="tl-channel__col-read">
                  <ReadState readers={m.readers} />
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default ArchieChannelPage;
