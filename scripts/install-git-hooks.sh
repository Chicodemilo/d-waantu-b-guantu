#!/usr/bin/env bash
# Path: scripts/install-git-hooks.sh
# Created: 2026-06-10
# Purpose: Symlink .git/hooks/post-commit to scripts/hooks/post-commit so
#   the auto-close hook (DWB-345) is version-controlled and shared across
#   every clone. Run once per fresh checkout.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
src="$repo_root/scripts/hooks/post-commit"
dst="$repo_root/.git/hooks/post-commit"

if [[ ! -x "$src" ]]; then
  chmod +x "$src"
fi

if [[ -e "$dst" || -L "$dst" ]]; then
  if [[ "$(readlink "$dst" 2>/dev/null || echo)" == "$src" ]]; then
    echo "post-commit hook already linked: $dst -> $src"
    exit 0
  fi
  backup="$dst.bak.$(date +%s)"
  mv "$dst" "$backup"
  echo "moved existing hook to $backup"
fi

ln -s "$src" "$dst"
echo "installed: $dst -> $src"
