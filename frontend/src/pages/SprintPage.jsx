// Path: src/pages/SprintPage.jsx
// File: SprintPage.jsx
// Created: 2026-03-29
// Purpose: Displays sprint detail view with velocity chart and back-navigation to the parent project
// Caller: App.jsx (route: /projects/:id/sprints/:sprintId)
// Callees: react-router-dom, ../components/sprints/SprintDetail, ../components/sprints/SprintVelocity
// Data In: Route params (id, sprintId)
// Data Out: Default export SprintPage component
// Last Modified: 2026-03-29

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
