#!/usr/bin/env python3
"""
ffmpeg.py - enhance + upscale module

Two-pass pipeline:
  Pass A (cleanup): deblock/denoise at source resolution -- stabilize signal
  Pass B (main):    sharpen + upscale on clean signal

Quality tier is auto-detected from source bitrate (1=excellent -> 5=broken).
Override with explicit level 1-5. Level 0 = skip.

Usage:
  python3 ffmpeg.py <file.mp4> [level 0-5] [--passes N]
                               [--filters "f1,f2"] [--auto]
                               [--720|--1080|--1440|--source]
"""

import os, sys, subprocess, json

from config.settings import (AUTO_DEFAULT_LEVEL, UPSCALE_CEILING, UPSCALE_STEPS,
                              SOURCE_CEILING, CEILING_MAX_PASSES)
from filters.presets import QualityTier, CLEANUP, MAIN
from logger import log_error, cleanup_tmp


# ── dimension + step helpers ─────────────────────────────────────────────────

def _get_dims(path: str) -> tuple:
    """Returns (width, height, is_portrait, short_side)."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", path],
            capture_output=True, text=True, check=True,
        )
        streams = json.loads(result.stdout).get("streams", [])
        if not streams:
            raise ValueError(f"no video stream found in: {path}")
        w = int(streams[0]["width"])
        h = int(streams[0]["height"])
        return w, h, h > w, min(w, h)
    except FileNotFoundError:
        raise FileNotFoundError("ffprobe not found -- is FFmpeg installed and on PATH?")


def _get_steps(short_side: int, ceiling: int = None) -> list:
    """
    Return ordered upscale targets from source up to ceiling.
    ceiling=None defaults to UPSCALE_CEILING. ceiling=0 = source lock.
    """
    if ceiling == 0:
        return []
    cap = ceiling if ceiling is not None else UPSCALE_CEILING
    return [t for t in UPSCALE_STEPS if short_side < t <= cap]


def get_ceiling(short_side: int) -> int:
    """Derive appropriate upscale ceiling from source resolution."""
    for threshold in sorted(SOURCE_CEILING.keys(), reverse=True):
        if short_side >= threshold:
            return SOURCE_CEILING[threshold]
    return 720


def cap_passes(passes: int, ceiling: int) -> int:
    """Cap passes to quality/hardware limit for given ceiling."""
    max_p = CEILING_MAX_PASSES.get(ceiling, 2)
    if passes > max_p:
        print(f"[warn] max {max_p} passes for {ceiling}p ceiling -- running {max_p}")
        return max_p
    return passes


# ── quality detection ─────────────────────────────────────────────────────────

def _detect_tier(path: str, w: int, h: int) -> int:
    """
    Detect quality tier 1-5 from bitrate normalized to 1080p equivalent.
      1 = excellent  (>5000 kbps norm)
      2 = good       (2500-5000)
      3 = fair       (1000-2500)  -- typical YT Shorts
      4 = poor       (400-1000)
      5 = broken     (<400)
    Falls back to tier 3 on any probe failure.
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=bit_rate",
             "-of", "json", path],
            capture_output=True, text=True, check=True,
        )
        bit_rate = int(json.loads(result.stdout).get("format", {}).get("bit_rate", 0))
        if bit_rate <= 0:
            return 3
        norm_kbps = (bit_rate / 1000) * ((1920 * 1080) / (w * h))
        if norm_kbps > 5000: return 1
        if norm_kbps > 2500: return 2
        if norm_kbps > 1000: return 3
        if norm_kbps > 400:  return 4
        return 5
    except Exception:
        return 3


# ── filter chain builders ─────────────────────────────────────────────────────

def _cleanup_chain(tier: int) -> str:
    """
    Table A: deblock/denoise at source resolution.
    format=yuv420p bookends ensure VideoToolbox-compatible pixel format.
    No sharpening -- sharpening on a dirty signal amplifies artifacts.
    """
    qt      = QualityTier(tier)
    filters = list(CLEANUP[qt])
    return ",".join(filters)


