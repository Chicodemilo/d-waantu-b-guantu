// Path: src/hooks/useStandardsAudits.js
// File: useStandardsAudits.js
// Created: 2026-08-12
// Purpose: View-shaped data hook for the Standards Audits section. Encapsulates the fetch + 30s refresh interval + AbortController lifecycle and exposes { audits, loading, error } so the consuming component stays render-only. usePolling drives the global store loop and useTrackingSummary is a shared-cache dedup layer, so neither fits this per-section fetch shape; this hook owns its own local state.
// Caller: components/project/StandardsAudits.jsx, __tests__/useStandardsAudits.test.jsx
// Callees: react (useState, useEffect), api/standardsAudits (getStandardsAudits)
// Data In: projectId (number)
// Data Out: { audits: array, loading: boolean, error: boolean }
// Last Modified: 2026-08-12 (DWB-018)

import { useState, useEffect } from 'react';
import { getStandardsAudits } from '../api/standardsAudits';

const REFRESH_MS = 30_000;

function useStandardsAudits(projectId) {
  const [audits, setAudits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function refresh() {
      try {
        const data = await getStandardsAudits(projectId, { signal: controller.signal });
        if (cancelled) return;
        setAudits(Array.isArray(data) ? data : []);
        setError(false);
      } catch (err) {
        if (cancelled || err.name === 'AbortError') return;
        setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    refresh();
    const timer = setInterval(refresh, REFRESH_MS);
    return () => {
      cancelled = true;
      controller.abort();
      clearInterval(timer);
    };
  }, [projectId]);

  return { audits, loading, error };
}

export default useStandardsAudits;
