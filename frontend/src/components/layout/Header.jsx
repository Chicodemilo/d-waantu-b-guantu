// Path: src/components/layout/Header.jsx
// File: Header.jsx
// Created: 2026-03-29
// Purpose: Renders the top header bar with hamburger menu button, dynamic page title, and surfaced-alert badge (DWB-464)
// Caller: AppShell.jsx
// Callees: react-router-dom (useLocation, Link), useStore
// Data In: location pathname, alerts and projects from store, onMenuClick callback
// Data Out: default export Header component
// Last Modified: 2026-06-24

import { useLocation, Link } from 'react-router-dom';
import useStore from '../../store/useStore';

function Header({ onMenuClick }) {
  const location = useLocation();
  // DWB-464: badge counts only surfaced-category open alerts.
  const openAlerts = useStore((s) => s.getSurfacedAlerts());
  const projects = useStore((s) => s.projects);

  const getProjectFromPath = () => {
    const match = location.pathname.match(/\/projects\/(\d+)/);
    if (!match) return null;
    return projects.find((p) => p.id === Number(match[1]));
  };

  const getTitle = () => {
    const path = location.pathname;
    if (path === '/') return 'Dashboard';
    if (path === '/docs') return 'System Docs';
    if (path === '/instructions') return 'Instructions';
    if (path.match(/\/tests\/\d+/)) return 'System Test Run';
    if (path === '/tests') return 'System Tests';
    if (path.includes('/tickets/')) return 'Ticket Detail';
    if (path.includes('/tickets')) return 'Tickets';
    if (path.includes('/sprints/')) return 'Sprint Detail';
    if (path.includes('/epics/')) return 'Epic Detail';
    if (path.includes('/docs')) return 'Docs';
    if (path.match(/\/projects\/\d+\/agents\/\d+/)) return 'Agent Detail';
    if (path.match(/\/projects\/\d+\/agents$/)) return 'Team';
    if (path.includes('/projects/')) return 'Project Overview';
    return "D'Waantu B'Guantu";
  };

  const project = getProjectFromPath();

  return (
    <header className="header">
      <div className="header__left">
        <button className="header__hamburger" onClick={onMenuClick} aria-label="Toggle menu">
          {'\u2261'}
        </button>
        {project ? (
          <span className="header__title">
            <span className="header__title-label">Project Overview</span>
            {' '}
            <span className="header__title-prefix">{project.prefix} /</span>
            {' '}
            <span className="header__title-name">{project.name}</span>
          </span>
        ) : (
          <span className="header__title">{getTitle()}</span>
        )}
      </div>
      {openAlerts.length > 0 && (
        <Link to="/" className="header__alerts">
          alerts
          <span className="header__alert-badge">{openAlerts.length}</span>
        </Link>
      )}
    </header>
  );
}

export default Header;
