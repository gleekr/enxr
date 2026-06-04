#!/usr/bin/env bash
# Pull latest from public GitHub (no auth needed).
# Run from inside the repo, or pass a path.
# Usage: ./pull.sh [/path/to/repo] [branch]

set -e

REPO_PATH="${1:-$(pwd)}"
BRANCH="${2:-}"

cd "$REPO_PATH"

if [ -n "$BRANCH" ]; then
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    git pull
fi

echo "[OK] up to date: $(git rev-parse --short HEAD) ($(git branch --show-current))"
