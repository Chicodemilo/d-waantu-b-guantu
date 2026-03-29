// Path: src/components/layout/Sidebar.jsx
// File: Sidebar.jsx
// Created: 2026-03-29
// Purpose: Navigation sidebar with links to dashboard, instructions, system tests, and per-project sub-nav
// Caller: AppShell.jsx
// Callees: react (useState), react-router-dom (NavLink, useLocation), useStore
// Data In: projects from store, current location pathname
// Data Out: default export Sidebar component
// Last Modified: 2026-03-29

import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import useStore from '../../store/useStore';

function Sidebar() {
  const projects = useStore((s) => s.projects);
  const [showArchived, setShowArchived] = useState(false);
  const location = useLocation();

  const activeProjects = projects.filter((p) => p.status !== 'archived');
  const archivedProjects = projects.filter((p) => p.status === 'archived');

  const isProjectActive = (projectId) =>
    location.pathname === `/projects/${projectId}` ||
    location.pathname.startsWith(`/projects/${projectId}/`);

  const linkClass = ({ isActive }) =>
    `sidebar__link${isActive ? ' sidebar__link--active' : ''}`;

  const caretLinkClass = (isOpen) => ({ isActive }) => {
    let cls = 'sidebar__link';
    if (isActive) cls += ' sidebar__link--active';
    if (isOpen) cls += ' sidebar__link--caret-open';
    return cls;
  };

  const renderProject = (p, dimmed) => {
    const active = isProjectActive(p.id);
    return (
      <li key={p.id} className={`sidebar__group${dimmed ? ' sidebar__group--archived' : ''}`}>
        <NavLink to={`/projects/${p.id}`} className={caretLinkClass(active)}>
          {p.prefix.toLowerCase()}
        </NavLink>
        {active && (
          <ul className="sidebar__nested">
            <li>
              <NavLink to={`/projects/${p.id}/tickets`} className={linkClass}>
                tickets
              </NavLink>
            </li>
            <li>
              <NavLink to={`/projects/${p.id}/agents`} className={linkClass}>
                agents
              </NavLink>
            </li>
            <li>
              <NavLink to={`/projects/${p.id}/tests`} className={linkClass}>
                tests
              </NavLink>
            </li>
          </ul>
        )}
      </li>
    );
  };

  const isDashboardActive = location.pathname === '/';
  const isInstructionsActive = location.pathname === '/instructions';
  const isSystemTestsActive = location.pathname.startsWith('/tests');

  return (
    <aside className="sidebar">
      <div className="sidebar__logo">
        <span>$</span> D'Waantu B'Guantu
      </div>
      <nav>
        <ul className="sidebar__nav">
          <li className="sidebar__section-label">Overview</li>
          <li>
            <NavLink to="/" className={caretLinkClass(isDashboardActive)} end>
              dashboard
            </NavLink>
          </li>
          <li>
            <NavLink to="/instructions" className={caretLinkClass(isInstructionsActive)}>
              instructions
            </NavLink>
          </li>
          <li className="sidebar__link-with-info">
            <NavLink to="/tests" className={caretLinkClass(isSystemTestsActive)}>
              system_tests
            </NavLink>
            <span className="tooltip-trigger">?<span className="tooltip-content">Tests for the project management system itself, not the projects it tracks.</span></span>
          </li>

          <li className="sidebar__section-label">
            Projects
            {archivedProjects.length > 0 && (
              <button
                className="sidebar__archive-toggle"
                onClick={() => setShowArchived(!showArchived)}
              >
                {showArchived ? '[hide archived]' : '[show archived]'}
              </button>
            )}
          </li>
          {activeProjects.map((p) => renderProject(p, false))}
          {showArchived && archivedProjects.map((p) => renderProject(p, true))}
        </ul>
      </nav>
    </aside>
  );
}

export default Sidebar;
