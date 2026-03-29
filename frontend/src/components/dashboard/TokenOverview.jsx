import useStore from '../../store/useStore';
import { ROLES } from '../../config';
import AsciiChart from '../common/AsciiChart';
import '../../styles/dashboard.css';

function TokenOverview() {
  const projects = useStore((s) => s.projects).filter((p) => p.status === 'active');
  const tickets = useStore((s) => s.tickets);
  const agents = useStore((s) => s.agents);
  const projectAgents = useStore((s) => s.projectAgents);

  // Token breakdown by project
  const projectData = projects.map((p) => {
    const projectTickets = tickets.filter((t) => t.project_id === p.id);
    const ticketTokens = projectTickets.reduce((sum, t) => sum + t.tokens_used, 0);
    const total = ticketTokens + p.tl_overhead_tokens + p.pm_overhead_tokens;
    return {
      label: p.prefix,
      value: total,
      displayValue: `${(total / 1000).toFixed(1)}k`,
    };
  });

  // Token breakdown by agent (exclude TL/PM — they're in Overhead, and only active projects)
  const activeProjectIds = new Set(projects.map((p) => p.id));
  const activeAgentIds = new Set(
    projectAgents.filter((pa) => activeProjectIds.has(pa.project_id)).map((pa) => pa.agent_id)
  );
  const workerAgents = agents.filter(
    (a) => a.role !== ROLES.TEAM_LEAD && a.role !== ROLES.PM && activeAgentIds.has(a.id)
  );
  const agentData = workerAgents.map((a) => {
    const agentTickets = tickets.filter((t) => t.assigned_agent_id === a.id);
    const total = agentTickets.reduce((sum, t) => sum + t.tokens_used, 0);
    const pa = projectAgents?.find((r) => r.agent_id === a.id);
    const project = pa ? projects.find((p) => p.id === pa.project_id) : null;
    const label = `${a.name}/${a.role}`;
    return {
      label,
      value: total,
      displayValue: `${(total / 1000).toFixed(1)}k`,
    };
  });

  // Overhead breakdown — look up actual TL and PM agents per project
  const findAgent = (projectId, role) => {
    const pa = projectAgents.find((r) => {
      if (r.project_id !== projectId) return false;
      const a = agents.find((ag) => ag.id === r.agent_id);
      return a && a.role === role;
    });
    return pa ? agents.find((a) => a.id === pa.agent_id) : null;
  };

  const overheadData = projects.flatMap((p) => {
    const tl = findAgent(p.id, ROLES.TEAM_LEAD);
    const pm = findAgent(p.id, ROLES.PM);
    return [
      {
        label: tl ? `${tl.name}/${tl.role}` : `${p.prefix} TL`,
        value: p.tl_overhead_tokens,
        displayValue: `${(p.tl_overhead_tokens / 1000).toFixed(1)}k`,
      },
      {
        label: pm ? `${pm.name}/${pm.role}` : `${p.prefix} PM`,
        value: p.pm_overhead_tokens,
        displayValue: `${(p.pm_overhead_tokens / 1000).toFixed(1)}k`,
      },
    ];
  });

  return (
    <div className="token-overview">
      <AsciiChart title="Tokens by Project" tooltip="Total tokens for all agents on the project — includes team lead, PM, and worker agents." data={projectData} colorClass="orange" />
      <AsciiChart title="Tokens by Agent" tooltip="Tokens consumed by each agent across their assigned tickets." data={agentData} colorClass="blue" />
      <AsciiChart title="Overhead Tokens" tooltip="Tokens spent by the Team Lead (TL) and Project Manager (PM) on coordination — not tied to specific tickets. Tracked separately per project." data={overheadData} />
    </div>
  );
}

export default TokenOverview;
