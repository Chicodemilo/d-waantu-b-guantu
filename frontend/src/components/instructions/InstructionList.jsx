// Path: src/components/instructions/InstructionList.jsx
// File: InstructionList.jsx
// Created: 2026-03-29
// Purpose: Groups and displays instructions by scope (global, project, agent)
// Caller: InstructionsPage.jsx
// Callees: useStore, InstructionView
// Data In: None (reads instructions from store)
// Data Out: default export InstructionList component
// Last Modified: 2026-08-11 (DWB-009)

import useStore from '../../store/useStore';
import InstructionView from './InstructionView';

function InstructionList() {
  const instructions = useStore((s) => s.instructions);

  const scopes = [
    { key: 'global', label: 'Global Instructions' },
    { key: 'project', label: 'Project Instructions' },
    { key: 'agent', label: 'Agent Instructions' },
  ];

  return (
    <div className="instruction-list">
      {scopes.map((scope) => {
        const items = instructions.filter((i) => i.scope === scope.key);
        if (items.length === 0) return null;
        return (
          <div key={scope.key} className="instruction-scope-group">
            <div className="instruction-scope-group__title">{scope.label}</div>
            {items.map((item) => (
              <InstructionView key={item.id} instruction={item} />
            ))}
          </div>
        );
      })}
    </div>
  );
}

export default InstructionList;
