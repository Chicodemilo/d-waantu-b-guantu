// Path: src/pages/AgentPage.jsx
// File: AgentPage.jsx
// Created: 2026-03-29
// Purpose: Displays agent detail view with applicable instructions (global, project, agent scoped) and the per-agent score ledger (DWB-428)
// Caller: App.jsx (route: /projects/:id/agents/:agentId)
// Callees: react-router-dom, ../store/useStore, ../components/agents/AgentDetail, ../components/agents/AgentScoreLedger, ../components/instructions/InstructionView
// Data In: Route params (id, agentId), instructions from Zustand store
// Data Out: Default export AgentPage component
// Last Modified: 2026-06-22

import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import AgentDetail from '../components/agents/AgentDetail';
import AgentScoreLedger from '../components/agents/AgentScoreLedger';
import InstructionView from '../components/instructions/InstructionView';

function AgentPage() {
  const { id, agentId } = useParams();
  const instructions = useStore((s) => s.instructions);

  const projectId = Number(id);
  const agentIdNum = Number(agentId);

  const applicable = instructions.filter((i) => {
    if (i.scope === 'global') return true;
    if (i.scope === 'project' && i.project_id === projectId) return true;
    if (i.scope === 'agent' && i.agent_id === agentIdNum) return true;
    return false;
  });

  return (
    <div>
      <div className="page-title">
        <Link to={`/projects/${id}/agents`}>&larr; Back to team</Link>
      </div>
      <AgentDetail agentId={agentId} />
      <AgentScoreLedger agentId={agentIdNum} projectId={projectId} />
      {applicable.length > 0 && (
        <div>
          <div className="page-title" style={{ marginTop: '24px' }}>Instructions</div>
          {applicable.map((inst) => (
            <InstructionView key={inst.id} instruction={inst} />
          ))}
        </div>
      )}
    </div>
  );
}

export default AgentPage;
