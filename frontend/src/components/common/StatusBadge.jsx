// Path: src/components/common/StatusBadge.jsx
// File: StatusBadge.jsx
// Created: 2026-03-29
// Purpose: Renders a styled status label badge with CSS class based on status value
// Caller: ProjectCard.jsx, ProjectHeader.jsx, TicketList.jsx, TicketDetail.jsx, AgentDetail.jsx, EpicDetail.jsx, EpicList.jsx, SprintDetail.jsx, SprintProgress.jsx, ProjectAgentsPage.jsx, ProjectTestsPage.jsx, TestResultsPage.jsx
// Callees: common.css
// Data In: props { status } (string status value like "active", "done", "in_progress")
// Data Out: default export StatusBadge component
// Last Modified: 2026-03-29

import '../../styles/common.css';

function StatusBadge({ status }) {
  const label = status.replace(/_/g, ' ');

  return (
    <span className={`status-badge status-badge--${status}`}>{label}</span>
  );
}

export default StatusBadge;
