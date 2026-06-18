// Path: src/components/common/SessionInfoLine.jsx
// File: SessionInfoLine.jsx
// Created: 2026-06-12
// Purpose: Single-line current-session summary rendered in two density variants. "header" variant is used by ProjectHeader and produces a label/value pair (matches the surrounding "status:" / "epic:" / "sprint:" row pattern). "card" variant is used by ProjectCard and produces one compact span (id + [OPEN]/[CLOSED] + duration). Live duration ticks at 10s when the session is open; the same tick also pings sessionsCache.ensureSessionsFetch so values stay fresh past the 60s TTL without a separate polling driver.
// Caller: ProjectHeader.jsx, ProjectCard.jsx
// Callees: react (useEffect, useState), utils/format (formatTime, formatTokens), services/sessionsCache (ensureSessionsFetch)
// Data In: session object from useCurrentSession; variant 'header' | 'card'; optional projectId for the live-tick refresh ping
// Data Out: header variant renders a label fragment + value span; card variant renders one span
// Last Modified: 2026-06-12

import { useEffect, useState } from 'react';
import { formatTime, formatTokens } from '../../utils/format';
import { ensureSessionsFetch } from '../../services/sessionsCache';

function hhmm(iso) {
  if (!iso) return '';
  const ts = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return '';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function liveDurationSeconds(session) {
  if (!session) return 0;
  const isOpen = session.status === 'open' || session.closed_at == null;
  if (!isOpen) return session.total_time_seconds || 0;
  if (!session.opened_at) return 0;
  const ts = session.opened_at.endsWith('Z') || session.opened_at.includes('+')
    ? session.opened_at
    : session.opened_at + 'Z';
  return Math.max(0, Math.floor((Date.now() - new Date(ts).getTime()) / 1000));
}

function SessionInfoLine({ session, variant, projectId }) {
  const [, setTick] = useState(0);
  const isOpen = !!session && (session.status === 'open' || session.closed_at == null);

  useEffect(() => {
    if (!isOpen) return undefined;
    const id = setInterval(() => {
      setTick((t) => t + 1);
      if (projectId != null) {
        ensureSessionsFetch(projectId).catch(() => {});
      }
    }, 10_000);
    return () => clearInterval(id);
  }, [isOpen, projectId]);

  if (!session) {
    if (variant === 'card') {
      return <span className="session-info session-info--card session-info--none">session: none</span>;
    }
    return (
      <>
        <span className="project-header__meta-label">session:</span>
        <span className="project-header__meta-value project-header__meta-value--dim">none</span>
      </>
    );
  }

  const duration = liveDurationSeconds(session);
  const durationLabel = duration > 0 ? formatTime(duration) : '0s';
  const tokensLabel = formatTokens(session.total_tokens || 0);
  const stateBadge = isOpen ? '[OPEN]' : '[CLOSED]';

  if (variant === 'card') {
    return (
      <span className="session-info session-info--card">
        session #{session.id} {stateBadge} {durationLabel}
      </span>
    );
  }

  const stateLabel = isOpen
    ? `open since ${hhmm(session.opened_at)}`
    : `closed at ${hhmm(session.closed_at)}`;

  return (
    <>
      <span className="project-header__meta-label">session:</span>
      <span className="project-header__meta-value">
        #{session.id} {stateLabel} - {tokensLabel} tok - {durationLabel}
      </span>
    </>
  );
}

export default SessionInfoLine;
