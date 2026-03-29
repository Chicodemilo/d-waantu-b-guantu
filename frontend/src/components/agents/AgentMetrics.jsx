import useStore from '../../store/useStore';
import AsciiChart from '../common/AsciiChart';
import '../../styles/agents.css';

function AgentMetrics({ agentId }) {
  const tickets = useStore((s) => s.getTicketsByAgent(agentId));

  const totalTokens = tickets.reduce((sum, t) => sum + t.tokens_used, 0);
  const totalTime = tickets.reduce((sum, t) => sum + t.time_spent_seconds, 0);
  const done = tickets.filter((t) => t.status === 'done').length;

  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    return `${hrs}h ${mins % 60}m`;
  };

  const statusData = [
    { label: 'Done', value: tickets.filter((t) => t.status === 'done').length },
    { label: 'In Progress', value: tickets.filter((t) => t.status === 'in_progress').length },
    { label: 'In Review', value: tickets.filter((t) => t.status === 'in_review').length },
    { label: 'To Do', value: tickets.filter((t) => t.status === 'todo').length },
    { label: 'Backlog', value: tickets.filter((t) => t.status === 'backlog').length },
  ].filter((d) => d.value > 0);

  return (
    <div>
      <div className="agent-metrics">
        <div className="agent-metrics__item">
          <div className="agent-metrics__value">{totalTokens.toLocaleString()}</div>
          <div className="agent-metrics__label">Total Tokens</div>
        </div>
        <div className="agent-metrics__item">
          <div className="agent-metrics__value">{formatTime(totalTime)}</div>
          <div className="agent-metrics__label">Time Spent</div>
        </div>
        <div className="agent-metrics__item">
          <div className="agent-metrics__value">
            {done}/{tickets.length}
          </div>
          <div className="agent-metrics__label">Completed</div>
        </div>
      </div>
      {statusData.length > 0 && (
        <AsciiChart title="Tickets by Status" data={statusData} maxBarWidth={20} />
      )}
    </div>
  );
}

export default AgentMetrics;
