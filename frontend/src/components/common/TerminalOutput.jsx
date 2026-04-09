// Path: src/components/common/TerminalOutput.jsx
// File: TerminalOutput.jsx
// Created: 2026-04-09
// Purpose: Terminal-style output display with ASCII box borders, animated open/close, scrollable content
// Caller: TestResultsPage.jsx
// Callees: tests.css
// Data In: props { output, isOpen, isLoading }
// Data Out: default export TerminalOutput component
// Last Modified: 2026-04-09

import { useRef, useState, useEffect } from 'react';
import '../../styles/tests.css';

function TerminalOutput({ output, isOpen, isLoading = false }) {
  const contentRef = useRef(null);
  const scrollRef = useRef(null);
  const [height, setHeight] = useState(0);

  useEffect(() => {
    if (isOpen && contentRef.current) {
      setHeight(contentRef.current.scrollHeight);
    } else {
      setHeight(0);
    }
  }, [isOpen, output, isLoading]);

  useEffect(() => {
    if (isOpen && output && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [isOpen, output]);

  let content;
  if (isLoading) {
    content = <span className="terminal-output__empty terminal-output__loading">&gt; running tests...</span>;
  } else if (!output) {
    content = <span className="terminal-output__empty">&gt; output not available</span>;
  } else {
    const lines = output.split('\n');
    content = lines.map((line, i) => (
      <div key={i} className="terminal-output__line">
        <span className="terminal-output__pipe">|</span>
        <span className="terminal-output__text">{line || ' '}</span>
        <span className="terminal-output__pipe">|</span>
      </div>
    ));
  }

  return (
    <div className={`terminal-output${isOpen ? ' terminal-output--open' : ''}`}>
      <div
        className="terminal-output__wrapper"
        style={{ maxHeight: isOpen ? Math.min(height, 220) + 'px' : '0px' }}
      >
        <div ref={contentRef}>
          <div className="terminal-output__border">
            <span>+</span>
            <span className="terminal-output__border-fill"></span>
            <span>+</span>
          </div>
          <div className="terminal-output__scroll" ref={scrollRef}>
            {content}
          </div>
          <div className="terminal-output__border">
            <span>+</span>
            <span className="terminal-output__border-fill"></span>
            <span>+</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default TerminalOutput;
