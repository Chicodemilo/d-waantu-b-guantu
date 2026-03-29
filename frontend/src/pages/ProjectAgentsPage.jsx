import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import StatusBadge from '../components/common/StatusBadge';

function ProjectAgentsPage() {
  const { id } = useParams();
  const project = useStore((s) => s.getProject(id));
  const agents = useStore((s) => s.getAgentsByProject(id));

  return (
    <div>
      <div className="page-title">
        <Link to={`/projects/${id}`}>&larr; Back to project</Link>
        <span>{project ? `${project.prefix} Agents` : 'Agents'}</span>
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Role</th>
            <th>Description</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((agent) => (
            <tr key={agent.id} className="data-table__row--clickable">
              <td>
                <Link to={`/projects/${id}/agents/${agent.id}`}>
                  {agent.name}
                </Link>
              </td>
              <td>{agent.role}</td>
              <td>{agent.description}</td>
              <td>
                <StatusBadge status={agent.is_active ? 'active' : 'inactive'} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {agents.length === 0 && (
        <div className="empty-state">No agents assigned to this project</div>
      )}
    </div>
  );
}

export default ProjectAgentsPage;
