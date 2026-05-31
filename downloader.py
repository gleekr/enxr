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

from config import (DEFAULT_DEST, BATCH_OG, BATCH_WORKERS,
                    BATCH_FRAGMENT_THREADS, YT_PLAYER_CLIENT,
                    YT_PLAYER_CLIENT_FALLBACK, COOKIE_BROWSER, COOKIE_FILE)


# ── Shared download settings ──────────────────────────────────────────────────
# Single source of truth -- _yt_opts and batch _dl_one both extend this.
# Changes here apply everywhere.
_DL_BASE: dict[str, Any] = {
    **({"cookiesfrombrowser": (COOKIE_BROWSER,)} if COOKIE_BROWSER else
       {"cookiefile": COOKIE_FILE}               if COOKIE_FILE    else {}),
    # Video quality is the priority. Prefer best video + best audio merged;
    # if no separate audio (or merge impossible), take the best video-only
    # stream; only then fall back to the best pre-muxed format. A silent but
    # higher-resolution video beats a lower-resolution one with sound.
    "format":                        "bv*+ba/bv*/b",
    "merge_output_format":           "mp4",
    "concurrent_fragment_downloads": 16,
    "buffersize":                    16 * 1024,      # int required (not "16K") via Python API
    "http_chunk_size":               10 * 1024 * 1024,
    "retries":                       10,
    "fragment_retries":              10,
    "throttledratelimit":            100 * 1024,     # re-fetch fragment if speed drops below 100 KB/s
    "socket_timeout":                30,
    "noplaylist":                    True,           # safety -- callers set False when needed
    # player_client controls which YouTube clients yt-dlp extracts with -- see
    # _client_args() and config.settings.YT_PLAYER_CLIENT for the rationale.
    "extractor_args":               {"youtube": {"player_client": list(YT_PLAYER_CLIENT)}},
}

_HANDLE_RE  = re.compile(r'/@([^/?#]+)')
_CHANNEL_RE = re.compile(r'/(?:channel|c)/([^/?#]+)')
_SLUG_CLEAN = re.compile(r'[^\w\-]')


def _client_args(clients: list) -> dict[str, Any]:
    """extractor_args dict pinning yt-dlp to the given YouTube player clients."""
    return {"youtube": {"player_client": list(clients)}}


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
        probe_opts = {"quiet": True, "extract_flat": True, "noplaylist": False,
                      "extractor_args": _client_args(YT_PLAYER_CLIENT)}
        with yt_dlp.YoutubeDL(probe_opts) as ydl:  # type: ignore[arg-type]
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


def _parse_selection(selection_str: str, total: int) -> list[int]:
    """Parse selection string like '3,2,7,23-30,25-59' into sorted unique indices (0-based)."""
    indices = set()
    for part in selection_str.split(','):
        part = part.strip()
        if '-' in part:
            try:
                start, end = part.split('-')
                start, end = int(start.strip()), int(end.strip())
                for i in range(start, end + 1):
                    if 1 <= i <= total:
                        indices.add(i - 1)
            except ValueError:
                pass
        else:
            try:
                i = int(part)
                if 1 <= i <= total:
                    indices.add(i - 1)
            except ValueError:
                pass
    return sorted(indices)


# ── Public API ────────────────────────────────────────────────────────────────

def download(source: str, dest: str = DEFAULT_DEST) -> str:
    """
    Download a single URL or copy a local mp4 to dest.
    Returns the output path on success, raises on failure.
    """
    os.makedirs(dest, exist_ok=True)

    if not _is_url(source):
        return _copy_file(source, dest)

    file_id = _rand_id(dest)
    opts    = _yt_opts(dest, file_id)

    def _attempt() -> Optional[str]:
        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
            ydl.download([source])
        candidates = glob.glob(os.path.join(dest, f"{file_id}.*"))
        return next((c for c in candidates if c.lower().endswith(".mp4")), None)

    try:
        mp4 = _attempt()
    except Exception:
        mp4 = None

    if not mp4:
        # primary clients (ios/tv) failed -- retry once with web fallback
        print("[yt-dlp] ios/tv extraction failed, retrying with web client "
              "(may briefly open the YouTube app)")
        opts["extractor_args"] = _client_args(YT_PLAYER_CLIENT_FALLBACK)
        mp4 = _attempt()

    if not mp4:
        raise FileNotFoundError(f"yt-dlp produced no .mp4 output for id {file_id}")
    return mp4


