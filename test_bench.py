#!/usr/bin/env python3
"""
test_bench.py - render time benchmark

Auto-scrapes ~1 min YouTube clips via yt-dlp search, runs the enhance pipeline,
logs results to log/bench_<timestamp>.txt

Usage:
  python test_bench.py              # auto-scrape 5 clips
  python test_bench.py <url> ...    # benchmark specific URLs
  python test_bench.py --n 10       # auto-scrape N clips
"""

import os, sys, time, datetime, json, subprocess, shutil, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ffmpeg import enhance

# -- scrape config -------------------------------------------------------------
SCRAPE_N      = 5           # default number of clips to benchmark
SCRAPE_POOL   = 30          # candidates to fetch (buffer for any rejects)
TARGET_MIN_S  = 30          # clip duration floor (seconds)
TARGET_MAX_S  = 60          # clip duration ceiling (seconds)
# Shorts-specific queries — Shorts are rarely DRM-protected and are the primary app use case
SEARCH_QUERIES = [
    "ytsearch50:#shorts gopro",
    "ytsearch50:#shorts dashcam",
    "ytsearch50:#shorts cooking",
    "ytsearch50:#shorts skateboard",
    "ytsearch50:#shorts street",
]

RESTORE_LEVEL = 2
ENHANCE_LEVEL = 3
LOG_DIR       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")
WORK_DIR      = os.path.join(tempfile.gettempdir(), "enxr_bench")

# -- url scraper --------------------------------------------------------------

def _scrape_urls(n: int = SCRAPE_N, pool: int = SCRAPE_POOL) -> list[str]:
    """Search YouTube via yt-dlp, return pool candidate URLs (>n to survive DRM rejects)."""
    urls: list[str] = []
    dur_filter = f"duration>={TARGET_MIN_S} & duration<={TARGET_MAX_S}"
    print(f"[scrape] fetching {pool} candidates ({TARGET_MIN_S}-{TARGET_MAX_S}s), need {n} good...")

    for query in SEARCH_QUERIES:
        if len(urls) >= pool:
            break
        cmd = [
            "yt-dlp", query,
            "--match-filter", dur_filter,
            "--skip-download",
            "--print", "%(webpage_url)s",
            "-q",
            "--no-playlist",
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired:
            print(f"  [scrape] timeout on: {query}")
            continue

        for line in r.stdout.strip().splitlines():
            line = line.strip()
            if line.startswith("http") and line not in urls:
                urls.append(line)
            if len(urls) >= pool:
                break

    print(f"[scrape] {len(urls)} candidates ready")
    if not urls:
        print("[scrape] no clips found -- check yt-dlp and network")
    return urls


# -- helpers -------------------------------------------------------------------

def _probe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=10,
        )
        return float(json.loads(r.stdout).get("format", {}).get("duration", 0))
    except Exception:
        return 0.0


def _probe_size_mb(path: str) -> float:
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except Exception:
        return 0.0


def _download(url: str, dest_dir: str) -> str | None:
    """Download URL to dest_dir. Returns file path or None on failure.
    web client + browser cookies = bypasses both CAPTCHA and DRM.
    Falls back through browsers, then to ios client if none found."""
    os.makedirs(dest_dir, exist_ok=True)
    out_tmpl = os.path.join(dest_dir, "%(id)s.%(ext)s")
    base = [
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", out_tmpl,
        "--no-playlist",
        url,
    ]
    # try web client with each browser's cookies, then ios fallback
    attempts = [
        ["--extractor-args", "youtube:player_client=web", "--cookies-from-browser", "edge"],
        ["--extractor-args", "youtube:player_client=web", "--cookies-from-browser", "chrome"],
        ["--extractor-args", "youtube:player_client=web", "--cookies-from-browser", "firefox"],
        ["--extractor-args", "youtube:player_client=ios,tv,web"],  # original strategy
    ]
    last_err = ""
    for extra in attempts:
        cmd = ["yt-dlp"] + extra + base
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            files = [os.path.join(dest_dir, f) for f in os.listdir(dest_dir)
                     if f.endswith(".mp4")]
            if files:
                return max(files, key=os.path.getmtime)
        last_err = (r.stdout + r.stderr).strip()
        for f in os.listdir(dest_dir):
            try: os.remove(os.path.join(dest_dir, f))
            except OSError: pass

    print(f"  [dl fail] {last_err[-300:]}")
    return None


def _fmt(seconds: float) -> str:
    return f"{seconds:.1f}s"


# -- benchmark runner ----------------------------------------------------------

