#!/usr/bin/env python3
"""downloader.py -- yt-dlp CLI wrapper"""
import json, os, re, subprocess, sys

from config import DEFAULT_DEST, BATCH_OG, COOKIE_BROWSER, COOKIE_FILE, POT_SERVER_URL


def _ytdlp() -> list[str]:
    client = "mweb" if POT_SERVER_URL else "android"
    args = [
        "yt-dlp",
        "-f", "bv*+ba/bv*/b",
        "--merge-output-format", "mp4",
        "--concurrent-fragments", "16",
        "--retries", "10",
        "--fragment-retries", "10",
        "--throttled-rate", "100K",
        "--socket-timeout", "30",
        "--extractor-args", f"youtube:player_client={client}",
    ]
    if POT_SERVER_URL:
        args += ["--extractor-args", f"youtubepot-bgutilhttp:base_url={POT_SERVER_URL}"]
    if COOKIE_BROWSER:
        args += ["--cookies-from-browser", COOKIE_BROWSER]
    elif COOKIE_FILE:
        args += ["--cookies", COOKIE_FILE]
    return args


def _probe(url: str) -> int:
    cmd = _ytdlp() + ["--flat-playlist", "-J", "--quiet", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return len(json.loads(r.stdout).get("entries") or [])
    except Exception:
        return 0


def _channel_dir(url: str, dest: str) -> str:
    m = re.search(r'/@([^/?#]+)|/(?:channel|c)/([^/?#]+)', url)
    name = next((g for g in m.groups() if g), "batch") if m else "batch"
    return os.path.join(dest, name)


def download(url: str, dest: str = DEFAULT_DEST) -> str | None:
    os.makedirs(dest, exist_ok=True)
    outtmpl = os.path.join(dest, "%(id)s.%(ext)s")
    cmd = _ytdlp() + ["--no-playlist", "-o", outtmpl, "--print", "after_move:filepath", url]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    stdout, _ = proc.communicate()
    lines = [l.strip() for l in stdout.splitlines() if l.strip()]
    return lines[-1] if proc.returncode == 0 and lines else None


def download_batch(url: str, dest: str = BATCH_OG,
                   playlist_items: str | None = None) -> tuple[list[str], str]:
    channel_dir = _channel_dir(url, dest)
    os.makedirs(channel_dir, exist_ok=True)
    outtmpl = os.path.join(channel_dir, "%(id)s.%(ext)s")
    cmd = _ytdlp() + ["-o", outtmpl, "--print", "after_move:filepath", url]
    if playlist_items:
        cmd += ["--playlist-items", playlist_items]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    stdout, _ = proc.communicate()
    files = [l.strip() for l in stdout.splitlines() if l.strip()] if proc.returncode == 0 else []
    return files, channel_dir


def download_channel_interactive(url: str, dest: str = BATCH_OG) -> None:
    print("\n[batch] fetching playlist info...")
    total = _probe(url)
    if not total:
        print("[batch] no entries found")
        return

    print(f"\n[batch] {total} video(s) found\n")
    print("  1. Download all")
    print("  2. First # videos")
    print("  3. Specify: 3,6,8,9-18,34-50")

    choice = input("\nChoice [1-3]: ").strip()
    if choice == "2":
        raw = input(f"First how many? [1-{total}]: ").strip()
        n = int(raw) if raw.isdigit() and 0 < int(raw) <= total else total
        playlist_items = f"1-{n}"
    elif choice == "3":
        playlist_items = input("Select (e.g. 3,6,8,9-18,34-50): ").strip() or None
    else:
        playlist_items = None

    download_batch(url, dest, playlist_items)


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if args else 1)

    for url in args:
        u = url.lower()
        is_batch = any(x in u for x in ("/shorts", "/videos", "/playlist", "/@", "/channel/", "/c/"))
        if is_batch:
            download_channel_interactive(url)
        else:
            download(url)


if __name__ == "__main__":
    main()