def _main_chain(tier: int, target: int, is_portrait: bool,
                do_upscale: bool, user_filters=None) -> str:
    """
    Table B: light repair + sharpen + optional upscale on cleaned signal.
    zscale uses lanczos + error diffusion for cleanest upscale quality.
    format=yuv420p at end is required by h264/h265_videotoolbox.
    """
    qt      = QualityTier(tier)
    filters = list(MAIN[qt])

    if user_filters:
        filters.extend(user_filters)

    if do_upscale:
        if is_portrait:
            filters.append(
                f"zscale=w={target}:h=-2:filter=lanczos:dither=error_diffusion")
        else:
            filters.append(
                f"zscale=w=-2:h={target}:filter=lanczos:dither=error_diffusion")

    filters.append("format=yuv420p")
    return ",".join(filters)


# ── encoder ───────────────────────────────────────────────────────────────────

def _try_encode(cmd: list) -> bool:
    """Attempt an ffmpeg encode. Returns True on success, False on failure."""
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False


def _encode(path: str, tmp_path: str, vf: str, high_quality: bool = False) -> None:
    """
    Encode with h264_videotoolbox (hardware H.264) first.
    Falls back to hevc_videotoolbox (hardware H.265) if H.264 VT fails.
    Falls back to libx264 (software, Windows/Linux) if both VT encoders fail.
    -hwaccel none forces software decode -- required for AV1/non-native codecs.
    Audio always aac. Metadata always stripped.

    high_quality: True for intermediate cleanup pass -- minimises generation
    loss before the main pass runs. VideoToolbox uses -q:v 85 (out of 100);
    libx264 uses -crf 18 (near-lossless). Final passes use encoder defaults.
    """
    base_args = [
        "ffmpeg", "-y",
        "-hwaccel", "none",
        "-i", path,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-c:a", "aac",
        "-vf", vf,
        "-map_metadata", "-1",
    ]

    vt_q   = ["-q:v", "85"] if high_quality else []
    x264_q = ["-crf", "18"] if high_quality else []

    if _try_encode(base_args + ["-c:v", "h264_videotoolbox"] + vt_q + [tmp_path]):
        return

    if _try_encode(base_args + ["-c:v", "hevc_videotoolbox"] + vt_q + [tmp_path]):
        print("[ffmpeg] h264_videotoolbox unavailable, used hevc_videotoolbox")
        return

    print("[ffmpeg] VideoToolbox unavailable, falling back to libx264")
    subprocess.run(base_args + ["-c:v", "libx264"] + x264_q + [tmp_path], check=True)


# ── main enhance loop ─────────────────────────────────────────────────────────

