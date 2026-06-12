#!/usr/bin/env python3
"""downloader.py -- yt-dlp fetch utility (single video), nightly auto-update build"""
import os, shutil, subprocess, sys, time
from pathlib import Path

from config import DEFAULT_DEST, COOKIE_BROWSER, COOKIE_FILE, POT_SERVER_URL, YT_PLAYER_CLIENTS

_YTDLP_CACHE = Path.home() / ".enxr" / "yt-dlp-nightly"
_TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo" -- always available
_resolved: tuple[list[str], dict | None] | None = None  # cached per process


def _fetch_nightly() -> bool:
    """Update cached nightly from GitHub. Never raises; False means use cache."""
    _YTDLP_CACHE.mkdir(parents=True, exist_ok=True)
    try:
        print("[yt-dlp] fetching latest nightly...", flush=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "--upgrade",
             "--target", str(_YTDLP_CACHE),
             "git+https://github.com/yt-dlp/yt-dlp.git"],
            check=True, timeout=120)
        print("[yt-dlp] nightly ready", flush=True)
        return True
    except Exception:
        print("[yt-dlp] fetch failed, using cached/system version", flush=True)
        return False


def _categorize_error(stderr: str) -> str:
    """Parse stderr to identify root cause: YouTube, yt-dlp, or local code."""
    if "Video unavailable" in stderr or "not available" in stderr.lower():
        return "yt: video unavailable (YouTube blocking or region restriction)"
    if "429" in stderr or "Too Many Requests" in stderr:
        return "yt: rate limited (YouTube rejecting requests)"
    if "Signature extraction failed" in stderr or "n parameter extraction failed" in stderr:
        return "yt: YouTube updated, yt-dlp out of sync (needs newer nightly)"
    if "ExtractorError" in stderr:
        return "ytdlp: extractor error (yt-dlp bug)"
    if "No such file" in stderr or "not found" in stderr.lower():
        return "broken code: yt-dlp binary not found"
    if "Permission denied" in stderr:
        return "broken code: permission denied on yt-dlp"
    if "connection" in stderr.lower():
        return "yt: network error (no internet or YouTube server down)"
    lines = [l.strip() for l in stderr.strip().split('\n') if l.strip()]
    if lines:
        return f"ytdlp: {lines[-1][:60]}"
    return "ytdlp: unknown error"


def _test_startup(cmd: list[str], env: dict | None) -> None:
    """Probe a known-good URL with the version we fell back to; warn with diagnosis."""
    try:
        result = subprocess.run(
            cmd + ["--quiet", "--no-warnings", "-O", "duration", _TEST_URL],
            capture_output=True, text=True, timeout=30, env=env)
        if result.returncode != 0:
            print(f"[yt-dlp] startup test FAILED: {_categorize_error(result.stderr)}", flush=True)
            print(f"   tested: {_TEST_URL}", flush=True)
    except subprocess.TimeoutExpired:
        print("[yt-dlp] startup test timeout (YouTube or network slow)", flush=True)
    except Exception:
        pass  # diagnostic only -- never block a real download


def _yt_dlp_invocation() -> tuple[list[str], dict | None]:
    """Resolve yt-dlp once per process: cached nightly first, system PATH second."""
    global _resolved
    if _resolved is not None:
        return _resolved

    updated = _fetch_nightly()
    if (_YTDLP_CACHE / "yt_dlp").exists():
        cmd = [sys.executable, "-m", "yt_dlp"]
        env = {**os.environ, "PYTHONPATH": str(_YTDLP_CACHE)}
    else:
        path = shutil.which("yt-dlp")
        if path is None:
            raise FileNotFoundError(
                "yt-dlp not found -- no cached nightly and nothing on PATH")
        cmd, env = [path], None

    if not updated:
        _test_startup(cmd, env)
    _resolved = (cmd, env)
    return _resolved


def _ytdlp(fmt: str = "mp4", client: str = "web") -> tuple[list[str], dict | None]:
    cmd, env = _yt_dlp_invocation()
    merge_fmt = "webm" if fmt == "webm" else "mp4"
    args = cmd + [
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
    return args, env


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "ftp://"))


def download(url: str, dest: str = DEFAULT_DEST, fmt: str = "mp4") -> str | None:
    os.makedirs(dest, exist_ok=True)
    outtmpl = os.path.join(dest, "%(id)s.%(ext)s")
    start_ts = time.time()
    last_error = None

    for client in YT_PLAYER_CLIENTS:
        args, env = _ytdlp(fmt, client)
        cmd = args + ["-o", outtmpl, "--print", "after_move:filepath", url]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=env)
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
        print(f"[yt-dlp] {client} failed ({_categorize_error(stderr)}), trying next client...")

    raise RuntimeError(f"yt-dlp failed (all clients exhausted): {last_error}")
