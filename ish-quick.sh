#!/usr/bin/env sh
# One-liner iSH setup (paste into terminal):
# curl -fsSL https://raw.githubusercontent.com/gleekr/enxr/master/ish-quick.sh | sh

echo "http://mirror.math.princeton.edu/pub/alpinelinux/latest-stable/main" > /etc/apk/repositories
echo "http://mirror.math.princeton.edu/pub/alpinelinux/latest-stable/community" >> /etc/apk/repositories
apk update && apk add --no-cache git python3 py3-pip ffmpeg curl wget nano github-cli && pip3 install -q yt-dlp && echo "[OK] ready"
