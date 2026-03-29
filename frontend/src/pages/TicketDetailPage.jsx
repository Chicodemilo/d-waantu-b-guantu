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
