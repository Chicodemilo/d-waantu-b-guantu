import { useParams, Link } from 'react-router-dom';
import SprintDetail from '../components/sprints/SprintDetail';
import SprintVelocity from '../components/sprints/SprintVelocity';

function SprintPage() {
  const { id, sprintId } = useParams();

  return (
    <div>
      <div className="page-title">
        <Link to={`/projects/${id}`}>&larr; Back to project</Link>
      </div>
      <SprintDetail sprintId={sprintId} projectId={id} />
      <hr className="section-divider" />
      <SprintVelocity projectId={id} />
    </div>
  );
}

export default SprintPage;
