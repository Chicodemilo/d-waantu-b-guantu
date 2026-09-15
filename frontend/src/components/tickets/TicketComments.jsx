// Path: src/components/tickets/TicketComments.jsx
// File: TicketComments.jsx
// Created: 2026-03-29
// Purpose: Displays a list of comments for a ticket with agent names and timestamps
// Caller: TicketDetail.jsx
// Callees: useStore, utils/format (formatApiDateTime)
// Data In: ticketId prop
// Data Out: default export TicketComments component
// Last Modified: 2026-09-15 (DWB-557: shared timestamp parsing)

import useStore from '../../store/useStore';
import { formatApiDateTime } from '../../utils/format';

function TicketComments({ ticketId }) {
  const comments = useStore((s) => s.getCommentsByTicket(ticketId));
  const agents = useStore((s) => s.agents);

  const getAgentName = (agentId) => {
    const agent = agents.find((a) => a.id === agentId);
    return agent ? agent.name : 'unknown';
  };

  const formatTime = (iso) => {
    return formatApiDateTime(iso);
  };

  return (
    <div className="ticket-comments">
      <div className="ticket-comments__title">
        Comments ({comments.length})
      </div>
      {comments.length === 0 && (
        <div className="empty-state">No comments yet</div>
      )}
      {comments.map((c) => (
        <div key={c.id} className="comment">
          <div className="comment__header">
            <span className="comment__author">{getAgentName(c.author_agent_id)}</span>
            <span className="comment__time">{formatTime(c.created_at)}</span>
          </div>
          <div className="comment__body">{c.body}</div>
        </div>
      ))}
    </div>
  );
}

export default TicketComments;
