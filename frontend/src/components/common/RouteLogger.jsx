// Path: src/components/common/RouteLogger.jsx
// File: RouteLogger.jsx
// Created: 2026-06-10
// Purpose: Headless component that logs `nav.mount` and `nav.unmount` records to the client-logs feed whenever the React Router pathname changes (DWB-371). Mounted once inside the Router context (App.jsx). Useful for the TL to reconstruct an SPA navigation sequence without browser-console access.
// Caller: App.jsx (sibling of <Routes>)
// Callees: react (useEffect), react-router-dom (useLocation), services/logger (log)
// Data In: None - reads location from react-router context
// Data Out: Returns null. Side effect: log.info('nav.mount'|'nav.unmount', path, { search })
// Last Modified: 2026-06-10

import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { log } from '../../services/logger';

function RouteLogger() {
  const location = useLocation();

  useEffect(() => {
    const path = location.pathname;
    const search = location.search || '';
    log.info('nav.mount', path, { search });
    return () => {
      log.info('nav.unmount', path, { search });
    };
  }, [location.pathname, location.search]);

  return null;
}

export default RouteLogger;
