#!/usr/bin/env python3
"""
ffmpeg.py - enhance + upscale module

Single-pass pipeline (one encode):
  format -> restore (deblock/deband) -> sharpen (unsharp) -> scale -> format

Restore and enhance(sharpen) are independent strength levels 0-5 (0 = off).
Scaling is always the LAST operation so sharpening runs at source resolution.

Usage:
  python3 ffmpeg.py <file.mp4> [--restore N] [--enhance N]
                               [--res 720|1080|1440] [--source]
"""

import os, sys, shutil, subprocess, json, time, platform

from config import build_chain, get_ceiling
from logger import log_error, cleanup_tmp


# ── dimension + step helpers ─────────────────────────────────────────────────

def _get_dims(path: str) -> tuple:
    """Returns (width, height, is_portrait, short_side, codec_name)."""
    if shutil.which("ffprobe") is None:
        raise FileNotFoundError("ffprobe not found -- is FFmpeg installed and on PATH?")

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,codec_name", "-of", "json", path],
            capture_output=True, text=True, check=True,
        )
        streams = json.loads(result.stdout).get("streams", [])
        if not streams:
            raise ValueError(f"no video stream found in: {path}")
        w = int(streams[0]["width"])
        h = int(streams[0]["height"])
        codec = streams[0].get("codec_name", "unknown")
        return w, h, h > w, min(w, h), codec
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        raise RuntimeError(f"ffprobe failed: {stderr or 'unknown error'}")


# get_ceiling is imported from config (single source of truth for the ladder).


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


# ── encoder strategy ──────────────────────────────────────────────────────────

def _has_nvidia_gpu() -> bool:
    """True if a dedicated NVIDIA GPU is present (nvidia-smi lists one)."""
    try:
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=5)
        return r.returncode == 0 and "GPU" in r.stdout
    except Exception:
        return False


def _available_encoders() -> set:
    """Names of encoders this ffmpeg build actually supports."""
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                           capture_output=True, text=True, timeout=10)
        out = r.stdout + r.stderr
        names = set()
        for line in out.splitlines():
            parts = line.split()
            # encoder rows look like: " V..... h264_videotoolbox  ..."
            if len(parts) >= 2 and parts[0][0:1] == "V":
                names.add(parts[1])
        return names
    except Exception:
        return set()


def _get_encoder_chain() -> list:
    """Pick the encoder chain by what ffmpeg actually has, not the OS string
    (A-Shell/iSH report unreliable platforms). VideoToolbox is preferred on
    Apple devices; NVENC when a dedicated NVIDIA GPU is present. libx264 is
    always the final, guaranteed fallback.
    """
    have = _available_encoders()
    chain = []

    if "h264_videotoolbox" in have:
        chain.append("h264_videotoolbox")
    elif "h264_nvenc" in have and _has_nvidia_gpu():
        chain.append("h264_nvenc")

    chain.append("libx264")   # always last -- proven everywhere

    print(f"[ffmpeg] encoder chain: {' > '.join(chain)}")
    return chain


def _encoder_args(codec: str, denoise_preset: str = "med") -> list:
    """Return codec-specific FFmpeg args, tuned by denoise preset.

    Presets map to: very_fast (batch) → fast (clean) → med (balanced) → slow (quality)
    """
    if codec in ("libx264", "libx265"):
        # Tune preset + CRF by denoise tier
        preset_map = {
            "very_fast": ("ultrafast", "28"),
            "fast":      ("fast", "26"),
            "med":       ("medium", "23"),
            "slow":      ("slow", "22"),
        }
        preset, crf = preset_map.get(denoise_preset, ("medium", "23"))
        return ["-preset", preset, "-crf", crf, "-profile:v", "main", "-g", "250"]
    if codec == "libvpx":
        return ["-deadline", "good", "-cpu-used", "4", "-crf", "30"]
    if codec == "libaom":
        return ["-cpu-used", "4", "-crf", "30"]
    return []


# ── encoder ───────────────────────────────────────────────────────────────────

