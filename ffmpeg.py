#!/usr/bin/env python3
"""
ffmpeg.py - enhance + upscale module
Importable by enxr.py or run standalone on any mp4.

Usage:
  python3 ffmpeg.py <####.mp4> [level 1-4] [--passes N] [--filters "f1,f2,..."]
                               [--auto] [--720|--1080|--1440|--source]

Levels:
  1 - low      mild deblock, denoise, sharpen
  2 - medium   deblock, DCT denoise, deband, sharpen
  3 - high     deblock, stronger DCT denoise, deband, sharpen
  4 - skip     no processing, file unchanged

Passes:
  Each pass upscales one step toward ceiling (default 1440p).
  Pass 1 uses chosen level + user filters.
  Pass 2+ uses level 1 -- source is already cleaner after pass 1.

Upscale ceiling flags (optional):
  --720      lock upscale ceiling to 720p
  --1080     lock upscale ceiling to 1080p
  --1440     lock upscale ceiling to 1440p (default)
  --source   no upscale at all; passes refine in place at source resolution

Auto flag:
  --auto     skip prompt, use level 2 by default (override with explicit level)

Upscale axis:
  Portrait  (h > w): scales width axis
  Landscape (w > h): scales height axis

Extra filters via --filters inserted after core repair, before sharpening.
Arg ordering is flexible.
"""

import os, sys, subprocess, json

from config.settings import AUTO_DEFAULT_LEVEL, UPSCALE_CEILING, UPSCALE_STEPS, SOURCE_CEILING, CEILING_MAX_PASSES
from filters.presets import PRESETS, Preset
from logger import log_error, cleanup_tmp


