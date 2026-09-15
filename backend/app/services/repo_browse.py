# Path: app/services/repo_browse.py
# File: repo_browse.py
# Created: 2026-09-15
# Purpose: Read-only directory browsing under a project's repo_path (DWB-553), for the exclusions browser in the DWB-552 manager. One level per call, repo-relative in and out, with every path resolved and proven to stay inside the repo root.
# Caller: app/routers/repo_browse.py
# Callees: pathlib
# Data In: repo_path + a repo-relative parent
# Data Out: list of {name, path} dicts for the child directories
# Last Modified: 2026-09-15

"""Browsing the repo tree without letting a caller out of it (DWB-553).

The exclusions manager needs to show a user the directories they can exclude,
and the patterns it stores are repo-relative, so this speaks the same language:
repo-relative in, repo-relative out. Nothing here writes.

CONTAINMENT is the whole point of the module. Three independent checks, because
each catches something the others miss:
  1. Syntactic refusal of absolute input and of any ``..`` segment, so an obvious
     escape is rejected with a message that names the reason.
  2. ``Path.resolve()`` on the joined path, then a containment test against the
     RESOLVED repo root. This is what catches a symlink pointing outside the
     repo, which no amount of string inspection would see.
  3. The listing itself only ever yields directories it found by walking one
     level of a contained directory, and re-checks each child, so a symlinked
     subdirectory cannot widen the tree either.

Hidden directories, ``node_modules`` and ``__pycache__`` are skipped: none is
somewhere a user browses on purpose, and ``.git`` in particular would bury the
useful entries. See _SKIP_NAMES for why that list stays short.
"""

from pathlib import Path

# Never listed, alongside every dot directory (.git, .venv, .dwb, .claude,
# .pytest_cache, .ruff_cache...): directories that are always GENERATED output,
# never something a human browses to on purpose.
#
# The bar for adding a name here is "can this ever be a directory the user
# actually wants to see?", and it is deliberately high, because hiding a
# directory does not merely tidy the list - it removes the user's ability to
# reach that subtree from the browser at all. __pycache__ and node_modules can
# only ever be build artefacts. Names like build/ and dist/ are NOT here for
# exactly that reason: they are conventional output in some repos and real
# source in others, and a wrong hide costs more than a visible row does.
_SKIP_NAMES = frozenset({"node_modules", "__pycache__"})


class RepoBrowseError(Exception):
    """Coded failure the router maps to a status. ``detail`` names the reason,
    so a refusal tells the caller what was wrong with the path they sent."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _normalize_parent(parent: str | None) -> str:
    """Repo-relative, forward-slashed, no leading './' or '/'.

    Raises RepoBrowseError('invalid_path') for absolute input or any '..'
    segment, before the path is joined to anything.
    """
    raw = (parent or "").strip()
    if not raw:
        return ""
    candidate = raw.replace("\\", "/")
    if candidate.startswith("/") or candidate.startswith("~"):
        raise RepoBrowseError(
            "invalid_path", f"parent must be repo-relative, not absolute: {raw!r}"
        )
    if len(candidate) > 1 and candidate[1] == ":":
        raise RepoBrowseError(
            "invalid_path", f"parent must be repo-relative, not absolute: {raw!r}"
        )
    while candidate.startswith("./"):
        candidate = candidate[2:]
    candidate = candidate.strip("/")
    if ".." in candidate.split("/"):
        raise RepoBrowseError(
            "invalid_path", f"parent must not escape the repo root: {raw!r}"
        )
    return candidate


def _contained(root: Path, target: Path) -> bool:
    """True when target, fully resolved, is the root or sits inside it. This is
    the check that catches a symlink out of the tree."""
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True


def list_directories(repo_path: str | None, parent: str | None = "") -> dict:
    """One level of child directories under ``parent``, repo-relative.

    Returns ``{"parent": <normalized>, "directories": [{"name", "path"}, ...]}``
    sorted by name. Raises RepoBrowseError with code 'no_repo_path',
    'invalid_path' (absolute, traversal, or escaping once resolved) or
    'not_found' (no such directory under the repo).
    """
    if not repo_path:
        raise RepoBrowseError(
            "no_repo_path", "project has no repo_path; nothing to browse"
        )
    root = Path(repo_path)
    if not root.is_dir():
        raise RepoBrowseError(
            "no_repo_path", f"repo_path is not a directory: {repo_path}"
        )
    root = root.resolve()

    rel = _normalize_parent(parent)
    target = (root / rel).resolve() if rel else root
    # Containment after resolution: a symlink inside the repo pointing out of it
    # passes every string check and fails here.
    if not _contained(root, target):
        raise RepoBrowseError(
            "invalid_path", f"parent must not escape the repo root: {parent!r}"
        )
    if not target.is_dir():
        raise RepoBrowseError("not_found", f"directory not found: {rel or '.'}")

    directories: list[dict] = []
    try:
        children = sorted(target.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        # Unreadable directory: an empty level beats a 500 on a browse.
        children = []

    for child in children:
        name = child.name
        if name.startswith(".") or name in _SKIP_NAMES:
            continue
        try:
            if not child.is_dir():
                continue
            resolved = child.resolve()
        except OSError:
            continue
        # A symlinked child pointing outside the repo is not browsable either.
        if not _contained(root, resolved):
            continue
        directories.append({"name": name, "path": f"{rel}/{name}" if rel else name})

    return {"parent": rel, "directories": directories}
