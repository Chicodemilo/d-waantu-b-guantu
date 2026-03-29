// Path: src/components/layout/AppShell.jsx
// File: AppShell.jsx
// Created: 2026-03-29
// Purpose: Top-level layout shell that composes Sidebar, Header, main content area, and Footer with mobile sidebar toggle
// Caller: App.jsx
// Callees: react (useState, useCallback), Sidebar, Header, Footer, layout.css
// Data In: children (React children rendered in main content area)
// Data Out: default export AppShell component
// Last Modified: 2026-03-29

import { useState, useCallback } from 'react';
import Sidebar from './Sidebar';
import Header from './Header';
import Footer from './Footer';
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
      <main className="main-content">{children}</main>
      <Footer />
    </div>
  );
}

export default AppShell;
