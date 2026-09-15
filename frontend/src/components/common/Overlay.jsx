// Path: src/components/common/Overlay.jsx
// File: Overlay.jsx
// Created: 2026-09-15
// Purpose: Generic overlay modal (DWB-535, Miles ruling for the node detail view). Portals a fixed scrim + centered panel to document.body, built on the .sidebar-overlay scrim pattern from layout.css/AppShell. Closes on Esc, scrim click, and a plain-text close link; traps Tab focus inside the panel while open and restores focus to the opener on close. Carries no domain props: whatever it should show is passed as children. Inline-text confirms elsewhere are unaffected; this is the only modal surface in the app.
// Caller: pages/NodesPage.jsx (node detail); any future view that needs a modal surface
// Callees: react (useEffect, useRef), react-dom (createPortal)
// Data In: open (bool), onClose (fn), label (aria-label string), closeLabel (string, default "close"), children
// Data Out: default export Overlay component (renders null when closed)
// Last Modified: 2026-09-15

import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function Overlay({ open, onClose, label = 'dialog', closeLabel = 'close', children }) {
  const panelRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return undefined;
    const panel = panelRef.current;
    const opener = document.activeElement;
    const focusables = () => (panel ? Array.from(panel.querySelectorAll(FOCUSABLE)) : []);

    const first = focusables()[0];
    if (first) first.focus();
    else if (panel) panel.focus();

    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        if (onCloseRef.current) onCloseRef.current();
        return;
      }
      if (e.key !== 'Tab' || !panel) return;
      const list = focusables();
      if (list.length === 0) {
        e.preventDefault();
        panel.focus();
        return;
      }
      const head = list[0];
      const tail = list[list.length - 1];
      const active = document.activeElement;
      const inside = panel.contains(active);
      if (e.shiftKey) {
        if (!inside || active === head || active === panel) {
          e.preventDefault();
          tail.focus();
        }
      } else if (!inside || active === tail) {
        e.preventDefault();
        head.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      if (opener && typeof opener.focus === 'function' && document.contains(opener)) opener.focus();
    };
  }, [open]);

  if (!open) return null;

  const handleScrimClick = (e) => {
    if (e.target === e.currentTarget && onClose) onClose();
  };

  return createPortal(
    <div className="overlay" data-testid="overlay-scrim" onClick={handleScrimClick}>
      <div
        className="overlay__panel"
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        ref={panelRef}
      >
        <div className="overlay__bar">
          <button type="button" className="overlay__close" onClick={onClose}>
            {closeLabel}
          </button>
        </div>
        <div className="overlay__body">{children}</div>
      </div>
    </div>,
    document.body
  );
}

export default Overlay;
