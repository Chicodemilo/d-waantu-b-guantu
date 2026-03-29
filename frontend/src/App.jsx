import { Routes, Route } from 'react-router-dom';
import useAppData from './hooks/useAppData';
import AppShell from './components/layout/AppShell';
import DashboardPage from './pages/DashboardPage';
import ProjectPage from './pages/ProjectPage';
import TicketsPage from './pages/TicketsPage';
import TicketDetailPage from './pages/TicketDetailPage';
import SprintPage from './pages/SprintPage';
import EpicPage from './pages/EpicPage';
import AgentPage from './pages/AgentPage';
import ProjectAgentsPage from './pages/ProjectAgentsPage';
import InstructionsPage from './pages/InstructionsPage';
import TestResultsPage from './pages/TestResultsPage';
import ProjectTestsPage from './pages/ProjectTestsPage';

function App() {
  useAppData();

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/projects/:id" element={<ProjectPage />} />
        <Route path="/projects/:id/tickets" element={<TicketsPage />} />
        <Route path="/projects/:id/tickets/:ticketId" element={<TicketDetailPage />} />
        <Route path="/projects/:id/sprints/:sprintId" element={<SprintPage />} />
        <Route path="/projects/:id/epics/:epicId" element={<EpicPage />} />
        <Route path="/projects/:id/agents" element={<ProjectAgentsPage />} />
        <Route path="/projects/:id/tests" element={<ProjectTestsPage />} />
        <Route path="/projects/:id/agents/:agentId" element={<AgentPage />} />
        <Route path="/instructions" element={<InstructionsPage />} />
        <Route path="/tests" element={<TestResultsPage />} />
        <Route path="/tests/:runId" element={<TestResultsPage />} />
      </Routes>
    </AppShell>
  );
}

export default App;
