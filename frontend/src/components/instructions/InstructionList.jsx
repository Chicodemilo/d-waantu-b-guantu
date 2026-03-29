import useStore from '../../store/useStore';
import InstructionView from './InstructionView';
import '../../styles/common.css';

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
