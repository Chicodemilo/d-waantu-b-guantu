// Path: src/pages/TicketDetailPage.jsx
// File: TicketDetailPage.jsx
// Created: 2026-03-29
// Purpose: Displays a single ticket's detail view with back-navigation to the tickets list
// Caller: App.jsx (route: /projects/:id/tickets/:ticketId)
// Callees: react-router-dom, ../components/tickets/TicketDetail
// Data In: Route params (id, ticketId)
// Data Out: Default export TicketDetailPage component
// Last Modified: 2026-03-29

import { useParams, Link } from 'react-router-dom';
import TicketDetail from '../components/tickets/TicketDetail';

function TicketDetailPage() {
  const { id, ticketId } = useParams();

  return (
    <div>
      <div className="page-title">
        <Link to={`/projects/${id}/tickets`}>&larr; Back to tickets</Link>
      </div>
      <TicketDetail ticketId={ticketId} />
    </div>
  );
}

export default TicketDetailPage;
