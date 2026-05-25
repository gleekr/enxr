#!/usr/bin/env python3
import os, json, subprocess, time

CALIBRATION_FILE = os.path.expanduser("~/.enxr_calibration.json")
_CAL_CLIP_SECS   = 3.0
_REF_PIXELS      = {720: 921_600, 1080: 2_073_600, 1440: 3_686_400}
_REF_RES         = 1080


def load_calibration() -> dict:
    try:
        with open(CALIBRATION_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(cal: dict) -> None:
    try:
        with open(CALIBRATION_FILE, "w") as f:
            json.dump(cal, f)
    except Exception:
        pass


def get_duration(path: str) -> float:
    """Return video duration in seconds, or 0.0 on failure."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", path],
            capture_output=True, text=True, check=True,
        )
        return float(json.loads(r.stdout).get("format", {}).get("duration", 0))
    except Exception:
        return 0.0


def run_calibration(path: str, vf: str, resolution: int) -> bool:
    """
    Encode a 3-second clip with vf, measure wall time, save speed factor.
    Returns True on success, False if encode fails (e.g. no VTB on dev machine).
    """
    tmp = os.path.expanduser("~/.enxr_cal_tmp.mp4")
    base = [
        "ffmpeg", "-y", "-hwaccel", "none",
        "-ss", "0", "-t", str(_CAL_CLIP_SECS),
        "-i", path,
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c:a", "aac", "-vf", vf,
        "-map_metadata", "-1",
    ]
    start = time.time()
    ok = False
    for encoder in ("h264_videotoolbox", "hevc_videotoolbox"):
        try:
            subprocess.run(base + ["-c:v", encoder, tmp],
                           capture_output=True, check=True)
            ok = True
            break
        except subprocess.CalledProcessError:
            continue
    elapsed = time.time() - start
    if os.path.exists(tmp):
        os.remove(tmp)
    if not ok or elapsed <= 0:
        return False
    speed = round(_CAL_CLIP_SECS / elapsed, 4)
    cal = load_calibration()
    cal[str(resolution)] = speed
    _save(cal)
    return True


def estimate_time(duration: float, passes: int, resolution: int,
                  cal: dict) -> str | None:
    """Return human-readable time estimate, or None if no calibration data."""
    key = str(resolution)
    if key not in cal or duration <= 0:
        return None
    speed  = cal[key]
    pixels = _REF_PIXELS.get(resolution, resolution * resolution * 16 // 9)
    factor = pixels / _REF_PIXELS[_REF_RES]
    total  = (duration / speed) * passes * factor
    mins, secs = divmod(int(total), 60)
    return f"~{mins} min {secs:02d} sec" if mins else f"~{secs} sec"


def update_calibration(resolution: int, actual_seconds: float,
                       duration: float) -> None:
    """Blend observed encode speed into calibration after a real encode."""
    if actual_seconds <= 0 or duration <= 0:
        return
    observed = duration / actual_seconds
    cal = load_calibration()
    key = str(resolution)
    if key in cal:
        cal[key] = round(cal[key] * 0.7 + observed * 0.3, 4)
    else:
        cal[key] = round(observed, 4)
    _save(cal)
