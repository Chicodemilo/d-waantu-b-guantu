import useStore from '../../store/useStore';
import '../../styles/dashboard.css';

function CrossProjectSummary() {
  const projects = useStore((s) => s.projects).filter((p) => p.status === 'active');
  const tickets = useStore((s) => s.tickets).filter((t) =>
    projects.some((p) => p.id === t.project_id)
  );
  const agents = useStore((s) => s.agents);
  const projectAgents = useStore((s) => s.projectAgents).filter((pa) =>
    projects.some((p) => p.id === pa.project_id)
  );
  const alerts = useStore((s) => s.alerts).filter(
    (a) => a.status === 'open' && projects.some((p) => p.id === a.project_id)
  );

  const activeAgentIds = new Set(projectAgents.map((pa) => pa.agent_id));

  const panels = [
    { label: 'Projects', value: projects.length },
    { label: 'Total Tickets', value: tickets.length },
    { label: 'Completed', value: tickets.filter((t) => t.status === 'done').length, className: '' },
    { label: 'In Progress', value: tickets.filter((t) => t.status === 'in_progress').length, className: 'summary-panel__value--orange' },
    { label: 'Open Alerts', value: alerts.length, className: 'summary-panel__value--blue' },
  ];

  return (
    <div className="cross-project-summary">
      {panels.map((p) => (
        <div key={p.label} className="summary-panel">
          <div className={`summary-panel__value ${p.className || ''}`}>
            {p.value}
          </div>
          <div className="summary-panel__label">{p.label}</div>
        </div>
      ))}
    </div>
  );
}

export default CrossProjectSummary;
