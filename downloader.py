#!/usr/bin/env python3
"""
downloader.py — core download module
Importable by parent project or run standalone.

Usage:
  python3 downloader.py <URL or file> [URL or file ...]
"""

import os, sys, re, shutil, random, tempfile, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import yt_dlp
from urllib.parse import urlparse

from config.settings import DEFAULT_DEST, BATCH_DEST, BATCH_WORKERS, BATCH_FRAGMENT_THREADS


def _rand_id(dest: str) -> str:
    # generate a random 4-digit ID that doesn't already exist at dest
    # avoids silent overwrite in batch downloads
    while True:
        file_id = f"{random.randint(0, 9999):04d}"
        if not os.path.exists(os.path.join(dest, f"{file_id}.mp4")):
            return file_id


def _yt_opts(dest: str, file_id: str) -> dict:
    return {
        "format":                        "bestvideo+bestaudio/best",
        "merge_output_format":           "mp4",
        "outtmpl":                       os.path.join(dest, f"{file_id}.%(ext)s"),
        "noplaylist":                    True,
        "concurrent_fragment_downloads": 16,
        "buffersize":                    16 * 1024,  # must be int when passed programmatically; "16K" only works via CLI
        "http_chunk_size":               10 * 1024 * 1024,
        "quiet":                         False,
        "no_warnings":                   False,
    }


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "ftp://"))


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


def download(source: str, dest: str = DEFAULT_DEST) -> str:
    """
    Download a URL or copy a local mp4 to dest.
    Returns the output path on success, raises on failure.
    """
    os.makedirs(dest, exist_ok=True)

    if _is_url(source):
        file_id  = _rand_id(dest)       # collision-safe ID
        out_path = os.path.join(dest, f"{file_id}.mp4")
        with yt_dlp.YoutubeDL(_yt_opts(dest, file_id)) as ydl:
            ydl.download([source])
        return out_path
    else:
        return _copy_file(source, dest)


def _channel_name_from_url(url: str) -> str:
    """Extract a filesystem-safe channel name from a YouTube channel URL."""
    m = re.search(r'/@([^/?#]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'/(?:channel|c)/([^/?#]+)', url)
    if m:
        return m.group(1)
    slug = urlparse(url).path.strip('/').replace('/', '_')
    return re.sub(r'[^\w\-]', '_', slug) or 'batch'


def download_batch(url: str, dest: str = BATCH_DEST,
                   playlist_items: str = None) -> tuple:
    """
    Download videos from a playlist or channel URL.
    Originals land in dest/<channel>/noenx/.
    playlist_items: yt-dlp selection string e.g. "1-50" or "1,3,6,22" or None for all.
    Returns (list_of_paths, channel_dir).
    """
    # Request higher CPU priority for a-shell
    try:
        os.nice(-5)
    except Exception:
        pass

    channel     = _channel_name_from_url(url)
    channel_dir = os.path.join(dest, channel)
    noenx_dir   = os.path.join(channel_dir, "noenx")
    os.makedirs(noenx_dir, exist_ok=True)

    # Fetch flat playlist to know what we're downloading before starting
    print("[batch] fetching playlist...")
    flat_opts = {"quiet": True, "extract_flat": True, "noplaylist": False}
    if playlist_items:
        flat_opts["playlist_items"] = playlist_items
    with yt_dlp.YoutubeDL(flat_opts) as ydl:
        info    = ydl.extract_info(url, download=False)
    entries = info.get("entries") or [info]
    total   = len(entries)
    print(f"[batch] {total} video(s) -- {BATCH_WORKERS} workers x {BATCH_FRAGMENT_THREADS} threads")

    tmp_dir = tempfile.mkdtemp(prefix="enxr_batch_")
    counter = [0]
    lock    = threading.Lock()

    def _dl_one(entry, idx):
        vid_id    = entry.get("id", "")
        entry_url = (f"https://www.youtube.com/watch?v={vid_id}"
                     if vid_id else entry.get("url", ""))
        if not entry_url:
            return None
        opts = {
            "format":                        "bestvideo+bestaudio/best",
            "merge_output_format":           "mp4",
            "outtmpl":                       os.path.join(tmp_dir, "%(id)s.%(ext)s"),
            "noplaylist":                    True,
            "concurrent_fragment_downloads": BATCH_FRAGMENT_THREADS,
            "buffersize":                    16 * 1024,
            "http_chunk_size":               10 * 1024 * 1024,
            "quiet":                         True,
            "no_warnings":                   True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(entry_url, download=True)
            fname = os.path.join(tmp_dir, f"{vid_id}.mp4")
            if os.path.exists(fname):
                with lock:
                    counter[0] += 1
                    print(f"  [{counter[0]}/{total}] {vid_id}")
                return fname
        except Exception as e:
            print(f"  [!] {idx}/{total} failed: {e}")
            return None

    try:
        tmp_files = []
        with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as executor:
            futures = {executor.submit(_dl_one, e, i + 1): i
                       for i, e in enumerate(entries)}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    tmp_files.append(result)

        downloaded = []
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
            out = download(source)
            print(f"[OK] {out}")
        except Exception as e:
            print(f"[!] {source}\n    {e}", file=sys.stderr)
            errors.append(source)

    print(f"\n{len(args) - len(errors)}/{len(args)} completed.")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
