// Path: src/components/layout/AppShell.jsx
// File: AppShell.jsx
// Created: 2026-03-29
// Purpose: Top-level layout shell that composes Sidebar, Header, main content area (wrapped in an ErrorBoundary so a render-time throw in any page renders the fallback rather than blanking the whole app - DWB-370), and SessionFooter (single persistent footer row: session state on the left, polling status on the right). The old standalone Footer was merged into SessionFooter as of DWB-349.
// Caller: App.jsx
// Callees: react (useState, useCallback), Sidebar, Header, SessionFooter, ErrorBoundary, layout.css
// Data In: children (React children rendered in main content area)
// Data Out: default export AppShell component
// Last Modified: 2026-06-10

import { useState, useCallback } from 'react';
import Sidebar from './Sidebar';
import Header from './Header';
import SessionFooter from './SessionFooter';
import ErrorBoundary from '../common/ErrorBoundary';
import '../../styles/layout.css';

function AppShell({ children }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const toggleSidebar = useCallback(() => setSidebarOpen((v) => !v), []);
  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  return (
    <div className="app-shell">
      {sidebarOpen && <div className="sidebar-overlay" onClick={closeSidebar} />}
      <Sidebar open={sidebarOpen} onNavClick={closeSidebar} />
      <Header onMenuClick={toggleSidebar} />
      <main className="main-content">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
      <SessionFooter />
    </div>
  );
}

export default AppShell;
