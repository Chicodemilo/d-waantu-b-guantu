import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import StatusBadge from '../common/StatusBadge';
import AgentMetrics from './AgentMetrics';
import '../../styles/agents.css';
import '../../styles/tickets.css';

function AgentDetail({ agentId }) {
  const agent = useStore((s) => s.getAgent(agentId));
  const tickets = useStore((s) => s.getTicketsByAgent(agentId));

  if (!agent) return <div className="empty-state">Agent not found</div>;

  return (
    <div className="agent-detail">
      <div className="agent-detail__header">
        <div className="agent-detail__name">{agent.name}</div>
        <div className="agent-detail__role">{agent.role.replace(/_/g, ' ')}</div>
        <div className="agent-detail__desc">{agent.description}</div>
      </div>

      <div className="agent-detail__section">
        <div className="agent-detail__section-title">Metrics</div>
        <AgentMetrics agentId={agentId} />
      </div>

      <div className="agent-detail__section">
        <div className="agent-detail__section-title">
          Assigned Tickets ({tickets.length})
        </div>
        <div className="ticket-list">
          {tickets.map((ticket) => (
            <Link
              key={ticket.id}
              to={`/projects/${ticket.project_id}/tickets/${ticket.id}`}
              className="ticket-row"
            >
              <span className="ticket-row__key">{ticket.ticket_key}</span>
              <span className="ticket-row__title">{ticket.title}</span>
              <StatusBadge status={ticket.status} />
              <span className="ticket-row__type">{ticket.ticket_type}</span>
              <span className="ticket-row__agent">
                {ticket.tokens_used.toLocaleString()} tok
              </span>
            </Link>
          ))}
          {tickets.length === 0 && (
            <div className="empty-state">No tickets assigned</div>
          )}
        </div>
      </div>
    </div>
  );
}

export default AgentDetail;
