#!/usr/bin/env sh
#
# iSH Alpine setup: fastest installs + essentials for enxr
#
# Usage: ./ish-setup.sh
# Or: sh ish-setup.sh (if chmod fails)

set -e

echo "[setup] iSH Alpine optimization"

# Use fastest Alpine mirrors (parallel + CDN)
echo "http://mirror.math.princeton.edu/pub/alpinelinux/latest-stable/main" > /etc/apk/repositories
echo "http://mirror.math.princeton.edu/pub/alpinelinux/latest-stable/community" >> /etc/apk/repositories

# Update repos
echo "[apk] updating repos..."
apk update

# Install essentials in one batch (faster than individual installs)
echo "[apk] installing essentials..."
apk add --no-cache \
    git \
    python3 \
    py3-pip \
    ffmpeg \
    curl \
    wget \
    nano \
    github-cli

# Speed up pip (parallel downloads)
echo "[pip] configuring for speed..."
mkdir -p ~/.config/pip
cat > ~/.config/pip/pip.conf << EOF
[global]
index-url = https://pypi.org/simple/
disable-pip-version-check = true
EOF

# Install yt-dlp
echo "[pip] installing yt-dlp..."
pip3 install -q yt-dlp

echo "[OK] iSH setup complete"
echo ""
echo "Next steps:"
echo "  1. gh auth login    # one-time GitHub auth"
echo "  2. gh repo clone <owner>/<repo> <path>"
echo ""