def _get_dims(path: str) -> tuple:
    # returns (width, height, is_portrait, short_side)
    # short_side used for step decisions so portrait and landscape
    # both resolve correctly regardless of which axis is longer
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "json", path,
            ],
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
    ceiling=None defaults to 1440. ceiling=0 means source lock (no upscale).
    e.g. 360p, ceiling=1080 -> [720, 1080]
         720p, ceiling=None -> [1080, 1440]
    """
    if ceiling == 0:
        return []  # source lock -- no upscale steps
    cap = ceiling if ceiling is not None else UPSCALE_CEILING
    return [t for t in UPSCALE_STEPS if short_side < t <= cap]


def get_ceiling(short_side: int) -> int:
    """Derive the appropriate upscale ceiling from source resolution."""
    for threshold in sorted(SOURCE_CEILING.keys(), reverse=True):
        if short_side >= threshold:
            return SOURCE_CEILING[threshold]
    return 720


def cap_passes(passes: int, ceiling: int) -> int:
    """Cap passes to hardware/quality limit for the given ceiling."""
    max_p = CEILING_MAX_PASSES.get(ceiling, 2)
    if passes > max_p:
        print(f"[warn] max {max_p} passes for {ceiling}p ceiling -- running {max_p}")
        return max_p
    return passes


def _filter_chain(level: int, target: int, user_filters: list = None,
                  is_portrait: bool = False, do_upscale: bool = True) -> str:
    """
    Build the FFmpeg -vf filter chain for one pass.

    Filter ordering logic:
      1. deblock        -- first on raw signal; artifacts not baked in by later filters
      2. dctdnoiz       -- denoise on cleaner post-deblock signal; DCT-based,
                          faster than nlmeans/fftdnoiz with good quality
      3. deband         -- easier to detect banding after noise removed;
                          skipped at level 1 where damage is minimal
      4. user filters   -- repair/analysis filters here, after core repair,
                          before sharpening so they work on a clean signal
      5. unsharp        -- always after all repair; sharpening before repair
                          amplifies artifacts instead of real detail
      6. zscale         -- always after filtering; lanczos + error diffusion
                          dithering for cleaner upscales than basic scale;
                          skipped entirely when --source is set
      7. format=yuv420p -- always final; VideoToolbox pixel format requirement
    """
    try:
        preset = Preset(level)
    except ValueError:
        raise ValueError(f"invalid level: {level} -- must be 1, 2, or 3")

    p = PRESETS[preset]
    filters = [p["deblock"], p["denoise"]]

    if p["has_deband"]:
        filters.append(p["deband"])

    # user repair/analysis filters -- after core repair, before sharpening
    if user_filters:
        filters.extend(user_filters)

    # sharpening always after all repair
    filters.append(p["sharpen"])

    if do_upscale:
        # zscale after filtering -- lanczos + error diffusion dithering
        # portrait: scale width axis; landscape: scale height axis
        if is_portrait:
            filters.append(f"zscale=w={target}:h=-2:filter=lanczos:dither=error_diffusion")
        else:
            filters.append(f"zscale=w=-2:h={target}:filter=lanczos:dither=error_diffusion")

    # format=yuv420p always last -- VideoToolbox pixel format requirement
    filters.append("format=yuv420p")

    return ",".join(filters)


def _try_encode(cmd: list) -> bool:
    """Attempt an ffmpeg encode. Returns True on success, False on failure."""
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False


def _encode(path: str, tmp_path: str, vf: str) -> None:
    """
    Encode with h264_videotoolbox (hardware, fastest) first.
    -hwaccel none forces software decode on input -- required when source is
    AV1 or other codecs VT can't decode natively, otherwise VT rejects the
    frame format even though it's compiled in.
    Falls back to libkvazaar (software H.265) if VT fails.
    Falls back to libx264 (Windows testing) if libkvazaar unavailable.
    Audio always aac. Metadata always stripped.
    """
    base_args = [
        "ffmpeg", "-y",
        "-hwaccel", "none",     # force software decode so VT accepts any input codec
        "-i", path,
        "-map", "0:v:0",        # best video stream only
        "-map", "0:a:0",        # best audio stream only
        "-c:a", "aac",
        "-vf", vf,
        "-map_metadata", "-1",  # strip all metadata
    ]

    # hardware H.264 -- fastest, capture_output=True so silent failure doesn't flood terminal
    if _try_encode(base_args + ["-c:v", "h264_videotoolbox", tmp_path]):
        return

    # libkvazaar fallback (iOS/macOS builds without VT)
    if _try_encode(base_args + ["-c:v", "libkvazaar", tmp_path]):
        print("[ffmpeg] VideoToolbox unavailable, used libkvazaar (H.265)")
        return

    # libx264 fallback (Windows testing)
    print("[ffmpeg] VideoToolbox unavailable, falling back to libx264 (H.264)")
    subprocess.run(base_args + ["-c:v", "libx264", tmp_path], check=True)


def prompt_level(batch: bool = False, skip_prompts: bool = False) -> int:
    """
    Prompt for enhancement level 1-4.
    skip_prompts: if True, return AUTO_DEFAULT_LEVEL (from session context)
    """
    if skip_prompts:
        return AUTO_DEFAULT_LEVEL

    print("\nchoose level 1-4")
    print("  1 - low")
    print("  2 - medium")
    print("  3 - high")
    print(f"  4 - {'skip all' if batch else 'skip'}")
    while True:
        choice = input("enter: ").strip()
        if choice in ("1", "2", "3", "4"):
            return int(choice)
        print("  invalid, enter 1-4")


def enhance(path: str, level: int = None, user_filters: list = None,
            passes: int = 1, ceiling: int = None, out_dir: str = None) -> str:
    """
    Restore and upscale a ####.mp4, optionally across multiple passes.

    ceiling: upscale target cap. None=1440, 0=source lock (enhance only).
    All passes use the chosen level and user filters.

    Returns ex####.mp4 on success, ####.mp4 if skipped or failed.
    """
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        raise FileNotFoundError(f"file not found: {path}")

    w, h, is_portrait, short_side = _get_dims(path)
    dirname  = os.path.dirname(path)
    name     = os.path.splitext(os.path.basename(path))[0]
    final_dir = out_dir if out_dir else dirname
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    is_high_res = (short_side >= 1440)
    source_lock = (ceiling == 0)

    # >= 1440p short side: skip unless source lock (ceiling=0) where user
    # explicitly wants enhancement passes at native resolution
    if is_high_res and not source_lock:
        return path

    if level is None:
        level = prompt_level()

    if level == 4:
        return path

    if source_lock:
        # source lock -- enhance passes times at source resolution, no upscale
        step_list   = [short_side] * passes
        do_upscales = [False] * passes
    else:
        step_list   = _get_steps(short_side, ceiling)
        passes      = min(passes, len(step_list))
        step_list   = step_list[:passes]
        do_upscales = [True] * len(step_list)

    current_path   = path
    current_height = short_side

    for i, target in enumerate(step_list):
        is_last      = (i == len(step_list) - 1)
        do_upscale   = do_upscales[i]
        pass_level   = level
        pass_filters = user_filters

        tmp_path = os.path.join(dirname, f"tmp_{name}_enc.mp4")
        out_path = os.path.join(final_dir, f"ex{name}.mp4") if is_last \
                   else os.path.join(dirname, f"tmp_{name}_p{i + 1}.mp4")

        if source_lock and i >= 2:
            print(f"[warn] pass {i + 1} -- verify output quality, diminishing returns likely")

        if do_upscale:
            print(f"[ffmpeg] pass {i + 1}/{len(step_list)}: {current_height}p -> {target}p (level {pass_level})")
        else:
            # source lock -- refining in place, no resolution change
            print(f"[ffmpeg] pass {i + 1}/{len(step_list)}: {current_height}p refine (level {pass_level})")

        vf = _filter_chain(pass_level, target, pass_filters, is_portrait, do_upscale)

        try:
            _encode(current_path, tmp_path, vf)
            os.replace(tmp_path, out_path)

            # remove intermediate pass file after it's been used as input
            if current_path != path:
                os.remove(current_path)

            current_path   = out_path
            current_height = target if do_upscale else current_height

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            log_error("enhance", e, extra=f"file={os.path.basename(path)} pass={i+1}/{len(step_list)}")
            cleanup_tmp(dirname)
            if current_path != path and os.path.exists(current_path):
                os.remove(current_path)
            return path  # keep original on failure

    # remove original ####.mp4 after all passes succeed
    if os.path.exists(path) and current_path != path:
        os.remove(path)

    return current_path


# CLI
def _parse_args(args: list):
    """
    Flexible arg parser.
    Accepts path, level, --passes, --filters, --auto, --720/1080/1440/source
    in any order.
    """
    path         = None
    level        = None
    user_filters = None
    passes       = 1
    auto         = False
    ceiling      = None  # None = default up to 1440

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
            ceiling = 0  # no upscale, refine in place
            i += 1
        elif a.isdigit() and 1 <= int(a) <= 4 and level is None:
            level = int(a)
            i += 1
        elif path is None and not a.startswith("--"):
            path = a
            i += 1
        else:
            i += 1

    # --auto uses AUTO_DEFAULT_LEVEL unless explicit level given
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
