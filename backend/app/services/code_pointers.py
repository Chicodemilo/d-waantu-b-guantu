# Path: app/services/code_pointers.py
# File: code_pointers.py
# Created: 2026-09-14
# Purpose: Code-pointer grounding lane (DWB-525). Git/diff helpers that walk
#          commit-to-ticket mappings, parse unified-diff hunk headers into
#          per-file new-side line ranges, and BUILD SourceUnits for the node
#          registry (DWB-522): whole-file per-line code units (ref=relpath,
#          sha=commit, line refs) so register_sources mines tags per line and the
#          (code, relpath) refresh scope re-grounds a touched file on each commit
#          (refresh lines + sha, prune vanished tags). Deleted files feed a prune
#          scope. Degrades to empty on missing repo_path / git failure.
# Caller: DWB-527 event dispatch (post-commit touch) -> node_registry.register_sources
# Callees: git via subprocess, app/services/node_registry.SourceUnit
# Data In: repo_path, project prefix, commit sha
# Data Out: (list[SourceUnit], prune_scope set) + plain git-walk dicts
# Last Modified: 2026-09-14

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from app.services.node_registry import SourceUnit

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.services.node_registry import RegistrationResult

# A <PREFIX>-NNN ticket token, scoped per-project by the caller's prefix so a
# DWB commit can't ground against a CI ticket. Mirrors git_hook._parse_ticket_keys.
def _key_pattern(prefix: str) -> re.Pattern:
    return re.compile(rf"\b{re.escape(prefix)}-(\d+)\b")


