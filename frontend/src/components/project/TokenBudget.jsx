// Path: src/components/project/TokenBudget.jsx
// File: TokenBudget.jsx
// Created: 2026-04-17
// Purpose: Collapsible token budget panel showing per-file token counts grouped by category, with Memory subgrouped by agent
// Caller: ProjectPage.jsx
// Callees: react (useState, useEffect, useMemo), config (API_BASE_URL), styles/dashboard.css
// Data In: projectId prop
// Data Out: default export TokenBudget component
// Last Modified: 2026-06-18 (DWB-399)

import { useState, useEffect, useMemo } from 'react';
import { API_BASE_URL } from '../../config';
import '../../styles/dashboard.css';

// Section ordering + which categories roll up into each section.
// Agent defs intentionally excluded — they are 8-line stubs post-DWB-331 and don't merit UI surface area.
const SECTIONS = [
  {
    key: 'root_docs',
    label: 'Root Docs',
    categories: ['claude_md', 'handoff', 'team', 'architecture', 'readme', 'initial'],
    info: [
      'Covers: project-level reference at the repo root (CLAUDE.md, HANDOFF.md, ARCHITECTURE.md, README.md, INITIAL.md).',
      'Who edits: you (the human). TL updates HANDOFF.md at session end. Agents otherwise leave these alone.',
      'When updated: HANDOFF.md every session. ARCHITECTURE and README rarely. CLAUDE.md when the project rules change.',
    ],
  },
  {
    key: 'playbooks',
    label: 'Playbooks',
    categories: ['playbook'],
    info: [
      'Covers: how to use the DWB system per role (team-lead, pm, worker). Not project-specific — same content across every DWB-managed project.',
      "Who edits: you only. Agents can't edit playbooks.",
      'When updated: when DWB doctrine evolves in the DWB repo, then pushed here via the Deploy Playbooks button.',
      "Size isn't gated — these just exist.",
    ],
  },
  {
    key: 'project_rules',
    label: 'Project Rules',
    categories: ['project_rules'],
    info: [
      'Covers: project-specific conventions per role — stack, ticket prefix, agent IDs, env vars, anything that differs per project.',
      'Who edits: you and the TL.',
      "When updated: as the project evolves. Never overwritten by Deploy Playbooks — they're yours to keep.",
    ],
  },
  {
    key: 'memory',
    label: 'Memory',
    categories: ['memory_identity', 'memory_scratchpad', 'memory_lessons', 'memory_recent'],
    subgroupBy: 'agent_name',
    info: [
      'Covers: per-agent personal memory — identity.md (who they are), scratchpad.md (in-flight notes), lessons.md (durable patterns), recent_sessions.md (session index).',
      'Who edits: identity.md is system-generated. The owning agent writes scratchpad, lessons, recent_sessions.',
      'When updated: throughout each session. The session-complete endpoint formalizes session-end entries with ISO 8601 timestamps.',
    ],
  },
];

const formatTokens = (n) => {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
};

