# Path: app/services/repo_url.py
# File: repo_url.py
# Created: 2026-06-25
# Purpose: Derive a project's GitHub-style web base URL from its git remote (DWBG-021)
# Caller: app/schemas/project.py (ProjectRead.repo_url computed field)
# Callees: subprocess (git), re
# Data In: repo_path (str | None)
# Data Out: str | None  (https://github.com/owner/repo or None)
# Last Modified: 2026-06-25

"""Best-effort derivation of a project's web-browsable repo URL.

The frontend turns narrative code references (``file:line``, commit shas) into
clickable GitHub-style links and needs a clean web base to anchor them. We
derive that base from the project's git remote rather than persisting it, so it
is always fresh and requires no migration.

Contract:
- ``derive_repo_web_url`` NEVER raises. Any failure (missing path, not a repo,
  no remote, non-GitHub remote, subprocess error) returns ``None``.
- The remote URL is read via ``git -C <repo_path> config --get
  remote.origin.url`` with ``repo_path`` passed as an argv element, never
  interpolated into a shell string, so there is no shell-injection surface.
- Only GitHub remotes are recognized. Both SSH and HTTPS forms normalize to a
  clean web base with the trailing ``.git`` stripped:
    git@github.com:owner/repo.git        -> https://github.com/owner/repo
    https://github.com/owner/repo.git    -> https://github.com/owner/repo
    https://github.com/owner/repo        -> https://github.com/owner/repo
    ssh://git@github.com/owner/repo.git   -> https://github.com/owner/repo
"""

import re
import subprocess

# owner/repo: GitHub disallows whitespace and most punctuation; keep this
# permissive but anchored so we only match a single owner/repo segment pair.
_OWNER_REPO = r"(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)"

# SSH scp-like form: git@github.com:owner/repo(.git)
_SSH_RE = re.compile(
    r"^git@github\.com:" + _OWNER_REPO + r"(?:\.git)?/?$",
    re.IGNORECASE,
)

# HTTPS / git / ssh-url forms: (https|http|git|ssh)://[user@]github.com/owner/repo(.git)
_URL_RE = re.compile(
    r"^(?:https?|git|ssh)://(?:[^@/]+@)?github\.com/" + _OWNER_REPO + r"(?:\.git)?/?$",
    re.IGNORECASE,
)


def normalize_github_remote(remote_url: str | None) -> str | None:
    """Normalize a raw git remote URL to a GitHub web base, or None.

    Pure string function (no I/O) so the normalization rules are unit-testable
    without a real repo. Returns ``None`` for empty input or any remote that is
    not a recognizable GitHub remote.
    """
    if not remote_url:
        return None
    candidate = remote_url.strip()
    if not candidate:
        return None

    match = _SSH_RE.match(candidate) or _URL_RE.match(candidate)
    if not match:
        return None

    owner = match.group("owner")
    repo = match.group("repo")
    # Defensive: a trailing ".git" can survive when the non-greedy repo group
    # plus optional suffix interact oddly; strip it explicitly.
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return None
    return f"https://github.com/{owner}/{repo}"


def derive_repo_web_url(repo_path: str | None) -> str | None:
    """Read the git remote at ``repo_path`` and normalize it to a web base.

    Best-effort and safe: returns ``None`` (never raises) when ``repo_path`` is
    missing, is not a git repo, has no ``remote.origin.url``, the git call
    fails, or the remote is not a recognizable GitHub remote.
    """
    if not repo_path:
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", repo_path, "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return normalize_github_remote(completed.stdout)