def enhance(path: str, level: int = None, user_filters: list = None,
            passes: int = 1, ceiling: int = None, out_dir: str = None) -> str:
    """
    Two-pass restoration + upscale pipeline.

    Pass A (cleanup): stabilize signal at source resolution using Table A preset.
    Pass B (main):    sharpen + upscale using Table B preset, N times.

    level: quality tier override 1-5, or None for auto-detect.
           0 = skip all processing.
    ceiling: upscale cap. None=auto from source, 0=source lock.
    out_dir: final output directory (defaults to same dir as input).

    Returns output path on success, original path on skip/failure.
    """
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        raise FileNotFoundError(f"file not found: {path}")

    w, h, is_portrait, short_side = _get_dims(path)
    dirname   = os.path.dirname(path)
    name      = os.path.splitext(os.path.basename(path))[0]
    final_dir = out_dir if out_dir else dirname
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    if level == 0:
        return path

    is_high_res = (short_side >= UPSCALE_CEILING)
    source_lock = (ceiling == 0)

    if is_high_res and not source_lock:
        return path

    # Auto-detect tier if no override given
    tier = level if level else _detect_tier(path, w, h)
    tier = max(1, min(5, tier))
    print(f"[ffmpeg] quality tier {tier} ({QualityTier(tier).name.lower()})")

    if source_lock:
        step_list   = [short_side] * passes
        do_upscales = [False] * passes
    else:
        step_list   = _get_steps(short_side, ceiling)
        passes      = min(passes, len(step_list))
        step_list   = step_list[:passes]
        do_upscales = [True] * len(step_list)

    current_path   = path
    current_height = short_side

    # ── Pass A: cleanup at source resolution ──────────────────────────────────
    cleanup_vf   = _cleanup_chain(tier)
    cleanup_path = os.path.join(dirname, f"tmp_{name}_cleanup.mp4")
    tmp_enc      = os.path.join(dirname, f"tmp_{name}_enc.mp4")

    print(f"[ffmpeg] cleanup: {short_side}p (tier {tier})")
    try:
        _encode(current_path, tmp_enc, cleanup_vf, high_quality=True)
        os.replace(tmp_enc, cleanup_path)
        current_path = cleanup_path
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        log_error("enhance_cleanup", e, extra=f"file={os.path.basename(path)}")
        cleanup_tmp(dirname)
        return path

    # ── Pass B: main passes (sharpen + upscale) ───────────────────────────────
    for i, target in enumerate(step_list):
        is_last  = (i == len(step_list) - 1)
        do_up    = do_upscales[i]

        if source_lock and i >= 2:
            print(f"[warn] pass {i + 1} -- diminishing returns likely")

        if do_up:
            print(f"[ffmpeg] main {i + 1}/{len(step_list)}: "
                  f"{current_height}p -> {target}p")
        else:
            print(f"[ffmpeg] main {i + 1}/{len(step_list)}: "
                  f"{current_height}p refine")

        main_vf  = _main_chain(tier, target, is_portrait, do_up, user_filters)
        out_path = (os.path.join(final_dir, f"ex{name}.mp4") if is_last
                    else os.path.join(dirname, f"tmp_{name}_p{i + 1}.mp4"))

        try:
            _encode(current_path, tmp_enc, main_vf)
            os.replace(tmp_enc, out_path)

            if current_path != path and os.path.exists(current_path):
                os.remove(current_path)

            current_path   = out_path
            current_height = target if do_up else current_height

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            log_error("enhance_main", e,
                      extra=f"file={os.path.basename(path)} pass={i+1}")
            cleanup_tmp(dirname)
            if current_path != path and os.path.exists(current_path):
                os.remove(current_path)
            return path

    # Remove original after all passes succeed
    if os.path.exists(path) and current_path != path:
        os.remove(path)

    return current_path


# ── prompt (standalone CLI use) ───────────────────────────────────────────────

def prompt_level(skip_prompts: bool = False) -> int:
    if skip_prompts:
        return AUTO_DEFAULT_LEVEL
    print("\nchoose tier 1-5 (or 0 to skip)")
    print("  0 - skip")
    print("  1 - excellent source  (sharpen only)")
    print("  2 - good source       (light restore)")
    print("  3 - fair / typical YT (standard)")
    print("  4 - poor / compressed (aggressive)")
    print("  5 - broken source     (max restore)")
    while True:
        choice = input("tier (0-5, enter for auto): ").strip()
        if choice == "":
            return None
        if choice in ("0", "1", "2", "3", "4", "5"):
            return int(choice)
        print("  invalid, enter 0-5 or press enter for auto")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args(args: list):
    path         = None
    level        = None
    user_filters = None
    passes       = 1
    auto         = False
    ceiling      = None

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--filters" and i + 1 < len(args):
            user_filters = [f.strip() for f in args[i + 1].split(",")]
            i += 2
        elif a == "--passes" and i + 1 < len(args):
            passes = int(args[i + 1])
            i += 2
        elif a == "--auto":
            auto = True
            i += 1
        elif a == "--720":
            ceiling = 720
            i += 1
        elif a == "--1080":
            ceiling = 1080
            i += 1
        elif a == "--1440":
            ceiling = 1440
            i += 1
        elif a == "--source":
            ceiling = 0
            i += 1
        elif a.isdigit() and 0 <= int(a) <= 5 and level is None:
            level = int(a)
            i += 1
        elif path is None and not a.startswith("--"):
            path = a
            i += 1
        else:
            i += 1

    if auto and level is None:
        level = AUTO_DEFAULT_LEVEL

    return path, level, user_filters, passes, ceiling


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if args else 1)

    path, level, user_filters, passes, ceiling = _parse_args(args)

    if not path:
        print("error: no input file specified", file=sys.stderr)
        sys.exit(1)

    try:
        out = enhance(path, level, user_filters, passes, ceiling)
        print(f"[OK] {out}")
    except Exception as e:
        print(f"[!] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
