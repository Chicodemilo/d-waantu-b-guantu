# Path: app/config/node_scan.py
# File: node_scan.py
# Created: 2026-09-15 (DWB-549)
# Purpose: The node-scan exclusion MATCHER plus the shipped default patterns that seed a new project. One pattern grammar shared by the code lane (code_pointers) and the doc lane (doc_pointers) so a path is excluded identically everywhere, applied at enumeration so an excluded file never becomes a SourceUnit.
# Caller: app/services/code_pointers.py, app/services/doc_pointers.py, app/services/node_exclusion.py
# Callees: fnmatch
# Data In: a repo-relative file path + the project's active pattern tuple
# Data Out: bool (is this path excluded)
# Last Modified: 2026-09-15 (DWB-549 amendment: patterns come from the DB per project, not from process config)

"""What the node index deliberately does NOT read (DWB-549).

Two measured problems motivated this, both from the live project-1 index:

1. DUPLICATION (the worse one). Playbooks exist twice in the tree: the source
   under ``docs/`` and the deployed copy under ``.claude/``. The deployed copy is
   byte-identical and reaches the index through the CODE lane (it is a tracked
   file in playbook-deploy commits), so every playbook term was grounded twice.
   Document frequency counted both copies, which inflated df and - since DWB-545
   divides by df - quietly pushed genuinely common playbook vocabulary DOWN and
   made the whole idf scale lie. ``docs/`` stays because it is the source.

2. VOLUME. 13,810 of 59,948 code pointers (23%) came from ``backend/tests``.
   Test files restate the vocabulary of the code they exercise, so they add
   pointers without adding places worth sending an agent, and they crowd the
   ranked output with a source file's test twin.

WHERE THE LIST LIVES. This module owns the matcher and the shipped defaults, and
nothing else. The active list is per-project DATABASE state (see
app/services/node_exclusion.py) because a human edits it from the nodes page, so
``patterns`` is a REQUIRED argument here: there is no process-wide fallback a
lane could accidentally inherit, and the defaults below are only ever read once,
when a project is seeded. From then on they are ordinary rows, and a user who
deletes one has deleted it - this matcher cannot tell a seeded pattern from a
typed one and must not try.

Pattern grammar, deliberately small:
  - ``some/dir/``    directory PREFIX - excludes that subtree.
  - ``**/name/``     directory at ANY depth - excludes every such subtree.
  - ``conftest.py``  a bare filename or glob - matched against the BASENAME.
  - ``a/b/*.md``     a glob containing "/" - matched against the whole path.
"""

from fnmatch import fnmatch

# Seeded into a project's exclusion rows on first use. Deployed playbook copies
# (source of the double-grounding) plus test dirs/files across both stacks.
DEFAULT_NODE_SCAN_EXCLUDES: tuple[str, ...] = (
    ".claude/",
    "backend/tests/",
    "**/__tests__/",
    "test_*.py",
    "conftest.py",
    "*.test.js",
    "*.test.jsx",
)


def _normalize(relpath: str) -> str:
    """Repo-relative, forward-slashed, no leading './'."""
    p = (relpath or "").replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def is_excluded(relpath: str, patterns: tuple[str, ...] | list[str]) -> bool:
    """True when this repo-relative path must not be grounded.

    ``patterns`` is the project's active list and is required - an empty list
    excludes nothing, which is exactly how a project whose rows a user cleared
    indexes, and how every project behaved before this ticket. An empty path is
    never excluded.
    """
    if not patterns:
        return False
    path = _normalize(relpath)
    if not path:
        return False
    segments = path.split("/")
    basename = segments[-1]

    for raw in patterns:
        pattern = _normalize(raw)
        if not pattern:
            continue
        if pattern.endswith("/"):
            directory = pattern[:-1]
            if directory.startswith("**/"):
                # Directory of that name at any depth (exclude the file itself
                # being the "directory" - only interior segments count).
                if directory[3:] in segments[:-1]:
                    return True
            elif path.startswith(f"{directory}/"):
                return True
            continue
        # File pattern: globs containing a separator match the whole path,
        # bare globs match the basename.
        target = path if "/" in pattern else basename
        if fnmatch(target, pattern):
            return True
    return False
