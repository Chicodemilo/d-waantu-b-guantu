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
