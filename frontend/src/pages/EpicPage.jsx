// Path: src/pages/EpicPage.jsx
// File: EpicPage.jsx
// Created: 2026-03-29
// Purpose: Displays epic detail view with back-navigation to the parent project
// Caller: App.jsx (route: /projects/:id/epics/:epicId)
// Callees: react-router-dom, ../components/epics/EpicDetail
// Data In: Route params (id, epicId)
// Data Out: Default export EpicPage component
// Last Modified: 2026-03-29

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
