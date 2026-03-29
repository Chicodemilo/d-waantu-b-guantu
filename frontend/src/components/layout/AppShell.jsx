// Path: src/components/layout/AppShell.jsx
// File: AppShell.jsx
// Created: 2026-03-29
// Purpose: Top-level layout shell that composes Sidebar, Header, main content area, and Footer
// Caller: App.jsx
// Callees: Sidebar, Header, Footer, layout.css
// Data In: children (React children rendered in main content area)
// Data Out: default export AppShell component
// Last Modified: 2026-03-29

import Sidebar from './Sidebar';
import Header from './Header';
import Footer from './Footer';
import '../../styles/layout.css';

function AppShell({ children }) {
  return (
    <div className="app-shell">
      <Sidebar />
      <Header />
      <main className="main-content">{children}</main>
      <Footer />
    </div>
  );
}

export default AppShell;