function InfoIcon({ bullets }) {
  return (
    <span className="token-budget__info-wrap">
      <button
        type="button"
        className="token-budget__info-icon"
        aria-label="Section info"
      >
        i
      </button>
      <div className="token-budget__info-tooltip" role="tooltip">
        <ul>
          {bullets.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      </div>
    </span>
  );
}

function FileRow({ f }) {
  // DWB-398/399: DWB-shipped docs (playbooks, agent defs) are gate-exempt — they
  // just exist, no over/warning judgment. project_rules are budgeted (DWB-399).
  // Exempt rows render neutral:
  // muted indicator, no ratio, a flat muted track instead of a colored bar.
  const exempt = f.status === 'exempt';
  const pct = f.ceiling > 0 ? Math.round((f.tokens / f.ceiling) * 100) : 0;
  const barWidth = Math.min(pct, 100);
  const barClass =
    f.status === 'over'
      ? 'token-budget__bar--over'
      : f.status === 'warning'
        ? 'token-budget__bar--warning'
        : 'token-budget__bar--ok';
  const indicator = exempt
    ? '–'
    : f.status === 'over'
      ? '✗'
      : f.status === 'warning'
        ? '●'
        : '✓';
  return (
    <div className="token-budget__file">
      <div className="token-budget__file-row">
        <span className={`token-budget__indicator token-budget__indicator--${f.status}`}>
          {indicator}
        </span>
        <span className="token-budget__name">{f.name}</span>
        <span className="token-budget__count">
          {exempt ? formatTokens(f.tokens) : `${formatTokens(f.tokens)}/${formatTokens(f.ceiling)}`}
        </span>
      </div>
      <div className="token-budget__bar-track">
        {exempt ? (
          <div className="token-budget__bar-fill token-budget__bar--exempt" />
        ) : (
          <div
            className={`token-budget__bar-fill ${barClass}`}
            style={{ width: `${barWidth}%` }}
          />
        )}
      </div>
    </div>
  );
}

function TokenBudget({ projectId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE_URL}/projects/${projectId}/token-budget`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Group files by section. Memo so we don't redo on every collapse toggle.
  const sections = useMemo(() => {
    if (!data) return [];
    return SECTIONS.map((section) => {
      const files = data.files.filter((f) => section.categories.includes(f.category));
      if (files.length === 0) return { ...section, files: [], subgroups: null };
      if (!section.subgroupBy) return { ...section, files, subgroups: null };
      // Build subgroup map preserving first-seen order.
      const order = [];
      const map = new Map();
      for (const f of files) {
        const k = f[section.subgroupBy] || 'unknown';
        if (!map.has(k)) {
          map.set(k, []);
          order.push(k);
        }
        map.get(k).push(f);
      }
      return {
        ...section,
        files,
        subgroups: order.map((name) => ({ name, files: map.get(name) })),
      };
    }).filter((s) => s.files.length > 0);
  }, [data]);

  if (loading || !data) return null;

  const overCount = data.files.filter((f) => f.status === 'over').length;
  const warnCount = data.files.filter((f) => f.status === 'warning').length;

  const statusLabel =
    overCount > 0
      ? `${overCount} over`
      : warnCount > 0
        ? `${warnCount} warning`
        : '✓ all ok';
  const statusClass =
    overCount > 0
      ? 'token-budget__status--over'
      : warnCount > 0
        ? 'token-budget__status--warning'
        : 'token-budget__status--ok';

  return (
    <div className="token-budget">
      <button
        className="token-budget__toggle"
        onClick={() => setExpanded(!expanded)}
      >
        <span className={`token-budget__caret${expanded ? ' token-budget__caret--open' : ''}`}>&gt;</span>
        token budget
        <span className={`token-budget__status ${statusClass}`}>[{statusLabel}]</span>
      </button>
      {expanded && (
        <div className="token-budget__body">
          <div className="token-budget__summary">
            <span className="token-budget__summary-item">
              total: {formatTokens(data.total_tokens)} tokens across {data.files.length} files
            </span>
            <span className="token-budget__summary-item">
              team startup: ~{formatTokens(data.team_startup_cost)} tokens (5-agent team)
            </span>
          </div>
          <div className="token-budget__sections">
            {sections.map((section) => {
              const sectionTotal = section.files.reduce((acc, f) => acc + f.tokens, 0);
              return (
                <section key={section.key} className="token-budget__section">
                  <header className="token-budget__section-header">
                    <span className="token-budget__section-label">
                      {section.label}
                      {section.info && <InfoIcon bullets={section.info} />}
                    </span>
                    <span className="token-budget__section-meta">
                      {section.files.length} {section.files.length === 1 ? 'file' : 'files'}
                      {' · '}
                      {formatTokens(sectionTotal)} tokens
                    </span>
                  </header>
                  {section.subgroups ? (
                    <div className="token-budget__subgroups">
                      {section.subgroups.map((sg) => {
                        const sgTotal = sg.files.reduce((acc, f) => acc + f.tokens, 0);
                        return (
                          <div key={sg.name} className="token-budget__subgroup">
                            <header className="token-budget__subgroup-header">
                              <span className="token-budget__subgroup-label">{sg.name}</span>
                              <span className="token-budget__subgroup-meta">
                                {formatTokens(sgTotal)} tokens
                              </span>
                            </header>
                            <div className="token-budget__list">
                              {sg.files.map((f) => (
                                <FileRow key={f.path} f={f} />
                              ))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="token-budget__list">
                      {section.files.map((f) => (
                        <FileRow key={f.path} f={f} />
                      ))}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default TokenBudget;
