// Path: src/components/layout/Footer.jsx
// File: Footer.jsx
// Created: 2026-03-29
// Purpose: Displays polling status indicator and last-updated timestamp in the app footer
// Caller: AppShell.jsx
// Callees: useStore (Zustand store)
// Data In: polling state from store (isActive, interval, lastUpdated)
// Data Out: default export Footer component
// Last Modified: 2026-03-29

import useStore from '../../store/useStore';

function Footer() {
  const polling = useStore((s) => s.polling);

  const formatTime = (iso) => {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', { hour12: false });
  };

  return (
    <footer className="footer">
      <div className="footer__polling">
        <span
          className={`footer__dot${polling.isActive ? '' : ' footer__dot--idle'}`}
        />
        {polling.isActive ? 'polling' : 'idle'} &middot;{' '}
        {polling.interval / 1000}s interval
      </div>
      <span>last updated: {formatTime(polling.lastUpdated)}</span>
    </footer>
  );
}

export default Footer;
