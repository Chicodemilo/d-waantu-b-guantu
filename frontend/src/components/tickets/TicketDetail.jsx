// Path: src/components/tickets/TicketDetail.jsx
// File: TicketDetail.jsx
// Created: 2026-03-29
// Purpose: Full ticket detail view with metadata, description, stats, status history, and comments
// Caller: TicketDetailPage.jsx
// Callees: react (useState, useEffect), useStore, StatusBadge, TicketComments, api/tickets (getTicketHistory), tickets.css
// Data In: ticketId prop
// Data Out: default export TicketDetail component
// Last Modified: 2026-03-29

import { useState, useEffect } from 'react';
import useStore from '../../store/useStore';
import { formatTime } from '../../utils/format';
import StatusBadge from '../common/StatusBadge';
import TicketComments from './TicketComments';
import { getTicketHistory, updateTicket } from '../../api/tickets';
import '../../styles/tickets.css';

function StatusHistory({ ticketId }) {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getTicketHistory(ticketId)
      .then((data) => {
        if (!cancelled) setHistory(data);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [ticketId]);

  if (loading) return null;
  if (history.length === 0) return null;

  return (
    <div className="status-history">
      <div className="status-history__title">Status History</div>
      <div className="status-history__list">
        {history.map((entry, i) => {
          const ts = new Date(entry.changed_at || entry.created_at);
          const time = ts.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
          });
          return (
            <div key={i} className="status-history__entry">
              <span className="status-history__time">{time}</span>
              <span className="status-history__transition">
                {entry.from_status && (
                  <><span className="status-history__from">{entry.from_status}</span> &rarr; </>
                )}
                <span className="status-history__to">{entry.to_status}</span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function JiraLink({ ticket }) {
  const project = useStore((s) => s.getProject(ticket.project_id));
  const jiraBaseUrl = project?.jira_base_url || 'https://roadvantage.atlassian.net';
  const [editing, setEditing] = useState(false);
  const [keyInput, setKeyInput] = useState('');
  const [saving, setSaving] = useState(false);

  const handleLink = async () => {
    if (!keyInput.trim()) return;
    setSaving(true);
    try {
      await updateTicket(ticket.id, { jira_issue_key: keyInput.trim().toUpperCase() });
      setEditing(false);
      setKeyInput('');
    } catch {
      // next poll will refresh
    } finally {
      setSaving(false);
    }
  };

  const handleUnlink = async () => {
    setSaving(true);
    try {
      await updateTicket(ticket.id, { jira_issue_key: null });
    } catch {
      // next poll will refresh
    } finally {
      setSaving(false);
    }
  };

  if (ticket.jira_issue_key) {
    return (
      <div className="jira-link">
        <a
          className="jira-link__key"
          href={`${jiraBaseUrl}/browse/${ticket.jira_issue_key}`}
          target="_blank"
          rel="noopener noreferrer"
        >{ticket.jira_issue_key}</a>
        <button
          className="jira-link__unlink"
          onClick={handleUnlink}
          disabled={saving}
        >
          {saving ? 'unlinking...' : '[unlink]'}
        </button>
      </div>
    );
  }

  if (editing) {
    return (
      <div className="jira-link">
        <input
          type="text"
          className="jira-key-input"
          placeholder="POR-123"
          value={keyInput}
          onChange={(e) => setKeyInput(e.target.value)}
          maxLength={50}
          autoFocus
        />
        <button
          className="sync-btn"
          onClick={handleLink}
          disabled={saving || !keyInput.trim()}
        >
          {saving ? '$ linking...' : '$ link'}
        </button>
        <button className="sync-btn" onClick={() => { setEditing(false); setKeyInput(''); }}>
          $ cancel
        </button>
      </div>
    );
  }

  return (
    <button
      className="jira-link__unlink"
      onClick={() => setEditing(true)}
    >
      [link jira issue]
    </button>
  );
}

function TicketDetail({ ticketId }) {
  const ticket = useStore((s) => s.getTicket(ticketId));
  const agents = useStore((s) => s.agents);
  const sprints = useStore((s) => s.sprints);
  const epics = useStore((s) => s.epics);

  if (!ticket) return <div className="empty-state">Ticket not found</div>;

  const agent = agents.find((a) => a.id === ticket.assigned_agent_id);
  const sprint = sprints.find((s) => s.id === ticket.sprint_id);
  const epic = epics.find((e) => e.id === ticket.epic_id);

  return (
    <div className="ticket-detail">
      <div className="ticket-detail__header">
        <div className="ticket-detail__key">{ticket.ticket_key}</div>
        <div className="ticket-detail__title">{ticket.title}</div>
        <div className="ticket-detail__meta">
          <div className="ticket-detail__meta-item">
            <span className="ticket-detail__meta-label">Status:</span>
            <StatusBadge status={ticket.status} />
          </div>
          <div className="ticket-detail__meta-item">
            <span className="ticket-detail__meta-label">Type:</span>
            <span className="ticket-detail__meta-value">{ticket.ticket_type}</span>
          </div>
          <div className="ticket-detail__meta-item">
            <span className="ticket-detail__meta-label">Agent:</span>
            <span className="ticket-detail__meta-value">{agent ? `${agent.name}/${agent.role}` : 'unassigned'}</span>
          </div>
          <div className="ticket-detail__meta-item">
            <span className="ticket-detail__meta-label">Sprint:</span>
            <span className="ticket-detail__meta-value">{sprint ? `S${sprint.sprint_number}: ${sprint.name}` : 'none'}</span>
          </div>
          <div className="ticket-detail__meta-item">
            <span className="ticket-detail__meta-label">Epic:</span>
            <span className="ticket-detail__meta-value">{epic?.name || 'none'}</span>
          </div>
          <div className="ticket-detail__meta-item">
            <span className="ticket-detail__meta-label">Jira:</span>
            <JiraLink ticket={ticket} />
          </div>
          <div className="ticket-detail__meta-item">
            <span className="ticket-detail__meta-label">Time:</span>
            <span className="ticket-detail__meta-value">{formatTime(ticket.time_spent_seconds)}</span>
          </div>
        </div>
      </div>

      <div className="ticket-detail__description">{ticket.description}</div>

      <div className="ticket-detail__stats">
        <div className="ticket-detail__stat">
          <div className="ticket-detail__stat-label">Tokens Used</div>
          <div className="ticket-detail__stat-value">
            {ticket.tokens_used.toLocaleString()}
            {ticket.token_source && (
              <span className={`token-source token-source--${ticket.token_source === 'transcript_scan' ? 'scan' : ticket.token_source === 'manual_estimate' ? 'estimate' : 'unknown'}`}>
                {ticket.token_source.replace('_', ' ')}
              </span>
            )}
          </div>
        </div>
        <div className="ticket-detail__stat">
          <div className="ticket-detail__stat-label">Time Spent</div>
          <div className="ticket-detail__stat-value">
            {formatTime(ticket.time_spent_seconds)}
          </div>
        </div>
        <div className="ticket-detail__stat">
          <div className="ticket-detail__stat-label">Created</div>
          <div className="ticket-detail__stat-value">
            {new Date(ticket.created_at).toLocaleDateString()}
          </div>
        </div>
      </div>

      <StatusHistory ticketId={ticketId} />
      <TicketComments ticketId={ticketId} />
    </div>
  );
}

export default TicketDetail;
