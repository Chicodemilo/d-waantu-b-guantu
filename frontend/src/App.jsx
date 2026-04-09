// Path: src/App.jsx
// File: App.jsx
// Created: 2026-03-29
// Purpose: Root application component that initializes data polling and defines all routes
// Caller: main.jsx
// Callees: react-router-dom, hooks/useAppData, components/layout/AppShell, pages/DashboardPage, pages/ProjectPage, pages/TicketsPage, pages/TicketDetailPage, pages/SprintPage, pages/EpicPage, pages/AgentPage, pages/ProjectAgentsPage, pages/InstructionsPage, pages/TestResultsPage, pages/ProjectTestsPage, pages/DocsPage, pages/SystemDocsPage
// Data In: None
// Data Out: Exports App component (renders route tree inside AppShell)
// Last Modified: 2026-03-29

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
import DocsPage from './pages/DocsPage';
import SystemDocsPage from './pages/SystemDocsPage';
import ErrorLogPage from './pages/ErrorLogPage';

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
        <Route path="/projects/:id/docs" element={<DocsPage />} />
        <Route path="/projects/:id/agents/:agentId" element={<AgentPage />} />
        <Route path="/docs" element={<SystemDocsPage />} />
        <Route path="/instructions" element={<InstructionsPage />} />
        <Route path="/tests" element={<TestResultsPage />} />
        <Route path="/tests/:runId" element={<TestResultsPage />} />
        <Route path="/errors" element={<ErrorLogPage />} />
      </Routes>
    </AppShell>
  );
}

export default App;
