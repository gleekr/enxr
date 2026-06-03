#!/usr/bin/env python3
"""downloader.py -- yt-dlp fetch utility (single video)"""
import os, subprocess

from config import DEFAULT_DEST, COOKIE_BROWSER, COOKIE_FILE, POT_SERVER_URL


def _ytdlp(fmt: str = "mp4", cookie_browser: str | None = None) -> list[str]:
    browser = cookie_browser or COOKIE_BROWSER
    client = "mweb" if POT_SERVER_URL else "android"
    merge_fmt = "webm" if fmt == "webm" else "mp4"
    args = [
        "yt-dlp",
        "-f", "bv*+ba/bv*/b",
        "--merge-output-format", merge_fmt,
        "--concurrent-fragments", "16",
        "--retries", "10",
        "--fragment-retries", "10",
        "--throttled-rate", "100K",
        "--socket-timeout", "30",
        "--no-playlist",
        "--extractor-args", f"youtube:player_client={client}",
    ]
    if POT_SERVER_URL:
        args += ["--extractor-args", f"youtubepot-bgutilhttp:base_url={POT_SERVER_URL}"]
    if browser:
        args += ["--cookies-from-browser", browser]
    elif COOKIE_FILE:
        args += ["--cookies", COOKIE_FILE]
    return args


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "ftp://"))


def download(url: str, dest: str = DEFAULT_DEST, fmt: str = "mp4",
             cookie_browser: str | None = None) -> str | None:
    os.makedirs(dest, exist_ok=True)
    outtmpl = os.path.join(dest, "%(id)s.%(ext)s")
    cmd = _ytdlp(fmt, cookie_browser) + ["-o", outtmpl, "--print", "after_move:filepath", url]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    stdout, _ = proc.communicate()
    lines = [l.strip() for l in stdout.splitlines() if l.strip()]
    return lines[-1] if proc.returncode == 0 and lines else None
