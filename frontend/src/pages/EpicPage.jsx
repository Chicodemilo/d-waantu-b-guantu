import { useParams, Link } from 'react-router-dom';
import EpicDetail from '../components/epics/EpicDetail';

function EpicPage() {
  const { id, epicId } = useParams();

  return (
    <div>
      <div className="page-title">
        <Link to={`/projects/${id}`}>&larr; Back to project</Link>
      </div>
      <EpicDetail epicId={epicId} projectId={id} />
    </div>
  );
}

export default EpicPage;
