#!/usr/bin/env python3
"""
downloader.py -- yt-dlp CLI wrapper
Calls yt-dlp for all downloads. Custom batch selection prompts preserved.

Usage:
  python3 downloader.py <URL> [URL ...]
"""
import glob, json, os, random, re, shutil, subprocess, sys, tempfile, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from config import (DEFAULT_DEST, BATCH_OG, BATCH_WORKERS,
                    COOKIE_BROWSER, COOKIE_FILE, POT_SERVER_URL)

_HANDLE_RE  = re.compile(r'/@([^/?#]+)')
_CHANNEL_RE = re.compile(r'/(?:channel|c)/([^/?#]+)')
_SLUG_CLEAN = re.compile(r'[^\w\-]')


def _ytdlp(clients: str | None = None) -> list[str]:
    if clients is None:
        clients = "mweb" if POT_SERVER_URL else "ios,tv"
    args = [
        "yt-dlp",
        "-f", "bv*+ba/bv*/b",
        "--merge-output-format", "mp4",
        "--concurrent-fragments", "16",
        "--retries", "10",
        "--fragment-retries", "10",
        "--throttled-rate", "100K",
        "--socket-timeout", "30",
        "--extractor-args", f"youtube:player_client={clients}",
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


def _channel_name_from_url(url: str) -> str:
    m = _HANDLE_RE.search(url)
    if m: return m.group(1)
    m = _CHANNEL_RE.search(url)
    if m: return m.group(1)
    slug = urlparse(url).path.strip('/').replace('/', '_')
    return _SLUG_CLEAN.sub('_', slug) or 'batch'


def _parse_selection(spec: str, total: int) -> list[int]:
    indices = set()
    for part in spec.split(','):
        part = part.strip()
        if '-' in part:
            try:
                s, e = part.split('-', 1)
                for i in range(int(s.strip()), int(e.strip()) + 1):
                    if 1 <= i <= total: indices.add(i - 1)
            except ValueError: pass
        else:
            try:
                i = int(part)
                if 1 <= i <= total: indices.add(i - 1)
            except ValueError: pass
    return sorted(indices)


def _rand_id(dest: str) -> str:
    for _ in range(10000):
        fid = f"{random.randint(0, 9999):04d}"
        if not os.path.exists(os.path.join(dest, f"{fid}.mp4")):
            return fid
    raise RuntimeError(f"no free slot in {dest}")


def _probe(url: str) -> list[dict]:
    """Flat playlist probe -- returns entries sorted by view_count desc."""
    cmd = _ytdlp() + ["--flat-playlist", "-J", "--quiet", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        info = json.loads(r.stdout)
        entries = info.get("entries") or []
        return sorted(entries, key=lambda e: e.get("view_count") or 0, reverse=True)
    except Exception:
        return []


# ── Public API ────────────────────────────────────────────────────────────────

def download(url: str, dest: str = DEFAULT_DEST) -> str | None:
    """Download a single URL to dest. Returns output path or None on failure."""
    os.makedirs(dest, exist_ok=True)
    uid     = f"{random.randint(0, 9999):04d}"
    outtmpl = os.path.join(dest, f"{uid}_%(id)s.%(ext)s")
    for clients in (("mweb", "ios,tv") if POT_SERVER_URL else ("ios,tv", "web")):
        cmd = _ytdlp(clients) + ["--no-playlist", "-o", outtmpl, url]
        if subprocess.run(cmd).returncode == 0:
            hits = glob.glob(os.path.join(dest, f"{uid}_*.mp4"))
            if hits: return hits[0]
    return None


def download_batch(url: str, dest: str = BATCH_OG,
                   playlist_items: str | None = None) -> tuple[list[str], str]:
    """Non-interactive batch download. playlist_items: yt-dlp selection string or None for all."""
    channel     = _channel_name_from_url(url)
    channel_dir = os.path.join(dest, channel)
    os.makedirs(channel_dir, exist_ok=True)
    archive_path = os.path.join(channel_dir, ".dlarchive")
    tmp_dir      = tempfile.mkdtemp(prefix="enxr_batch_")

    try:
        cmd = _ytdlp() + ["-o", os.path.join(tmp_dir, "%(id)s.%(ext)s"),
                          "--download-archive", archive_path, "--quiet"]
        if playlist_items:
            cmd += ["--playlist-items", playlist_items]
        cmd.append(url)
        subprocess.run(cmd)

        downloaded: list[str] = []
        for tmp_path in sorted(glob.glob(os.path.join(tmp_dir, "*.mp4"))):
            fid = _rand_id(channel_dir)
            out = os.path.join(channel_dir, f"{fid}.mp4")
            shutil.move(tmp_path, out)
            downloaded.append(out)
            print(f"[OK] {channel}/{fid}.mp4")

        return downloaded, channel_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def download_channel_interactive(url: str, dest: str = BATCH_OG) -> tuple[list[str], list[int]]:
    """Batch download with interactive selection prompt."""
    print("\n[batch] fetching playlist metadata...")
    entries = _probe(url)
    if not entries:
        print("[batch] no entries found")
        return [], []
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

    filtered  = [entries[i] for i in selection if i < total]
    total_sel = len(filtered)
    print(f"\n[download] {total_sel} video(s) queued -- {BATCH_WORKERS} workers\n")

    channel     = _channel_name_from_url(url)
    channel_dir = os.path.join(dest, channel)
    os.makedirs(channel_dir, exist_ok=True)
    archive_path = os.path.join(channel_dir, ".dlarchive")
    tmp_dir      = tempfile.mkdtemp(prefix="enxr_batch_")
    counter      = [0]
    lock         = threading.Lock()
    failed: list[int] = []

    def _dl_one(entry: dict, idx: int) -> str | None:
        vid_id    = entry.get("id", "")
        entry_url = (entry.get("webpage_url") or entry.get("url")
                     or (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else ""))
        if not entry_url:
            with lock: failed.append(idx)
            return None

        outtmpl = os.path.join(tmp_dir, "%(id)s.%(ext)s")
        for clients in (("mweb", "ios,tv") if POT_SERVER_URL else ("ios,tv", "web")):
            cmd = _ytdlp(clients) + [
                "--no-playlist", "-o", outtmpl,
                "--download-archive", archive_path,
                "--quiet", "--no-warnings", entry_url,
            ]
            if subprocess.run(cmd).returncode == 0:
                hits = glob.glob(os.path.join(tmp_dir, f"{vid_id}.*"))
                mp4  = next((h for h in hits if h.lower().endswith(".mp4")), None)
                if mp4:
                    with lock:
                        counter[0] += 1
                        print(f"  [{counter[0]}/{total_sel}] {vid_id}")
                    return mp4

        with lock:
            failed.append(idx)
            print(f"  [!] {vid_id} failed")
        return None

    try:
        tmp_files: list[str] = []
        with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as executor:
            futs = {executor.submit(_dl_one, e, i + 1): i for i, e in enumerate(filtered)}
            for fut in as_completed(futs):
                res = fut.result()
                if res: tmp_files.append(res)

        downloaded: list[str] = []
        for tmp_path in sorted(tmp_files):
            fid = _rand_id(channel_dir)
            out = os.path.join(channel_dir, f"{fid}.mp4")
            shutil.move(tmp_path, out)
            downloaded.append(out)
            print(f"[OK] {channel}/{fid}.mp4")

        if failed:
            print(f"\n[!] Failed: {', '.join(map(str, sorted(set(failed))))}")
        return downloaded, sorted(set(failed))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if args else 1)

    all_downloaded: list[str] = []
    errors: list[str] = []

    for source in args:
        try:
            u = source.lower()
            is_batch = _is_url(source) and any(
                x in u for x in ("/shorts", "/videos", "/playlist", "/@", "/channel/", "/c/"))
            if is_batch:
                downloaded, failed = download_channel_interactive(source)
                all_downloaded.extend(downloaded)
                if failed:
                    print(f"[!] {len(failed)} failed")
            else:
                out = download(source)
                if out:
                    print(f"[OK] {out}")
                    all_downloaded.append(out)
                else:
                    errors.append(source)
        except Exception as e:
            print(f"[!] {source}: {e}", file=sys.stderr)
            errors.append(source)

    print(f"\n{len(args) - len(errors)}/{len(args)} completed.")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
