#!/usr/bin/env python3
"""
test_comprehensive.py — Full pipeline validation with quality metrics.

Runs encode tests on all testclips with:
  - Output file validity (codec, dimensions, duration)
  - Consistency checks (same input -> identical output hash)
  - Timing profiles

Usage:
  python test_comprehensive.py [--quick]
"""

import os, sys, json, subprocess, shutil, tempfile, hashlib, time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ffmpeg import enhance, _get_dims
from config import get_ceiling

TESTCLIPS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testclips")
TRIM_SECS = 3

# Comprehensive test matrix
PRESETS = [
    ("very_fast", 0),  # batch, no processing
    ("very_fast", 2),  # batch + light sharpen
    ("med",       2),  # balanced
    ("med",       3),  # balanced + sharpen
    ("slow",      3),  # quality
]


def _probe(path: str) -> dict | None:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,width,height",
             "-show_entries", "format=duration",
             "-of", "json", path],
            capture_output=True, text=True, check=True, timeout=10,
        )
        data = json.loads(r.stdout)
        s = (data.get("streams") or [{}])[0]
        f = data.get("format", {})
        return {
            "codec":    s.get("codec_name"),
            "width":    int(s.get("width", 0)),
            "height":   int(s.get("height", 0)),
            "duration": float(f.get("duration", 0)),
        }
    except Exception:
        return None


def _file_hash(path: str) -> str:
    """MD5 of file for consistency checking."""
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            h.update(chunk)
    return h.hexdigest()


def test_clip(clip: Path, out_dir: str, quick: bool = False) -> dict:
    """Run all tests on a single clip. Returns result summary."""
    try:
        w, h, is_portrait, short_side, codec = _get_dims(str(clip))
    except Exception as e:
        return {"clip": clip.name, "status": "SKIP", "reason": f"probe: {e}"}

    ceiling = get_ceiling(short_side)
    target = ceiling if ceiling > 0 else short_side

    results = {
        "clip": clip.name,
        "source": {"w": w, "h": h, "short_side": short_side, "codec": codec},
        "target": target,
        "tests": {},
    }

    # Trim for speed
    trimmed = os.path.join(out_dir, f"trim_{clip.name}")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "0", "-t", str(TRIM_SECS), "-i", str(clip), "-c", "copy", trimmed],
            capture_output=True, check=True, timeout=15,
        )
    except Exception:
        return {"clip": clip.name, "status": "SKIP", "reason": "trim failed"}

    presets = PRESETS[:2] if quick else PRESETS

    for denoise, lvl in presets:
        tag = f"{denoise}/{lvl}"

        # Encode test
        src_copy = os.path.join(out_dir, f"{clip.stem}_{denoise}_{lvl}.mp4")
        shutil.copy2(trimmed, src_copy)
        clip_dir = os.path.join(out_dir, clip.stem)
        os.makedirs(clip_dir, exist_ok=True)

        t0 = time.time()
        try:
            out = enhance(src_copy, denoise_preset=denoise, enhance_level=lvl,
                          target_res=target, out_dir=clip_dir, keep_original=True)
            elapsed = time.time() - t0

            if os.path.abspath(out) == os.path.abspath(src_copy):
                results["tests"][tag] = {"status": "FAIL", "reason": "encode failed silently"}
                continue

            info = _probe(out)
            if not info:
                results["tests"][tag] = {"status": "FAIL", "reason": "output unprobeable"}
                continue

            got_short = min(info["width"], info["height"])
            if info["codec"] != "h264" or got_short != target or info["duration"] <= 0:
                results["tests"][tag] = {
                    "status": "FAIL",
                    "codec": info["codec"],
                    "short_side": got_short,
                    "duration": info["duration"],
                }
                continue

            results["tests"][tag] = {
                "status": "PASS",
                "codec": info["codec"],
                "dims": f"{info['width']}x{info['height']}",
                "time_sec": round(elapsed, 1),
                "size_mb": round(os.path.getsize(out) / (1024*1024), 1),
            }

        except Exception as e:
            results["tests"][tag] = {"status": "FAIL", "reason": str(e)[:50]}

    # Consistency check: same input twice = same output hash
    if not quick:
        src_copy2 = os.path.join(out_dir, f"{clip.stem}_consistency.mp4")
        shutil.copy2(trimmed, src_copy2)
        try:
            out1 = enhance(src_copy, denoise_preset="med", enhance_level=2,
                          target_res=target, out_dir=clip_dir, keep_original=True)
            out2 = enhance(src_copy2, denoise_preset="med", enhance_level=2,
                          target_res=target, out_dir=clip_dir, keep_original=True)
            h1 = _file_hash(out1)
            h2 = _file_hash(out2)
            results["consistency"] = {"status": "PASS" if h1 == h2 else "FAIL",
                                      "hash1": h1[:8], "hash2": h2[:8]}
        except Exception as e:
            results["consistency"] = {"status": "FAIL", "reason": str(e)[:50]}

    return results


def main():
    quick = "--quick" in sys.argv
    clips = sorted(Path(TESTCLIPS).glob("*.mp4"))
    if not clips:
        print(f"No clips in {TESTCLIPS}")
        sys.exit(1)

    tmpdir = tempfile.mkdtemp(prefix="enxr_comprehensive_")
    all_results = {"quick": quick, "clips": []}
    total_pass = total_fail = 0

    try:
        for clip in clips:
            result = test_clip(clip, tmpdir, quick)
            all_results["clips"].append(result)

            print(f"\n{clip.name}  {result['source']['short_side']}p -> {result.get('target', '?')}p")
            if result.get("status") == "SKIP":
                print(f"  SKIP: {result.get('reason')}")
                continue

            for tag, test in result.get("tests", {}).items():
                status = test.get("status", "?")
                if status == "PASS":
                    total_pass += 1
                    time_str = f"{test['time_sec']}s"
                    print(f"  {tag:15} PASS  {test['dims']}  {test['size_mb']}MB  {time_str}")
                else:
                    total_fail += 1
                    reason = test.get('reason', 'unknown')
                    print(f"  {tag:15} FAIL  {reason}")

            if result.get("consistency"):
                c = result["consistency"]
                status = c["status"]
                print(f"  consistency    {status}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print(f"\n{'='*60}")
    print(f"Total: {total_pass} passed, {total_fail} failed")

    # Write full JSON report
    report_path = "test_results_comprehensive.json"
    with open(report_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"Full report: {report_path}")

    sys.exit(0 if total_fail == 0 else 1)


if __name__ == "__main__":
    main()
