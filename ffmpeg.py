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

import os, sys, subprocess, json, re

from config.settings import (AUTO_DEFAULT_LEVEL, UPSCALE_CEILING, UPSCALE_STEPS,
                              SOURCE_CEILING, CEILING_MAX_PASSES, PASS_STRENGTH_DECAY)
from filters.presets import QualityTier, CLEANUP, MAIN
from logger import log_error, cleanup_tmp


# ── dimension + step helpers ─────────────────────────────────────────────────

def _get_dims(path: str) -> tuple:
    """Returns (width, height, is_portrait, short_side, codec_name)."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,codec_name", "-of", "json", path],
            capture_output=True, text=True, check=True,
        )
        streams = json.loads(result.stdout).get("streams", [])
        if not streams:
            raise ValueError(f"no video stream found in: {path}")
        w     = int(streams[0]["width"])
        h     = int(streams[0]["height"])
        codec = streams[0].get("codec_name", "unknown")
        return w, h, h > w, min(w, h), codec
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


def _apply_decay(filters: list, decay: float) -> list:
    """Scale numeric filter params by decay factor for refinement passes."""
    result = []
    for f in filters:
        f = re.sub(r'\bla=([\d.]+)',
                   lambda m: f"la={float(m.group(1)) * decay:.4f}", f)
        for p in ('alpha', 'beta', 'gamma', 'delta'):
            f = re.sub(rf'\b{p}=([\d.]+)',
                       lambda m, p=p: f"{p}={float(m.group(1)) * decay:.4f}", f)
        f = re.sub(r'\brange=(\d+)',
                   lambda m: f"range={max(8, int(int(m.group(1)) * decay))}", f)
        result.append(f)
    return result


def _main_chain(tier: int, target: int, is_portrait: bool,
                do_upscale: bool, user_filters=None, decay: float = 1.0) -> str:
    """
    Table B: light repair + sharpen + optional upscale on cleaned signal.
    zscale uses lanczos + error diffusion for cleanest upscale quality.
    format=yuv420p at end is required by h264/h265_videotoolbox.
    decay scales filter param intensity for refinement passes (pass 2+).
    """
    qt      = QualityTier(tier)
    filters = list(MAIN[qt])

    if decay < 1.0:
        filters = _apply_decay(filters, decay)

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

def _try_encode(cmd: list) -> tuple:
    """Attempt an ffmpeg encode. Returns (True, '') on success, (False, stderr) on failure."""
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True, ""
    except subprocess.CalledProcessError as e:
        return False, e.stderr or ""


def _ffmpeg_errors(stderr: str) -> str:
    """Extract meaningful lines from ffmpeg stderr -- skips progress/info noise."""
    if not stderr.strip():
        return "encode failed (no output)"
    keywords = ("error", "failed", "invalid", "unknown", "not found", "cannot")
    lines = stderr.strip().splitlines()
    # strip build config line -- videotoolbox keyword was matching this, not real errors
    lines = [l for l in lines if not l.strip().startswith("configuration:")]
    relevant = [l.strip() for l in lines if any(k in l.lower() for k in keywords)]
    return " | ".join(relevant[-5:]) if relevant else (lines[-1].strip() if lines else "encode failed")


def _encode(path: str, tmp_path: str, vf: str, high_quality: bool = False) -> None:
    """
    Encode with h264_videotoolbox (hardware H.264) first.
    Falls back to hevc_videotoolbox (hardware H.265) if H.264 VT fails.
    Raises RuntimeError if both fail -- libx264 is GPL and compiled out
    of the iOS ffmpeg build, so no software fallback is available.
    -hwaccel none forces software decode -- required for AV1/non-native codecs.
    Audio always aac. Metadata always stripped.

    high_quality param retained for API compatibility but VTB does not
    support -q:v mode -- quality flags dropped to avoid -22 Invalid argument.
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

    ok, err = _try_encode(base_args + ["-c:v", "h264_videotoolbox", tmp_path])
    if ok:
        return
    log_error("h264_videotoolbox", RuntimeError(_ffmpeg_errors(err)))

    ok, err = _try_encode(base_args + ["-c:v", "hevc_videotoolbox", tmp_path])
    if ok:
        print("[ffmpeg] h264_videotoolbox unavailable, used hevc_videotoolbox")
        return
    log_error("hevc_videotoolbox", RuntimeError(_ffmpeg_errors(err)))

    raise RuntimeError(
        "no compatible encoder found -- "
        "h264_videotoolbox and hevc_videotoolbox both failed"
    )


