#!/usr/bin/env bash
# Path: scripts/install-git-hooks.sh
# Created: 2026-06-10
# Purpose: Install the DWB post-commit hook into THIS clone, and prove it took.
#   Also `--check`, which reports whether the clone is armed and changes nothing.
# Caller: an operator, by hand, once per fresh checkout. NOTHING runs this
#   automatically and nothing should: git deliberately refuses to execute hooks
#   that arrive with a clone, so arming is a local action by design.
# Last Modified: 2026-10-28 (DWB-695: verify after installing, add --check)
#
# WHY THIS SCRIPT VERIFIES ITSELF
#
# The defect DWB-695 exists to close is that an unarmed clone and a quiet one
# look identical from inside DWB. A `ln -s` that prints "installed" and is
# never checked reproduces that problem one level up: it reports that it RAN,
# not that it LANDED. So the last thing this script does is ask whether git
# would actually run the hook, and exit non-zero if it would not.
#
# THE THREE CONDITIONS BELOW MIRROR `app/services/git_hook_health.py`
# DELIBERATELY, and a test asserts the two agree. They are:
#   1. a post-commit file exists in the directory git ACTUALLY uses
#      (`git rev-parse --git-path hooks`, which honours core.hooksPath),
#   2. it is executable - git SILENTLY skips a hook that is not, and the hint
#      it prints goes to the committer's terminal, never to DWB,
#   3. it contains the DWB endpoint, so it reports to us rather than merely
#      being some hook.
#
# core.hooksPath IS NOT SET BY THIS SCRIPT, by ruling. Setting it REPLACES the
# hooks directory rather than adding to it, so a half-done configuration
# switches `.git/hooks` off as well and leaves a repository that looks
# configured and runs nothing. That failure is live on another repo today.

set -euo pipefail

MARKER="/api/hooks/post-commit"

repo_root="$(git rev-parse --show-toplevel)"
src="$repo_root/scripts/hooks/post-commit"

hooks_dir_rel="$(git -C "$repo_root" rev-parse --git-path hooks)"
case "$hooks_dir_rel" in
  /*) hooks_dir="$hooks_dir_rel" ;;
  *)  hooks_dir="$repo_root/$hooks_dir_rel" ;;
esac
dst="$hooks_dir/post-commit"

override="$(git -C "$repo_root" config --get core.hooksPath || true)"

# Reports the armed state. Prints a verdict, returns 0 armed / 1 unarmed.
check_armed() {
  if [[ -n "$override" ]]; then
    echo "note: core.hooksPath is set to '$override', so .git/hooks is IGNORED."
    echo "      git looks only in: $hooks_dir"
  fi
  if [[ ! -e "$dst" ]]; then
    echo "UNARMED: no post-commit hook at $dst"
    return 1
  fi
  if [[ ! -x "$dst" ]]; then
    echo "UNARMED: $dst exists but is NOT EXECUTABLE - git skips it silently."
    return 1
  fi
  if ! grep -q "$MARKER" "$dst" 2>/dev/null; then
    echo "UNARMED: $dst runs, but does not post to $MARKER, so DWB is never told."
    return 1
  fi
  echo "ARMED: $dst -> posts to $MARKER"
  return 0
}

if [[ "${1:-}" == "--check" ]]; then
  # Read-only. Changes nothing, installs nothing.
  check_armed
  exit $?
fi

if [[ ! -f "$src" ]]; then
  echo "error: $src is missing; nothing to install." >&2
  exit 1
fi
[[ -x "$src" ]] || chmod +x "$src"

mkdir -p "$hooks_dir"

if [[ -e "$dst" || -L "$dst" ]]; then
  if [[ "$(readlink "$dst" 2>/dev/null || echo)" == "$src" ]]; then
    echo "post-commit hook already linked: $dst -> $src"
  else
    backup="$dst.bak.$(date +%s)"
    mv "$dst" "$backup"
    echo "moved existing hook to $backup"
    ln -s "$src" "$dst"
    echo "installed: $dst -> $src"
  fi
else
  ln -s "$src" "$dst"
  echo "installed: $dst -> $src"
fi

# VERIFY, and fail loudly rather than reporting a success nobody checked.
echo
if check_armed; then
  echo
  echo "Confirm from DWB's side:  GET /api/projects/{id}/hook-status"
  exit 0
fi
echo
echo "error: the hook was written but this clone is still UNARMED (above)." >&2
echo "       Nothing below DWB will see commits from this repository." >&2
exit 1
