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

# Install only project dependencies (one batch for speed)
# Python 3.10+
echo "[apk] installing dependencies..."
apk add --no-cache \
    git \
    python3.10 \
    py3.10-pip \
    ffmpeg

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
pip3.10 install -q yt-dlp

echo "[OK] iSH setup complete"
echo ""
echo "Next: clone enxr"
echo "  git clone https://github.com/gleekr/enxr.git ~/enxr"
echo ""
