#!/usr/bin/env python3
"""
downloader.py -- core download module
Importable by parent project or run standalone.

Usage:
  python3 downloader.py <URL or file> [URL or file ...]
"""

import os, sys, re, shutil, random, tempfile, threading, glob
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional
import yt_dlp
from urllib.parse import urlparse

from config.settings import DEFAULT_DEST, BATCH_DEST, BATCH_WORKERS, BATCH_FRAGMENT_THREADS


# ── Shared download settings ──────────────────────────────────────────────────
# Single source of truth -- _yt_opts and batch _dl_one both extend this.
# Changes here apply everywhere.
_DL_BASE: dict[str, Any] = {
    "format":                        "bestvideo+bestaudio/best",
    "merge_output_format":           "mp4",
    "concurrent_fragment_downloads": 16,
    "buffersize":                    16 * 1024,      # int required (not "16K") via Python API
    "http_chunk_size":               10 * 1024 * 1024,
    "retries":                       10,
    "fragment_retries":              10,
    "throttledratelimit":            100 * 1024,     # re-fetch fragment if speed drops below 100 KB/s
    "socket_timeout":                30,
    "noplaylist":                    True,           # safety -- callers set False when needed
    "extractor_args":               {"youtube": {"player_client": ["web"]}},
}

_HANDLE_RE  = re.compile(r'/@([^/?#]+)')
_CHANNEL_RE = re.compile(r'/(?:channel|c)/([^/?#]+)')
_SLUG_CLEAN = re.compile(r'[^\w\-]')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rand_id(dest: str) -> str:
    """Collision-safe 4-digit ID that doesn't already exist at dest."""
    for _ in range(10000):
        file_id = f"{random.randint(0, 9999):04d}"
        if not os.path.exists(os.path.join(dest, f"{file_id}.mp4")):
            return file_id
    raise RuntimeError(f"no free 4-digit slot in {dest}")


def _yt_opts(dest: str, file_id: str) -> dict[str, Any]:
    return {
        **_DL_BASE,
        "outtmpl":     os.path.join(dest, f"{file_id}.%(ext)s"),
        "quiet":       False,
        "no_warnings": False,
    }


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "ftp://"))


def _detect_playlist(url: str) -> tuple[bool, int]:
    """Flat probe -- returns (is_playlist, count).
    Fast: no download, just metadata. Returns (False, 0) on any error."""
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True, "noplaylist": False}) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(url, download=False)
        entries = info.get("entries")
        return (True, len(entries)) if entries else (False, 1)
    except Exception:
        return (False, 0)


def _copy_file(src: str, dest_dir: str) -> str:
    src = os.path.abspath(os.path.expanduser(src))
    if not os.path.isfile(src):
        raise FileNotFoundError(f"file not found: {src}")
    if not src.lower().endswith(".mp4"):
        raise ValueError(f"not an mp4 file: {src}")

    dest = os.path.join(dest_dir, os.path.basename(src))
    if os.path.abspath(src) == os.path.abspath(dest):
        return dest

    if os.path.exists(dest):
        base, ext = os.path.splitext(os.path.basename(src))
        counter = 1
        while os.path.exists(dest):
            dest = os.path.join(dest_dir, f"{base}_{counter}{ext}")
            counter += 1

    shutil.copy2(src, dest)
    return dest


def _channel_name_from_url(url: str) -> str:
    """Filesystem-safe channel name from a YouTube channel/playlist URL."""
    m = _HANDLE_RE.search(url)
    if m:
        return m.group(1)
    m = _CHANNEL_RE.search(url)
    if m:
        return m.group(1)
    slug = urlparse(url).path.strip('/').replace('/', '_')
    return _SLUG_CLEAN.sub('_', slug) or 'batch'


# ── Public API ────────────────────────────────────────────────────────────────

def download(source: str, dest: str = DEFAULT_DEST) -> str:
    """
    Download a single URL or copy a local mp4 to dest.
    Returns the output path on success, raises on failure.
    """
    os.makedirs(dest, exist_ok=True)

    if _is_url(source):
        file_id = _rand_id(dest)
        with yt_dlp.YoutubeDL(_yt_opts(dest, file_id)) as ydl:  # type: ignore[arg-type]
            ydl.download([source])
        candidates = glob.glob(os.path.join(dest, f"{file_id}.*"))
        mp4 = next((c for c in candidates if c.lower().endswith(".mp4")), None)
        if not mp4:
            raise FileNotFoundError(f"yt-dlp produced no .mp4 output for id {file_id}")
        return mp4
    else:
        return _copy_file(source, dest)


