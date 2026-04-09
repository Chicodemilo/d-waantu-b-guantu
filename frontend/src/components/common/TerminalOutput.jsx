// Path: src/components/common/TerminalOutput.jsx
// File: TerminalOutput.jsx
// Created: 2026-04-09
// Purpose: Renders terminal-style output display with ASCII box borders, loading state, and scrollable content
// Caller: TestResultsPage.jsx
// Callees: tests.css
// Data In: props { output, isOpen, isLoading }
// Data Out: default export TerminalOutput component
// Last Modified: 2026-04-09

import '../../styles/tests.css';

const BORDER_WIDTH = 78;
const BORDER_LINE = '+' + '-'.repeat(BORDER_WIDTH) + '+';

function TerminalOutput({ output, isOpen, isLoading = false }) {
  if (!isOpen) return null;

  let content;
  if (isLoading) {
    content = <span className="terminal-output__loading">&gt; running tests...</span>;
  } else if (!output) {
    content = <span className="terminal-output__empty">&gt; output not available</span>;
  } else {
    content = <pre>{output}</pre>;
  }

  return (
    <div className="terminal-output">
      <div className="terminal-output__border">{BORDER_LINE}</div>
      <div className="terminal-output__content">
        {content}
      </div>
      <div className="terminal-output__border">{BORDER_LINE}</div>
    </div>
  );
}

export default TerminalOutput;
