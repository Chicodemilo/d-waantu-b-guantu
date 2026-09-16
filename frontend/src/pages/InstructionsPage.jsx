// Path: src/pages/InstructionsPage.jsx
// File: InstructionsPage.jsx
// Created: 2026-03-29
// Purpose: Manages CLI instruction syncing, displays instruction list, playbooks, and code standards
// Caller: App.jsx (route: /instructions)
// Callees: react, ../components/instructions/InstructionList, ../api/instructions, ../api/status, ../services/logger
// Data In: Instructions sync status, playbooks, and code standards from API
// Data Out: Default export InstructionsPage component; named export codeHeaderTemplate (pure shape reader)
// Last Modified: 2026-09-16 (DWB-573: read header_format.template at its real path;
//          dropped the JSON.stringify fallback that turned a shape break into
//          raw JSON on the page and made it look deliberate)

import { useState, useEffect, useCallback } from 'react';
import InstructionList from '../components/instructions/InstructionList';
import { syncCheck, syncInstructions, getPlaybooks } from '../api/instructions';
import { getCodeStandards } from '../api/status';
import { log } from '../services/logger';

// The one shape GET /api/status/code-standards returns: {header_format: {fields,
// template, placement}}. Read it at its documented path and nowhere else. The
// previous chain (template || header_template || JSON.stringify) guessed at two
// top-level keys that have never existed on this endpoint, so it silently fell
// through to dumping the raw response onto a page a human reads, while looking
// like deliberate multi-shape handling. A miss is now a visible, logged failure:
// resilience that hides a break is worse than no resilience at all.
export function codeHeaderTemplate(codeStandards) {
  const template = codeStandards?.header_format?.template;
  return typeof template === 'string' && template.trim() ? template : null;
}

function InstructionsPage() {
  const [unsynced, setUnsynced] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [playbooks, setPlaybooks] = useState([]);
  const [expandedPlaybook, setExpandedPlaybook] = useState(null);
  const [codeStandards, setCodeStandards] = useState(null);
  const [standardsExpanded, setStandardsExpanded] = useState(false);
  const headerTemplate = codeHeaderTemplate(codeStandards);

  // Shape drift is loud for the team too, not just the reader: without this the
  // next move of this key is only ever caught by someone happening to look.
  useEffect(() => {
    if (codeStandards && !codeHeaderTemplate(codeStandards)) {
      log.error(
        'shape',
        'code-standards response has no header_format.template',
        { keys: Object.keys(codeStandards) }
      );
    }
  }, [codeStandards]);

  const checkSync = useCallback(async () => {
    try {
      const result = await syncCheck();
      setUnsynced(result.unsynced_count ?? 0);
    } catch {
      setUnsynced(null);
    }
  }, []);

  useEffect(() => {
    checkSync();
    getPlaybooks().then(setPlaybooks).catch(() => {});
    getCodeStandards().then(setCodeStandards).catch(() => {});
  }, [checkSync]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await syncInstructions();
      await checkSync();
    } catch {
      // sync endpoint may not exist yet
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div>
      <div className="page-title">
        <span>Instructions</span>
        <span className="tooltip-trigger">
          ?
          <span className="tooltip-content">
            Syncs instructions from your CLI configuration into the dashboard.
            Rules you set in your CLI are parsed and imported here for visibility.
          </span>
        </span>
      </div>
      <div style={{ marginBottom: '16px' }}>
        <button
          className="sync-btn"
          onClick={handleSync}
          disabled={syncing}
        >
          {syncing ? '$ syncing...' : '$ sync from cli'}
        </button>
        {unsynced !== null && (
          <span className="sync-btn__status">
            {unsynced > 0 ? `${unsynced} unsynced` : '\u2713 synced'}
          </span>
        )}
      </div>
      {codeStandards && (
        <div className="instruction-scope-group" style={{ marginBottom: '24px' }}>
          <div className="instruction-scope-group__title">
            Code Standards
            <span className="tooltip-trigger">
              ?
              <span className="tooltip-content">
                Mandatory header for all code files. Format is managed by the team lead: request changes via Claude Code.
              </span>
            </span>
          </div>
          {headerTemplate ? (
            <div className="instruction-card">
              <div
                className="instruction-card__header"
                onClick={() => setStandardsExpanded(!standardsExpanded)}
              >
                <span className={`instruction-card__caret${standardsExpanded ? ' instruction-card__caret--open' : ''}`}>&gt;</span>
                <span className="instruction-card__title">File Header Template</span>
              </div>
              {standardsExpanded && (
                <pre className="code-standards__template">{headerTemplate}</pre>
              )}
            </div>
          ) : (
            // Not behind the expander on purpose: a break hidden inside a
            // collapsed card is the same silent failure in a new costume.
            <div className="code-standards__missing">
              Code standards unavailable: the API response carried no
              header_format.template. Nothing to show here until it does.
            </div>
          )}
        </div>
      )}
      <InstructionList />
      {playbooks.length > 0 && (
        <div className="instruction-scope-group" style={{ marginTop: '24px' }}>
          <div className="instruction-scope-group__title">Playbooks</div>
          {playbooks.map((pb) => (
            <div key={pb.id || pb.title} className="instruction-card">
              <div
                className="instruction-card__header"
                onClick={() => setExpandedPlaybook(expandedPlaybook === pb.title ? null : pb.title)}
              >
                <span className={`instruction-card__caret${expandedPlaybook === pb.title ? ' instruction-card__caret--open' : ''}`}>&gt;</span>
                <span className="instruction-card__title">{pb.title}</span>
              </div>
              {expandedPlaybook === pb.title && (
                <div className="instruction-card__body">{pb.body || pb.content}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default InstructionsPage;