# Unified-diff hunk header: @@ -old_start[,old_count] +new_start[,new_count] @@
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _git(repo_path: str, args: list[str], *, timeout: int = 15) -> str | None:
    """Run a git command in repo_path, return stdout or None on any failure.

    None (not "") signals a hard git failure (not a repo, git missing, timeout,
    non-zero exit) so callers can degrade gracefully rather than mistaking an
    error for an empty result.
    """
    try:
        out = subprocess.run(
            ["git", "-C", repo_path, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout


def _repo_ok(repo_path: str | None) -> bool:
    """True only when repo_path is set, exists, and is inside a git work tree."""
    if not repo_path:
        return False
    if not Path(repo_path).exists():
        return False
    return _git(repo_path, ["rev-parse", "--is-inside-work-tree"]) is not None


def resolve_full_sha(repo_path: str, sha: str) -> str | None:
    """Expand a short sha to the full 40-char sha, or None if it can't resolve."""
    out = _git(repo_path, ["rev-parse", "--verify", f"{sha}^{{commit}}"])
    if out is None:
        return None
    full = out.strip()
    return full or None


def commit_files(repo_path: str, sha: str) -> list[str]:
    """Repo-relative paths touched by a commit (added/copied/modified/renamed).

    Deletions are excluded - a vanished file cannot host a code pointer. Uses
    diff-tree so merge commits and root commits both resolve. Returns [] on any
    git failure.
    """
    # --diff-filter=d drops pure deletions; -r recurses into trees; -M detects
    # renames (the new path is reported, which is what a pointer should target);
    # --root makes the initial (parentless) commit report its files as additions
    # instead of an empty diff.
    out = _git(
        repo_path,
        ["diff-tree", "--no-commit-id", "--name-only", "-r", "-M", "--root",
         "--diff-filter=d", sha],
    )
    if out is None:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def diff_line_ranges(repo_path: str, sha: str) -> dict[str, list[tuple[int, int]]]:
    """Map each touched file to its new-side line ranges from the commit's diff.

    Parses unified-diff hunk headers (@@ -a,b +c,d @@) with zero context
    (--unified=0) so ranges are tight to the changed lines. The new-side range
    is [new_start, new_start + new_count - 1]; a hunk with new_count == 0 is a
    pure deletion at that point and contributes no range. Returns {} on git
    failure. File keys are repo-relative.
    """
    # --format= suppresses the commit header; -M so renames report the new path;
    # --diff-filter=d drops deletions to stay aligned with commit_files.
    out = _git(
        repo_path,
        ["show", "--unified=0", "--format=", "-M", "--diff-filter=d", sha],
    )
    if out is None:
        return {}

    ranges: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in out.splitlines():
        # New-file marker of a diff stanza: "+++ b/path" (or "+++ /dev/null").
        if line.startswith("+++ "):
            target = line[4:].strip()
            if target == "/dev/null":
                current = None
            else:
                # Strip the "b/" prefix git prepends to the new-side path.
                current = target[2:] if target.startswith("b/") else target
                ranges.setdefault(current, [])
            continue
        if current is None:
            continue
        m = _HUNK_RE.match(line)
        if not m:
            continue
        new_start = int(m.group(1))
        new_count = 1 if m.group(2) is None else int(m.group(2))
        if new_count <= 0:
            # Pure deletion hunk - no new lines to point at.
            continue
        ranges[current].append((new_start, new_start + new_count - 1))
    # Drop files that ended up with no new-side ranges (e.g. mode-only changes).
    return {f: r for f, r in ranges.items() if r}


def _file_lines_at(repo_path: str, file_path: str, sha: str | None) -> list[str] | None:
    """Read a file's lines either from the working tree (sha=None) or as it was
    at a commit (git show sha:path). None on any failure."""
    if sha is None:
        p = Path(repo_path) / file_path
        try:
            return p.read_text(errors="replace").splitlines()
        except (OSError, UnicodeError):
            return None
    out = _git(repo_path, ["show", f"{sha}:{file_path}"])
    if out is None:
        return None
    return out.splitlines()


def deleted_files(repo_path: str, sha: str) -> list[str]:
    """Repo-relative paths DELETED by a commit (diff-filter=D).

    These host no code pointer at the new sha; the caller drops their pointers
    via a prune scope. Returns [] on any git failure.
    """
    out = _git(
        repo_path,
        ["diff-tree", "--no-commit-id", "--name-only", "-r", "-M", "--root",
         "--diff-filter=D", sha],
    )
    if out is None:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def build_code_units(
    repo_path: str | None,
    sha: str,
) -> tuple[list[SourceUnit], set[tuple[str, str]]]:
    """Build code-kind SourceUnits for every file a commit touched, plus the
    prune scope for files it deleted (DWB-525).

    For each non-deleted touched file we read the file AS IT WAS AT THE COMMIT
    (``git show sha:path``) and emit ONE SourceUnit per non-blank line:
    ``kind="code"``, ``ref=<repo-relative path>``, ``sha=<full commit sha>``,
    ``line_start == line_end == <1-based line no>``, ``text=<line content>``.
    node_registry mines each line's tags, so a tag grounds to the exact line it
    lives on, sha-stamped to the commit it was true at - "grep tags with line
    numbers" expressed as the registry's text-mining input.

    Because register_sources treats ``(kind, ref)`` as the refresh scope, feeding
    the WHOLE file each touch makes the pass rewrite that file's pointers with its
    current state: rotted line refs move, the sha advances, and tags that vanished
    from the file are pruned. The prune scope returned here additionally covers
    files the commit deleted (and any touched file we could not read) so their
    pointers drop even though they contribute no units.

    Degrades to ``([], set())`` when repo_path is missing/invalid or git fails -
    never raises, so the post-commit hook lane can call it unconditionally.
    """
    if not _repo_ok(repo_path):
        return [], set()
    assert repo_path is not None  # narrowed by _repo_ok

    full = resolve_full_sha(repo_path, sha) or sha
    touched = commit_files(repo_path, full)
    gone = deleted_files(repo_path, full)

    units: list[SourceUnit] = []
    # Prune scope starts with deletions and every touched file, so a touched
    # file that yields no minable lines still has its stale pointers cleared.
    prune_scope: set[tuple[str, str]] = {("code", f) for f in gone}
    for f in touched:
        prune_scope.add(("code", f))
        lines = _file_lines_at(repo_path, f, full)
        if lines is None:
            # Unreadable at this sha (e.g. binary / vanished): prune only.
            continue
        for lineno, text in enumerate(lines, start=1):
            if not text.strip():
                continue
            units.append(
                SourceUnit(
                    kind="code",
                    ref=f,
                    text=text,
                    sha=full,
                    line_start=lineno,
                    line_end=lineno,
                )
            )
    return units, prune_scope


def walk_commits_for_tickets(
    repo_path: str | None,
    prefix: str,
    *,
    max_commits: int = 500,
    since: str | None = None,
) -> list[dict]:
    """Walk recent commits, returning those whose message references a project
    ticket key, newest-first.

    Each entry: {sha, short_sha, ticket_keys, files, line_ranges} where
      - ticket_keys: unique <PREFIX>-NNN tokens parsed from the commit subject+body
      - files:       repo-relative touched paths (deletions excluded)
      - line_ranges: {file: [(start, end), ...]} new-side ranges from the diff

    Degrades to [] when repo_path is missing/invalid or git fails - never raises.
    `since` (a git date or ref) bounds the walk; `max_commits` caps it otherwise.
    """
    if not _repo_ok(repo_path):
        return []
    assert repo_path is not None  # narrowed by _repo_ok

    # NUL-delimited records: full sha, then the raw commit body, so multi-line
    # messages parse cleanly. %x00 between fields, %x1e between records.
    fmt = "%H%x00%B%x1e"
    log_args = ["log", f"--max-count={max_commits}", f"--format={fmt}"]
    if since:
        log_args.insert(1, f"--since={since}")
    raw = _git(repo_path, log_args)
    if raw is None:
        return []

    pat = _key_pattern(prefix)
    out: list[dict] = []
    for record in raw.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, body = record.partition("\x00")
        sha = sha.strip()
        if not sha:
            continue
        seen: set[str] = set()
        keys: list[str] = []
        for m in pat.finditer(body):
            key = f"{prefix}-{m.group(1)}"
            if key not in seen:
                seen.add(key)
                keys.append(key)
        if not keys:
            continue
        out.append({
            "sha": sha,
            "short_sha": sha[:8],
            "ticket_keys": keys,
            "files": commit_files(repo_path, sha),
            "line_ranges": diff_line_ranges(repo_path, sha),
        })
    return out


# --- grounding operations (build + register) ---------------------------------
# These are the callable seam for DWB-527's event dispatch (and a direct call
# from the post-commit hook lane). They do NOT commit - the caller (router via
# get_db) owns the transaction, per the service-layer rule.


def ground_commit(
    db: "Session",
    project_id: int,
    repo_path: str | None,
    sha: str,
) -> "RegistrationResult":
    """Re-ground code pointers for a single commit's touched files (DWB-525).

    The post-commit touch update: build whole-file per-line units for every file
    the commit touched (sha-stamped to the commit), plus a prune scope for the
    files it deleted, then register them. Idempotent per (code, file) refresh
    scope. Returns an empty RegistrationResult when repo_path/git is unusable so
    the hook lane never errors.
    """
    from app.services.node_registry import RegistrationResult, register_sources

    units, prune = build_code_units(repo_path, sha)
    if not units and not prune:
        return RegistrationResult()
    return register_sources(db, project_id, units, prune_scope=prune)


def ground_code_history(
    db: "Session",
    project_id: int,
    repo_path: str | None,
    prefix: str,
    *,
    max_commits: int = 500,
) -> "RegistrationResult":
    """Backfill code pointers by walking every ticket-referencing commit
    (the code half of a full nodeify pass, DWB-525/527).

    Commits are grounded OLDEST-first so the newest commit that touched a file
    wins the (code, file) refresh scope - each file ends sha-stamped to the last
    commit that changed it, with its current lines. Aggregates the per-commit
    RegistrationResults into one summary. Degrades to an empty result when the
    repo is unusable.
    """
    from app.services.node_registry import RegistrationResult

    commits = walk_commits_for_tickets(repo_path, prefix, max_commits=max_commits)
    agg = RegistrationResult()
    seen_tags: set[str] = set()
    # Oldest-first: reverse the newest-first walk so later state overwrites.
    for commit in reversed(commits):
        r = ground_commit(db, project_id, repo_path, commit["sha"])
        for t in r.grounded_tags:
            if t not in seen_tags:
                seen_tags.add(t)
        agg.pointers_written += r.pointers_written
        agg.scope_refs += r.scope_refs
    agg.grounded_tags = sorted(seen_tags)
    return agg


# --- full-pass provider (DWB-527 nodeify seam) -------------------------------


def code_provider(db: "Session", project, repo_path: str) -> list[SourceUnit]:
    """Full-pass code source provider for node_touch.nodeify (DWB-525/527).

    Registered via node_touch.register_source_provider('code', ...) to REPLACE
    the light message-only default. Walks the project's ticket-referencing
    commits (newest-first) and grounds each touched file exactly ONCE, at the
    NEWEST commit that touched it, as whole-file per-line units (ref=file path,
    sha=that commit, line_start==line_end==N). nodeify supplies the prune scope
    and registers; this fn only produces units and is best-effort ([] on any
    failure) per the provider contract.
    """
    prefix = getattr(project, "prefix", None)
    if not prefix or not _repo_ok(repo_path):
        return []
    commits = walk_commits_for_tickets(repo_path, prefix, max_commits=500)
    units: list[SourceUnit] = []
    seen_files: set[str] = set()
    # Newest-first walk: the first commit that touches a file is its newest, so
    # each file is grounded once at its most-recent ticket-referencing sha.
    for commit in commits:
        sha = commit["sha"]
        for f in commit["files"]:
            if f in seen_files:
                continue
            seen_files.add(f)
            lines = _file_lines_at(repo_path, f, sha)
            if lines is None:
                continue
            for lineno, text in enumerate(lines, start=1):
                if not text.strip():
                    continue
                units.append(
                    SourceUnit(
                        kind="code",
                        ref=f,
                        text=text,
                        sha=sha,
                        line_start=lineno,
                        line_end=lineno,
                    )
                )
    return units


def _register_provider() -> None:
    """Plug code_provider into the nodeify full pass (DWB-527 seam).

    Import-time side effect: importing this module (which happens at app startup
    via the hooks router) registers the richer code extractor over node_touch's
    light default. Wrapped so a registration hiccup can never crash import.
    """
    try:
        from app.services import node_touch

        node_touch.register_source_provider("code", code_provider)
    except Exception:  # noqa: BLE001 - provider registration is best-effort
        import logging

        logging.getLogger(__name__).warning(
            "code_provider registration skipped", exc_info=True
        )


# Landing the override (DWB-525): this REPLACES node_touch's light message-mining
# code_provider (ref=sha) with DWB-525's file-content/line-ref grounding
# (ref=file path, sha-stamped). Safe to register globally: node_touch's own
# nodeify tests isolate the light defaults via an autouse fixture that clears
# _PROVIDER_OVERRIDES, so this import-time registration only takes effect in
# production (and this module is imported at app startup via the hooks router).
_register_provider()
