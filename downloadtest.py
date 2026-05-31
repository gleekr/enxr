#!/usr/bin/env python3
"""
downloadtest.py -- download smoke test
Downloads N videos to a temp folder, deletes on completion, logs failures.

Usage:
  python3 downloadtest.py <URL> [count]
"""
import glob, os, shutil, subprocess, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import BATCH_WORKERS
from downloader import _ytdlp, _probe

LOG_DIR = os.path.join(os.path.dirname(__file__), "log")


def _fmt_elapsed(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m}min {s}sec"


def _write_log(url: str, total: int, completed: int, elapsed: float,
               failures: list[str]) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"dltest_{time.strftime('%Y%m%d_%H%M%S')}.txt")
    lines = [
        f"url:       {url}",
        f"result:    {completed}/{total} completed in {_fmt_elapsed(elapsed)}",
        f"failures:  {len(failures)}",
    ]
    if failures:
        lines.append("")
        lines += [f"  FAIL: {f}" for f in failures]
    content = "\n".join(lines) + "\n"
    with open(path, "w") as f:
        f.write(content)
    print(f"\n{'─'*40}")
    print(content, end="")
    print(f"{'─'*40}")
    print(f"[log] {path}")


def _dl_one(entry: dict, tmp_dir: str) -> str | None:
    vid_id    = entry.get("id", "")
    entry_url = (entry.get("webpage_url") or entry.get("url")
                 or (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else ""))
    if not entry_url:
        return None
    outtmpl = os.path.join(tmp_dir, "%(id)s.%(ext)s")
    for clients in ("ios,tv", "web"):
        cmd = _ytdlp(clients) + ["--no-playlist", "-o", outtmpl, "--quiet", "--no-warnings", entry_url]
        if subprocess.run(cmd).returncode == 0:
            hits = glob.glob(os.path.join(tmp_dir, f"{vid_id}.*"))
            mp4  = next((c for c in hits if c.lower().endswith(".mp4")), None)
            if mp4: return mp4
    return None


def _dl_single(url: str, tmp_dir: str) -> str | None:
    outtmpl = os.path.join(tmp_dir, "%(id)s.%(ext)s")
    for clients in ("ios,tv", "web"):
        cmd = _ytdlp(clients) + ["--no-playlist", "-o", outtmpl, "--quiet", "--no-warnings", url]
        if subprocess.run(cmd).returncode == 0:
            hits = glob.glob(os.path.join(tmp_dir, "*.mp4"))
            if hits: return max(hits, key=os.path.getmtime)
    return None


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if args else 1)

    url       = args[0]
    cli_count = int(args[1]) if len(args) > 1 and args[1].isdigit() else None

    tmp_dir  = tempfile.mkdtemp(prefix="dltest_")
    start    = time.time()
    failures: list[str] = []

    try:
        print(f"[dltest] probing {url} ...")
        try:
            entries = _probe(url)
            entries = entries if entries else None
        except Exception as e:
            elapsed = time.time() - start
            print(f"[!] probe failed: {e}")
            _write_log(url, 0, 0, elapsed, [f"probe error: {e}"])
            sys.exit(1)

        if entries is None:
            print("[dltest] single video\n")
            result  = _dl_single(url, tmp_dir)
            elapsed = time.time() - start
            done    = 1 if result else 0
            if not result:
                failures.append(url)
            suffix = ". if failed see Logs" if failures else ""
            print(f"\n{done}/1 downloads completed in {_fmt_elapsed(elapsed)}{suffix}")
            _write_log(url, 1, done, elapsed, failures)

        else:
            total = len(entries)
            count = cli_count
            if count is None:
                raw   = input(f"[dltest] {total} video(s) found. How many? [1-{total}]: ").strip()
                count = int(raw) if raw.isdigit() and 0 < int(raw) <= total else total
            entries = entries[:count]
            total   = len(entries)

            print(f"\n[dltest] {total} video(s) queued -- {BATCH_WORKERS} workers\n")

            counter = [0]
            lock    = threading.Lock()

            def _worker(entry: dict, idx: int) -> None:
                result = _dl_one(entry, tmp_dir)
                vid_id = entry.get("id", f"#{idx}")
                with lock:
                    if result:
                        counter[0] += 1
                        print(f"  [{counter[0]}/{total}] {vid_id}")
                    else:
                        failures.append(vid_id)
                        print(f"  [!] {vid_id} failed")

            with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as executor:
                futs = {executor.submit(_worker, e, i + 1): i for i, e in enumerate(entries)}
                for fut in as_completed(futs):
                    fut.result()

            elapsed   = time.time() - start
            completed = counter[0]
            suffix    = ". if failed see Logs" if failures else ""
            print(f"\n{completed}/{total} downloads completed in {_fmt_elapsed(elapsed)}{suffix}")
            _write_log(url, total, completed, elapsed, failures)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