def _file_valid(path: str) -> bool:
    """Quick ffprobe check -- True if file has a readable video stream."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type", "-of", "json", path],
            capture_output=True, text=True, timeout=8,
        )
        return r.returncode == 0 and "video" in r.stdout
    except Exception:
        return False


def _try_encode(cmd: list, tmp_path: str, progress_cb=None) -> tuple:
    """
    Attempt an ffmpeg encode. Returns (True, '') on success, (False, stderr) on failure.

    iOS SIGINT recovery: a-shell sends SIGINT (signal 2) when backgrounded --
    sometimes AFTER encoding completes but during final container cleanup.
    If the process exits non-zero but the output file exists and is large/valid,
    treat as success rather than falling through to the next encoder.

    progress_cb: optional callable(line: str) — receives each ffmpeg stderr line.
    When set, uses Popen for streaming; otherwise uses subprocess.run (CLI path).
    """
    if progress_cb is None:
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return True, ""
        except subprocess.CalledProcessError as e:
            if os.path.isfile(tmp_path):
                time.sleep(0.5)
                size = os.path.getsize(tmp_path)
                if size > 102400:
                    if _file_valid(tmp_path):
                        print("[ffmpeg] signal interrupt after encode -- output valid, continuing")
                        return True, ""
                    if size > 1024 * 1024:
                        print(f"[ffmpeg] signal interrupt -- ffprobe inconclusive but file is {size // 1024}KB, treating as valid")
                        return True, ""
            return False, e.stderr or ""
    else:
        stderr_lines = []
        try:
            proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    text=True)
            for line in proc.stderr:
                line = line.rstrip()
                stderr_lines.append(line)
                progress_cb(line)
            proc.wait()
        except Exception as e:
            return False, str(e)
        if proc.returncode == 0:
            return True, ""
        if os.path.isfile(tmp_path):
            time.sleep(0.5)
            size = os.path.getsize(tmp_path)
            if size > 102400:
                if _file_valid(tmp_path):
                    return True, ""
                if size > 1024 * 1024:
                    return True, ""
        return False, "\n".join(stderr_lines[-20:])


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


def _check_ffmpeg_tools() -> bool:
    """Verify FFmpeg and ffprobe are available on PATH."""
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        print(f"[ffmpeg] missing required tool(s): {', '.join(missing)}")
        return False
    return True


def _encode(path: str, tmp_path: str, vf: str, denoise_preset: str = "med", progress_cb=None) -> None:
    """
    Encode using OS-specific encoder chain (hardware-first).
    -hwaccel none forces software decode -- required for AV1/non-native codecs.
    Audio optional (0:a:0?) and transcoded to aac. Metadata always stripped.
    denoise_preset tunes encoder settings (very_fast/fast/med/slow).
    """
    base_args = [
        "ffmpeg", "-y",
        "-hwaccel", "none",
        "-i", path,
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c:a", "aac",
        "-vf", vf,
        "-pix_fmt", "yuv420p",
        "-map_metadata", "-1",
    ]

    encoder_chain = _get_encoder_chain()
    last_error = None

    for codec in encoder_chain:
        codec_args = _encoder_args(codec, denoise_preset)
        cmd = base_args + ["-c:v", codec] + codec_args + [tmp_path]

        ok, err = _try_encode(cmd, tmp_path, progress_cb)
        if ok:
            if codec != encoder_chain[0]:
                print(f"[ffmpeg] {encoder_chain[0]} unavailable, used {codec}")
            return
        last_error = _ffmpeg_errors(err)
        log_error(codec, RuntimeError(last_error))

    raise RuntimeError(
        f"no compatible encoder found -- {' > '.join(encoder_chain)} all failed. "
        f"last error: {last_error}"
    )


# ── main enhance (single pass) ──────────────────────────────────────────────────

def enhance(path: str, denoise_preset: str = "med", enhance_level: int = 3,
            target_res: int = None, ceiling: int = None, out_dir: str = None,
            keep_original: bool = False, skip_existing: bool = False,
            user_filters: list = None, progress_cb=None) -> str:
    """
    Single-pass denoise + sharpen + scale (one encode).

    denoise_preset: "slow" (best), "med" (1x realtime), "fast" (clean), "very_fast" (batch).
    enhance_level: 0-5 unsharp strength (0 = none).
    target_res:    explicit scale target short-side (e.g. 1440). None = derive.
    ceiling:       0 = source lock (no scale). None = auto from source.
    out_dir:       final output directory (defaults to same dir as input).
    skip_existing: if ex<name>.mp4 already exists, return it without re-encoding.

    Scaling is the last filter in the chain, so sharpening runs at source res.
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

    enhance_level = max(0, min(5, int(enhance_level)))
    if denoise_preset not in ("slow", "med", "fast", "very_fast"):
        denoise_preset = "med"

    out_path = os.path.join(final_dir, f"ex{name}.mp4")
    if skip_existing and os.path.isfile(out_path):
        if _file_valid(out_path):
            print(f"[ffmpeg] skip -- already enhanced: {os.path.basename(out_path)}")
            return out_path
        print(f"[ffmpeg] existing output is invalid or incomplete, re-encoding: {os.path.basename(out_path)}")

    # Derive effective scale target
    if ceiling == 0:
        eff_target = short_side
    elif target_res is not None:
        eff_target = target_res
    elif ceiling is not None:
        eff_target = ceiling
    else:
        auto_ceil  = get_ceiling(short_side)
        eff_target = auto_ceil if auto_ceil > 0 else short_side

    do_scale = eff_target > short_side

    # Nothing to do -- no denoise, no sharpen, no scale
    if denoise_preset == "very_fast" and enhance_level == 0 and not do_scale:
        print("[ffmpeg] nothing to do (denoise=off, enhance=0, no scale)")
        return path

    vf      = build_chain(denoise_preset, enhance_level, eff_target,
                          is_portrait, do_scale, user_filters)
    tmp_enc = os.path.join(dirname, f"tmp_{name}_enc.mp4")

    stage = (f"{short_side}p -> {eff_target}p" if do_scale else f"{short_side}p")
    print(f"[ffmpeg] {stage}  denoise={denoise_preset} enhance={enhance_level}")
    if progress_cb:
        progress_cb(f"__stage__:enhance:{stage} denoise={denoise_preset} e{enhance_level}")

    try:
        if not _check_ffmpeg_tools():
            raise FileNotFoundError("FFmpeg or ffprobe is not available on PATH")

        _encode(path, tmp_enc, vf, denoise_preset=denoise_preset, progress_cb=progress_cb)
        os.replace(tmp_enc, out_path)
    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError) as e:
        log_error("enhance", e, extra=f"file={os.path.basename(path)}")
        cleanup_tmp(dirname)
        if os.path.isfile(tmp_enc):
            try:
                os.remove(tmp_enc)
            except OSError:
                pass
        raise

    # Remove original after success (unless caller wants to keep it)
    if not keep_original and os.path.exists(path) and out_path != path:
        os.remove(path)

    return out_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args(args: list):
    path = denoise = enhance_lvl = target_res = ceiling = None
    denoise, enhance_lvl = "med", 3
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--denoise" and i + 1 < len(args):
            denoise = args[i + 1]; i += 2
        elif a == "--enhance" and i + 1 < len(args):
            enhance_lvl = int(args[i + 1]); i += 2
        elif a == "--res" and i + 1 < len(args):
            target_res = int(args[i + 1]); i += 2
        elif a in ("--720", "--1080", "--1440"):
            target_res = int(a.lstrip("-")); i += 1
        elif a == "--source":
            ceiling = 0; i += 1
        elif path is None and not a.startswith("--"):
            path = a; i += 1
        else:
            i += 1
    return path, denoise, enhance_lvl, target_res, ceiling


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if args else 1)

    if not _check_ffmpeg_tools():
        print("error: ffmpeg or ffprobe not available on PATH", file=sys.stderr)
        sys.exit(1)

    path, denoise, enhance_lvl, target_res, ceiling = _parse_args(args)

    if not path:
        print("error: no input file specified", file=sys.stderr)
        sys.exit(1)

    try:
        out = enhance(path, denoise_preset=denoise, enhance_level=enhance_lvl,
                      target_res=target_res, ceiling=ceiling)
        print(f"[OK] {out}")
    except Exception as e:
        print(f"[!] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