def run(urls: list[str], target: int = SCRAPE_N) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    ts      = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = os.path.join(LOG_DIR, f"bench_{ts}.txt")

    header = (
        f"enxr benchmark - {ts}\n"
        f"restore={RESTORE_LEVEL}  enhance={ENHANCE_LEVEL}\n"
        f"{'-' * 60}\n"
    )
    print(header, end="")

    results = []
    ok_count = 0

    for i, url in enumerate(urls, 1):
        if ok_count >= target:
            break

        # local file — skip download entirely
        is_local = os.path.isfile(url)
        clip_dir = os.path.join(WORK_DIR, f"clip_{i:02d}")
        if not is_local:
            if os.path.isdir(clip_dir):
                shutil.rmtree(clip_dir)
        out_dir = clip_dir + "_out"
        os.makedirs(out_dir, exist_ok=True)

        print(f"\n[{i}/{len(urls)}] {os.path.basename(url) if is_local else url}")

        if is_local:
            src = url
            t_dl = 0.0
            print(f"  local file")
        else:
            print(f"  downloading...")
            t_dl_start = time.perf_counter()
            src = _download(url, clip_dir)
            t_dl = time.perf_counter() - t_dl_start

        if not src:
            row = {"url": url, "status": "DOWNLOAD_FAIL"}
            results.append(row)
            print(f"  FAILED download")
            continue

        clip_dur  = _probe_duration(src)
        src_mb    = _probe_size_mb(src)
        src_name  = os.path.basename(src)
        print(f"  {src_name}  {clip_dur:.1f}s  {src_mb:.2f} MB")
        print(f"  download: {_fmt(t_dl)}")
        print(f"  enhancing...")

        t_enc_start = time.perf_counter()
        out = enhance(
            src,
            restore_level=RESTORE_LEVEL,
            enhance_level=ENHANCE_LEVEL,
            out_dir=out_dir,
            keep_original=True,
        )
        t_enc = time.perf_counter() - t_enc_start

        out_mb = _probe_size_mb(out)
        ratio  = clip_dur / t_enc if t_enc > 0 else 0

        status = "OK" if out != src else "ENCODE_FAIL"
        if status == "OK":
            ok_count += 1
        print(f"  encode:   {_fmt(t_enc)}  ({ratio:.1f}x realtime)  {out_mb:.2f} MB out")
        print(f"  status:   {status}")

        results.append({
            "url":        url,
            "file":       src_name,
            "duration_s": round(clip_dur, 1),
            "src_mb":     round(src_mb, 2),
            "dl_s":       round(t_dl, 1),
            "enc_s":      round(t_enc, 1),
            "realtime_x": round(ratio, 2),
            "out_mb":     round(out_mb, 2),
            "status":     status,
        })

        shutil.rmtree(clip_dir, ignore_errors=True)
        shutil.rmtree(out_dir, ignore_errors=True)

    # -- summary ---------------------------------------------------------------
    ok     = [r for r in results if r.get("status") == "OK"]
    failed = [r for r in results if r.get("status") != "OK"]

    summary_lines = [
        header,
        f"{'URL':<50} {'dur':>5} {'dl':>6} {'enc':>6} {'x':>6} {'out MB':>7} status",
        "-" * 90,
    ]
    for r in results:
        if r.get("status") == "OK":
            summary_lines.append(
                f"{r['url']:<50} {r['duration_s']:>5.1f}s {r['dl_s']:>5.1f}s "
                f"{r['enc_s']:>5.1f}s {r['realtime_x']:>5.1f}x {r['out_mb']:>6.2f}MB  {r['status']}"
            )
        else:
            summary_lines.append(
                f"{r['url']:<50} {'-':>5} {'-':>6} {'-':>6} {'-':>6} {'-':>7}  {r['status']}"
            )

    summary_lines += [
        "-" * 90,
        f"passed: {len(ok)}/{len(results)}",
    ]
    if ok:
        avg_x   = sum(r["realtime_x"] for r in ok) / len(ok)
        avg_enc = sum(r["enc_s"]      for r in ok) / len(ok)
        summary_lines.append(f"avg encode: {avg_enc:.1f}s  avg realtime: {avg_x:.1f}x")
    if failed:
        summary_lines.append("failed URLs:")
        for r in failed:
            summary_lines.append(f"  {r['url']}  ({r['status']})")

    report = "\n".join(summary_lines)
    print(f"\n{'-' * 60}\n{report}")

    with open(logfile, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"\n[log] {logfile}")


# -- entry ---------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]
    n = SCRAPE_N

    # --n 10 flag
    if "--n" in args:
        idx = args.index("--n")
        if idx + 1 < len(args):
            n = int(args[idx + 1])
            args = [a for i, a in enumerate(args) if i not in (idx, idx + 1)]

    if args:
        urls = args
    else:
        # check for local mp4s in vids/og as quick test material
        og_dir = os.path.expanduser("~/Documents/vids/og")
        local = sorted(
            [os.path.join(og_dir, f) for f in os.listdir(og_dir) if f.endswith(".mp4")]
        ) if os.path.isdir(og_dir) else []
        if local:
            print(f"[bench] found {len(local)} local file(s) in ~/Documents/vids/og — using those")
            urls = local[:n]
        else:
            print("[bench] no local files found, scraping YouTube...")
            print("[bench] NOTE: YouTube DRM may block downloads. Pass local .mp4 paths to skip.")
            urls = _scrape_urls(n)
    if not urls:
        sys.exit(1)
    run(urls, target=n)
