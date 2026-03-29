import { useState } from 'react';
import useStore from '../../store/useStore';
import '../../styles/common.css';

function InstructionView({ instruction }) {
  const [expanded, setExpanded] = useState(false);
  const projects = useStore((s) => s.projects);
  const agents = useStore((s) => s.agents);

  const scopeLabel = () => {
    switch (instruction.scope) {
      case 'global':
        return 'Global';
      case 'project': {
        const project = projects.find((p) => p.id === instruction.project_id);
        return project ? project.prefix.toLowerCase() : `Project #${instruction.project_id}`;
      }
      case 'agent': {
        const agent = agents.find((a) => a.id === instruction.agent_id);
        const agentProject = agent
          ? projects.find((p) => {
              const pa = useStore.getState().projectAgents;
              return pa?.some((r) => r.agent_id === agent.id && r.project_id === p.id);
            })
          : null;
        const prefix = agentProject ? agentProject.prefix.toLowerCase() : '';
        const agentName = agent ? agent.name : `#${instruction.agent_id}`;
        return prefix ? `${prefix}/${agentName}` : agentName;
      }
      default:
        return instruction.scope;
    }
  };

  return (
    <div className="instruction-card">
      <div className="instruction-card__header" onClick={() => setExpanded(!expanded)}>
        <span className={`instruction-card__caret${expanded ? ' instruction-card__caret--open' : ''}`}>&gt;</span>
        <span className="instruction-card__title">{instruction.title}</span>
        <span className="instruction-card__scope">{scopeLabel()}</span>
      </div>
      {expanded && (
        <div className="instruction-card__body">{instruction.body}</div>
      )}
    </div>
  );
}

export default InstructionView;
