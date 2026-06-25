// Path: src/components/project/InlineMarkdown.jsx
// File: InlineMarkdown.jsx
// Created: 2026-06-25
// Purpose: Light, SAFE inline-markdown renderer for session NARRATIVE bullets/lead
//          (DWBG-015). Turns a plain string into React nodes so the narrative reads
//          like Claude Code's VS Code session wrap-ups: inline `code` -> styled code
//          chips, markdown links [text](url) -> clickable anchors, and bare file/commit
//          refs (path/to/file.ext, file.ext:line, 7-40 char hex commit shas) ->
//          clickable links when an optional resolver is supplied (else plain text).
//          Parser is a hand-rolled tokenizer that emits React elements only — it never
//          uses dangerouslySetInnerHTML, so no raw-HTML / script injection is possible.
//          Plain-text input with no markdown renders verbatim (graceful fallback).
// Caller: components/project/SessionSummary.jsx (narrative rendering only)
// Callees: react
// Data In: text (string), linkResolver (optional fn(ref) -> href|null for bare refs)
// Data Out: default export InlineMarkdown component (renders a <> fragment of nodes)
// Last Modified: 2026-06-25

import { Fragment } from 'react';

// Order matters: code spans are matched first so backtick contents are never
// re-scanned for links/refs (a `code` span is opaque).
//   1. `code`                       -> code chip
//   2. [text](http(s)://... | path) -> anchor
//   3. bare commit sha (7-40 hex)   -> anchor (via resolver) | text
//   4. bare file ref path/to/x.ext  -> anchor (via resolver) | text
const CODE_RE = /`([^`]+)`/;
const LINK_RE = /\[([^\]]+)\]\(([^)\s]+)\)/;
// A commit-ish hex run (word-bounded) — kept conservative to avoid grabbing prose.
const SHA_RE = /\b([0-9a-f]{7,40})\b/;
// path/to/file.ext  OR  file.ext  OR  file.ext:line — must contain a dotted ext.
const FILE_RE = /\b([\w./-]*[\w-]+\.[A-Za-z][\w]*(?::\d+)?)\b/;

// Is a URL safe to put in href? Only http(s) and root-relative app paths. This
// blocks javascript:/data: schemes even though we never inject HTML.
function safeHref(url) {
  if (!url) return null;
  const u = String(url).trim();
  if (/^https?:\/\//i.test(u)) return u;
  if (u.startsWith('/')) return u;
  return null;
}

// Find the earliest of several regexes in `text`; returns the winning match
// (with which kind it is) or null when none match.
function firstMatch(text) {
  const candidates = [
    { kind: 'code', m: CODE_RE.exec(text) },
    { kind: 'link', m: LINK_RE.exec(text) },
    { kind: 'sha', m: SHA_RE.exec(text) },
    { kind: 'file', m: FILE_RE.exec(text) },
  ].filter((c) => c.m);
  if (candidates.length === 0) return null;
  candidates.sort((a, b) => a.m.index - b.m.index);
  return candidates[0];
}

// Tokenize one string into an array of React nodes.
function renderInline(text, linkResolver, keyBase) {
  const nodes = [];
  let rest = String(text == null ? '' : text);
  let i = 0;

  while (rest.length > 0) {
    const hit = firstMatch(rest);
    if (!hit) {
      nodes.push(<Fragment key={`${keyBase}-t${i++}`}>{rest}</Fragment>);
      break;
    }

    const { kind, m } = hit;
    if (m.index > 0) {
      nodes.push(
        <Fragment key={`${keyBase}-t${i++}`}>{rest.slice(0, m.index)}</Fragment>
      );
    }

    if (kind === 'code') {
      nodes.push(
        <code className="narrative-chip" key={`${keyBase}-c${i++}`}>
          {m[1]}
        </code>
      );
    } else if (kind === 'link') {
      const href = safeHref(m[2]);
      nodes.push(
        href ? (
          <a
            className="narrative-link"
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            key={`${keyBase}-l${i++}`}
          >
            {m[1]}
          </a>
        ) : (
          // Unsafe scheme -> render the visible text only, never the href.
          <Fragment key={`${keyBase}-l${i++}`}>{m[1]}</Fragment>
        )
      );
    } else {
      // bare sha or file ref — clickable only if a resolver hands back an href.
      const ref = m[1];
      const href = typeof linkResolver === 'function' ? safeHref(linkResolver(ref)) : null;
      nodes.push(
        href ? (
          <a
            className="narrative-link narrative-link--ref"
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            key={`${keyBase}-r${i++}`}
          >
            {ref}
          </a>
        ) : (
          <span className="narrative-ref" key={`${keyBase}-r${i++}`}>
            {ref}
          </span>
        )
      );
    }

    rest = rest.slice(m.index + m[0].length);
  }

  return nodes;
}

function InlineMarkdown({ text, linkResolver, keyBase = 'md' }) {
  return <>{renderInline(text, linkResolver, keyBase)}</>;
}

export { renderInline, safeHref };
export default InlineMarkdown;