# ── main enhance loop ─────────────────────────────────────────────────────────

def enhance(path: str, level: int = None, preset=None, user_filters: list = None,
            passes: int = 1, target_res: int = None, ceiling: int = None,
            out_dir: str = None) -> str:
    """
    Restoration + upscale pipeline.

    Pass A (cleanup): stabilize signal at source resolution.
    Pass B (main):    sharpen + one-shot upscale to target_res, then N-1
                      refinement passes at target_res with decaying strength.

    level:      quality tier override 1-5, None = auto-detect, 0 = skip.
    preset:     EnhancePreset for multi-pass (Task 3, reserved).
    target_res: explicit upscale target (e.g. 1440). None = derive from ceiling.
    ceiling:    0 = source lock. None = auto from source. Otherwise cap.
    out_dir:    final output directory (defaults to same dir as input).

    Returns output path on success, original path on skip/failure.
    """
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        raise FileNotFoundError(f"file not found: {path}")

    w, h, is_portrait, short_side, codec = _get_dims(path)
    if codec == "av1":
        print("[warn] AV1 source detected -- software decode required, processing will be slow")
    dirname   = os.path.dirname(path)
    name      = os.path.splitext(os.path.basename(path))[0]
    final_dir = out_dir if out_dir else dirname
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    if level == 0:
        return path

    is_high_res = (short_side >= UPSCALE_CEILING)

    # Derive effective target resolution
    if ceiling == 0:
        eff_target = short_side
    elif target_res is not None:
        eff_target = target_res
    elif ceiling is not None:
        eff_target = ceiling
    else:
        auto_ceil  = get_ceiling(short_side)
        eff_target = auto_ceil if auto_ceil > 0 else short_side
        if is_high_res:
            return path  # at/above ceiling with no explicit target, nothing to do

    do_upscale = eff_target > short_side

    # Auto-detect tier if no override given
    tier = level if level else _detect_tier(path, w, h)
    tier = max(1, min(5, tier))
    print(f"[ffmpeg] quality tier {tier} ({QualityTier(tier).name.lower()})")

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

    # ── Pass B: N passes at target_res, upscale on pass 1 only ───────────────
    for i in range(passes):
        is_last   = (i == passes - 1)
        pass_up   = do_upscale and (i == 0)
        decay     = (PASS_STRENGTH_DECAY[i]
                     if i < len(PASS_STRENGTH_DECAY)
                     else PASS_STRENGTH_DECAY[-1])

        if pass_up:
            print(f"[ffmpeg] pass {i + 1}/{passes}: {current_height}p -> {eff_target}p")
        else:
            pct = int(decay * 100)
            print(f"[ffmpeg] pass {i + 1}/{passes}: {eff_target}p refine ({pct}% strength)")

        main_vf  = _main_chain(tier, eff_target, is_portrait, pass_up, user_filters, decay)
        out_path = (os.path.join(final_dir, f"ex{name}.mp4") if is_last
                    else os.path.join(dirname, f"tmp_{name}_p{i + 1}.mp4"))

        try:
            _encode(current_path, tmp_enc, main_vf)
            os.replace(tmp_enc, out_path)

            if current_path != path and os.path.exists(current_path):
                os.remove(current_path)

            current_path   = out_path
            current_height = eff_target if pass_up else current_height

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            log_error("enhance_main", e,
                      extra=f"file={os.path.basename(path)} pass={i + 1}")
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
    target_res   = None
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
            target_res = 720
            i += 1
        elif a == "--1080":
            target_res = 1080
            i += 1
        elif a == "--1440":
            target_res = 1440
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

    return path, level, user_filters, passes, target_res, ceiling


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if args else 1)

    path, level, user_filters, passes, target_res, ceiling = _parse_args(args)

    if not path:
        print("error: no input file specified", file=sys.stderr)
        sys.exit(1)

    try:
        out = enhance(path, level, user_filters=user_filters, passes=passes,
                      target_res=target_res, ceiling=ceiling)
        print(f"[OK] {out}")
    except Exception as e:
        print(f"[!] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
