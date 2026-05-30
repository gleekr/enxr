#!/usr/bin/env bash
#
# Clone GitHub repo with one-time token input.
# Token stored in Git config (local, not pushed).
#
# Usage:
#   ./clone.sh owner/repo [/path/to/clone]
#
# Example:
#   ./clone.sh gleekr/enxr ~/dev/enxr

set -e

REPO="${1:?missing repo (owner/repo)}"
CLONE_PATH="${2:-$(pwd)/${REPO##*/}}"
REPO_URL="https://github.com/$REPO.git"

# Check if token already stored
TOKEN=$(git config --global github.token 2>/dev/null || true)

if [ -z "$TOKEN" ]; then
    echo "[!] GitHub token not found in git config" >&2
    read -sp "Paste GitHub token (input hidden): " TOKEN
    echo ""

    # Store token in git config (local)
    git config --global github.token "$TOKEN"
    echo "[OK] Token stored in git config" >&2
fi

# Clone with token
CLONE_URL="${REPO_URL#https://}"
CLONE_URL="https://$TOKEN@$CLONE_URL"

echo "[clone] $REPO -> $CLONE_PATH" >&2
git clone "$CLONE_URL" "$CLONE_PATH"
echo "[OK] Cloned to $CLONE_PATH" >&2

cd "$CLONE_PATH"