def download_batch(url: str, dest: str = BATCH_DEST,
                   playlist_items: Optional[str] = None) -> tuple[list[str], str]:
    """
    Download videos from a playlist or channel URL.
    Originals land in dest/<channel>/noenx/.
    playlist_items: yt-dlp selection string e.g. "1-50" or "1,3,6,22" or None for all.
    Returns (list_of_paths, channel_dir).
    """
    try:
        os.nice(-5)   # request higher CPU priority (no-op on non-Unix, safe to ignore)
    except Exception:
        pass

    channel     = _channel_name_from_url(url)
    channel_dir = os.path.join(dest, channel)
    noenx_dir   = os.path.join(channel_dir, "noenx")
    os.makedirs(noenx_dir, exist_ok=True)

    # Flat probe respecting playlist_items filter so count is accurate
    print("[batch] fetching playlist...")
    flat_opts: dict[str, Any] = {"quiet": True, "extract_flat": True, "noplaylist": False}
    if playlist_items:
        flat_opts["playlist_items"] = playlist_items
    with yt_dlp.YoutubeDL(flat_opts) as ydl:  # type: ignore[arg-type]
        info    = ydl.extract_info(url, download=False)
    entries = sorted(info.get("entries") or [info],
                     key=lambda e: e.get("view_count") or 0, reverse=True)
    total   = len(entries)
    print(f"[batch] {total} video(s) -- {BATCH_WORKERS} workers x {BATCH_FRAGMENT_THREADS} threads")

    tmp_dir = tempfile.mkdtemp(prefix="enxr_batch_")
    counter = [0]
    lock    = threading.Lock()

    def _dl_one(entry: Any, idx: int) -> Optional[str]:
        vid_id    = entry.get("id", "")
        entry_url = (entry.get("webpage_url")
                     or entry.get("url")
                     or (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else ""))
        if not entry_url:
            return None
        opts: dict[str, Any] = {
            **_DL_BASE,
            "outtmpl":                       os.path.join(tmp_dir, "%(id)s.%(ext)s"),
            "concurrent_fragment_downloads": BATCH_FRAGMENT_THREADS,
            "quiet":                         True,
            "no_warnings":                   True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
                ydl.extract_info(entry_url, download=True)
            candidates = glob.glob(os.path.join(tmp_dir, f"{vid_id}.*"))
            mp4 = next((c for c in candidates if c.lower().endswith(".mp4")), None)
            if mp4:
                with lock:
                    counter[0] += 1
                    print(f"  [{counter[0]}/{total}] {vid_id}")
                return mp4
        except Exception as e:
            print(f"  [!] {idx}/{total} failed: {e}")
        return None

    try:
        tmp_files: list[str] = []
        with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as executor:
            futures = {executor.submit(_dl_one, e, i + 1): i
                       for i, e in enumerate(entries)}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    tmp_files.append(result)

        downloaded: list[str] = []
        for tmp_path in sorted(tmp_files):
            file_id  = _rand_id(noenx_dir)
            out_path = os.path.join(noenx_dir, f"{file_id}.mp4")
            shutil.move(tmp_path, out_path)
            downloaded.append(out_path)
            print(f"[OK] {channel}/noenx/{file_id}.mp4")

        return downloaded, channel_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── CLI ───────────────────────────────────────────────────────────────────────
def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if args else 1)

    errors = []
    for source in args:
        try:
            if _is_url(source):
                is_playlist, count = _detect_playlist(source)
                if is_playlist:
                    print(f"[playlist] {count} video(s) detected -- downloading all to {BATCH_DEST}")
                    files, _ = download_batch(source)
                    for f in files:
                        print(f"[OK] {f}")
                    continue
            out = download(source)
            print(f"[OK] {out}")
        except Exception as e:
            print(f"[!] {source}\n    {e}", file=sys.stderr)
            errors.append(source)

    print(f"\n{len(args) - len(errors)}/{len(args)} completed.")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
