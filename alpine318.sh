#!/bin/sh
# alpine318.sh -- upgrade iSH to Alpine 3.18 + install enxr deps
# Run with:  sh alpine318.sh
# Uses printf (no quotes/brackets) to dodge iOS smart-punctuation mangling.

set -e

echo "[1/5] pointing repos at Alpine v3.18..."
printf '%s\n' \
  http://dl-cdn.alpinelinux.org/alpine/v3.18/main \
  http://dl-cdn.alpinelinux.org/alpine/v3.18/community \
  > /etc/apk/repositories

echo "[2/5] repo file now contains:"
cat /etc/apk/repositories

echo "[3/5] apk update + upgrade to 3.18 (this takes a bit)..."
apk update
apk upgrade --available

echo "[4/5] installing project deps: git python3 py3-pip ffmpeg..."
apk add --no-cache git python3 py3-pip ffmpeg

echo "[5/5] installing yt-dlp..."
pip3 install -q --upgrade yt-dlp

echo ""
echo "================  DONE  ================"
echo "Alpine: $(cat /etc/alpine-release)"
echo "Python: $(python3 --version)"
echo "ffmpeg: $(ffmpeg -version 2>/dev/null | head -n1)"
echo "yt-dlp: $(yt-dlp --version 2>/dev/null)"
echo "======================================="
echo ""
echo "Next: git clone https://github.com/gleekr/enxr.git"
