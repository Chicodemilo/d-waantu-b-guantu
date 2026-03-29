import { useState, useEffect, useCallback } from 'react';
import InstructionList from '../components/instructions/InstructionList';
import { syncCheck, syncInstructions, getPlaybooks } from '../api/instructions';
import { getCodeStandards } from '../api/status';
import '../styles/dashboard.css';
import '../styles/common.css';

function InstructionsPage() {
  const [unsynced, setUnsynced] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [playbooks, setPlaybooks] = useState([]);
  const [expandedPlaybook, setExpandedPlaybook] = useState(null);
  const [codeStandards, setCodeStandards] = useState(null);
  const [standardsExpanded, setStandardsExpanded] = useState(false);

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
                Mandatory header for all code files. Format is managed by the team lead — request changes via Claude Code.
              </span>
            </span>
          </div>
          <div className="instruction-card">
            <div
              className="instruction-card__header"
              onClick={() => setStandardsExpanded(!standardsExpanded)}
            >
              <span className={`instruction-card__caret${standardsExpanded ? ' instruction-card__caret--open' : ''}`}>&gt;</span>
              <span className="instruction-card__title">File Header Template</span>
            </div>
            {standardsExpanded && (
              <pre className="code-standards__template">{codeStandards.template || codeStandards.header_template || JSON.stringify(codeStandards, null, 2)}</pre>
            )}
          </div>
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
