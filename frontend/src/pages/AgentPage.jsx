import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import AgentDetail from '../components/agents/AgentDetail';
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
        <Link to={`/projects/${id}/agents`}>&larr; Back to agents</Link>
      </div>
      <AgentDetail agentId={agentId} />
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
