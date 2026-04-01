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

const SEVERITY_COLORS = {
  critical: 'var(--red, #ef4444)',
  warning: 'var(--orange, #fb923c)',
  info: 'var(--blue, #93c5fd)',
};

function Footer() {
  const polling = useStore((s) => s.polling);
  const infraWarnings = useStore((s) => s.infraWarnings);

  const formatTime = (iso) => {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', { hour12: false });
  };

  const worstSeverity = infraWarnings.length > 0
    ? infraWarnings.some(w => w.severity === 'critical') ? 'critical'
      : infraWarnings.some(w => w.severity === 'warning') ? 'warning'
      : 'info'
    : null;

  return (
    <footer className="footer">
      <div className="footer__polling">
        <span
          className={`footer__dot${polling.isActive ? '' : ' footer__dot--idle'}`}
        />
        {polling.isActive ? 'polling' : 'idle'} &middot;{' '}
        {polling.interval / 1000}s interval
      </div>
      {infraWarnings.length > 0 && (
        <div className="footer__infra" title={infraWarnings.map(w => w.message).join('\n')}>
          <span style={{ color: SEVERITY_COLORS[worstSeverity] }}>
            {infraWarnings.length} infra warning{infraWarnings.length !== 1 ? 's' : ''}
          </span>
        </div>
      )}
      <span>last updated: {formatTime(polling.lastUpdated)}</span>
    </footer>
  );
}

export default Footer;
