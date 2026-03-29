// Path: src/pages/TicketsPage.jsx
// File: TicketsPage.jsx
// Created: 2026-03-29
// Purpose: Displays the full ticket list for a project with project prefix in the title
// Caller: App.jsx (route: /projects/:id/tickets)
// Callees: react-router-dom, ../store/useStore, ../components/tickets/TicketList
// Data In: Route param (id), project from Zustand store
// Data Out: Default export TicketsPage component
// Last Modified: 2026-03-29

import { useParams } from 'react-router-dom';
import useStore from '../store/useStore';
import TicketList from '../components/tickets/TicketList';

function TicketsPage() {
  const { id } = useParams();
  const project = useStore((s) => s.getProject(id));

  return (
    <div>
      <div className="page-title">
        {project ? `${project.prefix} Tickets` : 'Tickets'}
      </div>
      <TicketList projectId={id} />
    </div>
  );
}

export default TicketsPage;
