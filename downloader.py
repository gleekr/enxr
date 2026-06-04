#!/usr/bin/env python3
"""downloader.py -- yt-dlp fetch utility (single video)"""
import os, shutil, subprocess, time

from config import DEFAULT_DEST, COOKIE_BROWSER, COOKIE_FILE, POT_SERVER_URL, YT_PLAYER_CLIENTS


def _get_yt_dlp_path() -> str:
    path = shutil.which("yt-dlp")
    if path is None:
        raise FileNotFoundError("yt-dlp not found -- install it and ensure it is on PATH")
    return path


def _ytdlp(fmt: str = "mp4", client: str = "web") -> list[str]:
    merge_fmt = "webm" if fmt == "webm" else "mp4"
    args = [
        _get_yt_dlp_path(),
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
    if COOKIE_BROWSER:
        args += ["--cookies-from-browser", COOKIE_BROWSER]
    elif COOKIE_FILE:
        args += ["--cookies", COOKIE_FILE]
    return args


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "ftp://"))


def download(url: str, dest: str = DEFAULT_DEST, fmt: str = "mp4") -> str | None:
    os.makedirs(dest, exist_ok=True)
    outtmpl = os.path.join(dest, "%(id)s.%(ext)s")
    start_ts = time.time()
    last_error = None

    for client in YT_PLAYER_CLIENTS:
        cmd = _ytdlp(fmt, client) + ["-o", outtmpl, "--print", "after_move:filepath", url]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = proc.communicate(timeout=1800)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise RuntimeError("yt-dlp timed out after 30 minutes")

        if proc.returncode == 0:
            lines = [l.strip() for l in stdout.splitlines() if l.strip()]
            if lines:
                return lines[-1]
            candidates = [os.path.join(dest, f) for f in os.listdir(dest)
                          if os.path.isfile(os.path.join(dest, f))
                          and os.path.getmtime(os.path.join(dest, f)) >= start_ts]
            return max(candidates, key=os.path.getmtime) if candidates else None

        last_error = stderr.strip() or stdout.strip()
        print(f"[yt-dlp] {client} failed, trying next client...")

    raise RuntimeError(f"yt-dlp failed (all clients exhausted): {last_error}")
