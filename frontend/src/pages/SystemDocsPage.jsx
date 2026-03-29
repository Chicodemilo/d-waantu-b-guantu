// Path: src/pages/SystemDocsPage.jsx
// File: SystemDocsPage.jsx
// Created: 2026-03-29
// Purpose: Wrapper that finds the DWB system project and renders DocsPage for it
// Caller: App.jsx (route: /docs)
// Callees: useStore, DocsPage
// Data In: projects from store
// Data Out: Default export SystemDocsPage component
// Last Modified: 2026-03-29

import useStore from '../store/useStore';
import DocsPage from './DocsPage';

function SystemDocsPage() {
  const projects = useStore((s) => s.projects);
  const dwb = projects.find((p) => p.prefix === 'DWB');

  if (!dwb) {
    return <div className="empty-state">System project (DWB) not found</div>;
  }

  return <DocsPage systemProjectId={dwb.id} />;
}

export default SystemDocsPage;