def download_batch(url: str, dest: str = BATCH_OG,
                   playlist_items: Optional[str] = None) -> tuple[list[str], str]:
    """
    Download videos from a playlist or channel URL.
    Originals land in dest/<channel>/ (dest defaults to BATCH_OG).
    playlist_items: yt-dlp selection string e.g. "1-50" or "1,3,6,22" or None for all.
    Returns (list_of_paths, channel_dir).
    """
    try:
        os.nice(-5)   # request higher CPU priority (no-op on non-Unix, safe to ignore)
    except Exception:
        pass

    channel     = _channel_name_from_url(url)
    channel_dir = os.path.join(dest, channel)
    os.makedirs(channel_dir, exist_ok=True)

    # Flat probe respecting playlist_items filter so count is accurate.
    # Pin the same player clients here -- the probe also opens the YouTube app
    # at fetch time if it falls back to the default web/mweb clients.
    print("[batch] fetching playlist...")
    flat_opts: dict[str, Any] = {
        "quiet": True, "extract_flat": True, "noplaylist": False,
        "extractor_args": _client_args(YT_PLAYER_CLIENT),
    }
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
    # Persistent archive of downloaded video IDs -- re-running a channel skips
    # videos already grabbed, so you only pull new Shorts.
    archive_path = os.path.join(channel_dir, ".dlarchive")

    def _dl_one(entry: Any, idx: int) -> Optional[str]:
        vid_id    = entry.get("id", "")
        entry_url = (entry.get("webpage_url")
                     or entry.get("url")
                     or (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else ""))
        if not entry_url:
            return None

        def _attempt(clients: list) -> Optional[str]:
            opts: dict[str, Any] = {
                **_DL_BASE,
                "outtmpl":                       os.path.join(tmp_dir, "%(id)s.%(ext)s"),
                "concurrent_fragment_downloads": BATCH_FRAGMENT_THREADS,
                "quiet":                         True,
                "no_warnings":                   True,
                "extractor_args":                _client_args(clients),
                "download_archive":              archive_path,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
                ydl.extract_info(entry_url, download=True)
            candidates = glob.glob(os.path.join(tmp_dir, f"{vid_id}.*"))
            return next((c for c in candidates if c.lower().endswith(".mp4")), None)

        mp4 = None
        try:
            mp4 = _attempt(YT_PLAYER_CLIENT)
        except Exception:
            pass  # primary failed -- fall through to web fallback below
        if not mp4:
            try:
                mp4 = _attempt(YT_PLAYER_CLIENT_FALLBACK)
            except Exception as e:
                print(f"  [!] {idx}/{total} failed: {e}")
                return None
        if mp4:
            with lock:
                counter[0] += 1
                print(f"  [{counter[0]}/{total}] {vid_id}")
            return mp4
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
            file_id  = _rand_id(channel_dir)
            out_path = os.path.join(channel_dir, f"{file_id}.mp4")
            shutil.move(tmp_path, out_path)
            downloaded.append(out_path)
            print(f"[OK] {channel}/{file_id}.mp4")

        return downloaded, channel_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Interactive channel selector ──────────────────────────────────────────────

def download_channel_interactive(url: str, dest: str = BATCH_OG) -> tuple[list[str], list[int]]:
    """
    Interactive batch downloader with selection prompt.
    Returns (downloaded_paths, failed_indices).
    """
    print("\n[batch] fetching playlist metadata...")
    flat_opts = {
        "quiet": True, "extract_flat": True, "noplaylist": False,
        "extractor_args": _client_args(YT_PLAYER_CLIENT),
    }
    with yt_dlp.YoutubeDL(flat_opts) as ydl:  # type: ignore[arg-type]
        info = ydl.extract_info(url, download=False)
    entries = sorted(info.get("entries") or [info],
                     key=lambda e: e.get("view_count") or 0, reverse=True)
    total = len(entries)

    print(f"\n[batch] {total} video(s) found (sorted by popular)\n")
    print("  1. Download all")
    print("  2. First # videos")
    print("  3. Specify: 3,6,8,9-18,34-50")

    choice = input("\nChoice [1-3]: ").strip()

    if choice == '2':
        raw = input(f"First how many? [1-{total}]: ").strip()
        count = int(raw) if raw.isdigit() and 0 < int(raw) <= total else total
        selection = list(range(count))
    elif choice == '3':
        spec = input("Select (e.g. 3,6,8,9-18,34-50): ").strip()
        selection = _parse_selection(spec, total)
        if not selection:
            print("[batch] no valid selection -- downloading all")
            selection = list(range(total))
    else:
        selection = list(range(total))

    filtered_entries = [entries[i] for i in selection if i < total]
    print(f"\n[download] {len(filtered_entries)} video(s) queued -- {BATCH_WORKERS} workers\n")

    channel = _channel_name_from_url(url)
    channel_dir = os.path.join(dest, channel)
    os.makedirs(channel_dir, exist_ok=True)

    tmp_dir = tempfile.mkdtemp(prefix="enxr_batch_")
    total_sel = len(filtered_entries)
    counter = [0]
    lock = threading.Lock()
    failed_indices = []
    archive_path = os.path.join(channel_dir, ".dlarchive")

    def _dl_one(entry: Any, orig_idx: int) -> Optional[str]:
        vid_id = entry.get("id", "")
        entry_url = (entry.get("webpage_url") or entry.get("url")
                     or (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else ""))
        if not entry_url:
            with lock:
                failed_indices.append(orig_idx)
            return None

        def _attempt(clients: list) -> Optional[str]:
            opts = {
                **_DL_BASE,
                "outtmpl": os.path.join(tmp_dir, "%(id)s.%(ext)s"),
                "concurrent_fragment_downloads": BATCH_FRAGMENT_THREADS,
                "quiet": True,
                "no_warnings": True,
                "extractor_args": _client_args(clients),
                "download_archive": archive_path,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
                ydl.extract_info(entry_url, download=True)
            candidates = glob.glob(os.path.join(tmp_dir, f"{vid_id}.*"))
            return next((c for c in candidates if c.lower().endswith(".mp4")), None)

        try:
            mp4 = _attempt(YT_PLAYER_CLIENT)
        except Exception:
            mp4 = None

        if not mp4:
            try:
                mp4 = _attempt(YT_PLAYER_CLIENT_FALLBACK)
            except Exception:
                with lock:
                    failed_indices.append(orig_idx)
                return None

        if mp4:
            with lock:
                counter[0] += 1
                print(f"  [{counter[0]}/{total_sel}] {vid_id}")
            return mp4
        return None

    try:
        tmp_files = []
        with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as executor:
            futures = {executor.submit(_dl_one, e, i + 1): i
                       for i, e in enumerate(filtered_entries)}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    tmp_files.append(result)

        downloaded = []
        for tmp_path in sorted(tmp_files):
            file_id = _rand_id(channel_dir)
            out_path = os.path.join(channel_dir, f"{file_id}.mp4")
            shutil.move(tmp_path, out_path)
            downloaded.append(out_path)
            print(f"[OK] {channel}/{file_id}.mp4")

        if failed_indices:
            print(f"\n[!] Failed: {', '.join(map(str, sorted(set(failed_indices))))}")

        return downloaded, sorted(set(failed_indices))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── CLI ───────────────────────────────────────────────────────────────────────
def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if args else 1)

    errors = []
    all_downloaded = []

    for source in args:
        try:
            if _is_url(source):
                u = source.lower()
                is_batch_url = any(x in u for x in
                                   ("/shorts", "/videos", "/playlist", "/@", "/channel/", "/c/"))
                if is_batch_url:
                    downloaded, failed = download_channel_interactive(source)
                    all_downloaded.extend(downloaded)
                    if failed:
                        print(f"[!] {len(failed)} failed: {', '.join(map(str, failed))}")
                    continue

                is_playlist, count = _detect_playlist(source)
                if is_playlist and count > 1:
                    print(f"\n[batch] {count} video(s) detected")
                    downloaded, failed = download_channel_interactive(source)
                    all_downloaded.extend(downloaded)
                    if failed:
                        print(f"[!] {len(failed)} failed: {', '.join(map(str, failed))}")
                    continue

            out = download(source)
            print(f"[OK] {out}")
            all_downloaded.append(out)
        except Exception as e:
            print(f"[!] {source}\n    {e}", file=sys.stderr)
            errors.append(source)

    if all_downloaded:
        choice = input(f"\n[enhance] Enhance batch? (Y/N): ").strip().upper()

        if choice == 'Y':
            print(f"\n[enhance] {len(all_downloaded)} video(s) downloaded")
            print("  1. All")
            print("  2. Specify range (e.g., 4-9, 3, 21)")
            print("  3. Cancel")
            select = input("\nSelect [1-3]: ").strip()

            to_enhance = None
            if select == '1':
                to_enhance = all_downloaded
            elif select == '2':
                ranges = input("Indices (e.g., 4-9, 3, 21): ").strip()
                indices = _parse_selection(ranges, len(all_downloaded))
                to_enhance = [all_downloaded[i] for i in indices if i < len(all_downloaded)]
            else:
                print("[enhance] cancelled")
                to_enhance = None

            if to_enhance:
                print(f"\n[enhancing] {len(to_enhance)} video(s)...")
                try:
                    from ffmpeg import enhance as enhance_video
                    for i, path in enumerate(to_enhance, 1):
                        try:
                            out = enhance_video(path, restore_level=2, enhance_level=3)
                            print(f"[{i}/{len(to_enhance)}] {out}")
                        except Exception as e:
                            print(f"[!] {path}: {e}", file=sys.stderr)
                except ImportError:
                    print("[!] ffmpeg module not found -- skipping enhance")

    print(f"\n{len(args) - len(errors)}/{len(args)} completed.")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
