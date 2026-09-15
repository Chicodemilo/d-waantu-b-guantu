// Path: src/components/nodes/RescanControl.jsx
// File: RescanControl.jsx
// Created: 2026-09-15
// Purpose: The one rescan control (DWB-556). Renders the rescan trigger and its inline-text confirm ("rescan? yes / cancel") in place, so both call sites, the nodes page head (DWB-551) and the exclusions modal (DWB-552), share one behaviour rather than implementing it twice. A rescan rewrites the whole index and holds for roughly 141 seconds, so it confirms first. Deliberately not a modal: it is the project's standing confirm pattern, and inside the exclusions modal a dialog confirm would nest a dialog in a dialog. Esc and a click outside both cancel; the Esc handler runs in the CAPTURE phase and stops propagation so cancelling a confirm inside the overlay does not also close the overlay. While a pass runs the control is disabled and the confirm cannot be entered or re-entered.
// Caller: pages/NodesPage.jsx (head), components/nodes/ExclusionsManager.jsx (modal footer)
// Callees: react (useState, useEffect, useRef)
// Data In: onConfirm (fn, starts the pass), running (bool), label (idle text), runningLabel, className (call-site styling), title
// Data Out: default export RescanControl component
// Last Modified: 2026-09-15

import { useState, useEffect, useRef } from 'react';

function RescanControl({
  onConfirm,
  running = false,
  label = 'rescan',
  runningLabel = 'rescanning...',
  className = '',
  title,
}) {
  const [confirming, setConfirming] = useState(false);
  const wrapRef = useRef(null);

  // A pass starting (or the control going disabled for any reason) drops the confirm.
  useEffect(() => {
    if (running) setConfirming(false);
  }, [running]);

  useEffect(() => {
    if (!confirming) return undefined;

    // Capture phase: cancel the confirm and stop the event before the Overlay's
    // own bubble-phase Escape handler can close the panel underneath it.
    const onKeyDown = (e) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      setConfirming(false);
    };
    const onPointerDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setConfirming(false);
    };

    document.addEventListener('keydown', onKeyDown, true);
    document.addEventListener('mousedown', onPointerDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      document.removeEventListener('mousedown', onPointerDown);
    };
  }, [confirming]);

  const confirm = () => {
    setConfirming(false);
    if (onConfirm) onConfirm();
  };

  if (running) {
    return (
      <button type="button" className={className} disabled aria-busy="true" title={title}>
        {runningLabel}
      </button>
    );
  }

  if (confirming) {
    return (
      <span className="rescan-confirm" ref={wrapRef} data-testid="rescan-confirm">
        rescan?{' '}
        <button type="button" className="rescan-confirm__link" onClick={confirm}>yes</button>
        {' / '}
        <button type="button" className="rescan-confirm__link" onClick={() => setConfirming(false)}>cancel</button>
      </span>
    );
  }

  return (
    <button
      type="button"
      className={className}
      onClick={() => setConfirming(true)}
      title={title}
    >
      {label}
    </button>
  );
}

export default RescanControl;
