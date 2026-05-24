# enxr — Handoff Document
# For: Claude Code + Sonnet
# Purpose: Implement pass/ceiling/level constraint system

---

## Project Overview

enxr is a Python CLI video download + enhancement pipeline targeting iOS (a-shell) and Windows (testing). It uses yt-dlp for downloads and FFmpeg for enhancement/upscale. Primary encoder is h264_videotoolbox (Apple HW), falls back to libkvazaar then libx264.

Run with: `python enxr.py`

---

## File Structure

```
enxr/
├── enxr.py              # interactive menu orchestrator
├── ffmpeg.py            # encode/upscale engine
├── enxgui.py            # terminal UI / prompts
├── downloader.py        # yt-dlp wrapper
├── logger.py            # log_error(), cleanup_tmp()
├── filters/
│   └── presets.py       # Preset enum + filter strings per level
├── config/
│   └── settings.py      # constants: AUTO_DEFAULT_LEVEL, DEFAULT_DEST, UPSCALE_CEILING, UPSCALE_STEPS
└── log/                 # created at runtime, YYYY-MM-DD.log on error
```

---

## Current File Contents

### config/settings.py
```python
import os

AUTO_DEFAULT_LEVEL = 2
DEFAULT_DEST       = os.path.expanduser("~/Documents")
UPSCALE_CEILING    = 1440
UPSCALE_STEPS      = [720, 1080, 1440]
```

### filters/presets.py
```python
from enum import Enum

class Preset(Enum):
    LOW    = 1
    MEDIUM = 2
    HIGH   = 3

PRESETS = {
    Preset.LOW: {
        "deblock":    "deblock=filter=strong:block=4:alpha=0.02:beta=0.02:gamma=0.02:delta=0.02",
        "denoise":    "hqdn3d=2:1.5:3:2.5",
        "has_deband": False,
        "deband":     None,
        "sharpen":    "unsharp=lx=3:ly=3:la=0.15:cx=3:cy=3:ca=0.0",
    },
    Preset.MEDIUM: {
        "deblock":    "deblock=filter=strong:block=4:alpha=0.07:beta=0.07:gamma=0.07:delta=0.07",
        "denoise":    "hqdn3d=4:3:6:4.5",
        "has_deband": True,
        "deband":     "deband=range=14:direction=0:blur=1",
        "sharpen":    "unsharp=lx=3:ly=3:la=0.3:cx=3:cy=3:ca=0.0",
    },
    Preset.HIGH: {
        "deblock":    "deblock=filter=strong:block=8:alpha=0.15:beta=0.15:gamma=0.15:delta=0.15",
        "denoise":    "hqdn3d=6:4.5:9:6.75",
        "has_deband": True,
        "deband":     "deband=range=22:direction=0:blur=1",
        "sharpen":    "unsharp=lx=3:ly=3:la=0.45:cx=3:cy=3:ca=0.0",
    },
}
```

### logger.py
```python
import os
import glob
import traceback
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")

def _log_path() -> str:
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, datetime.now().strftime("%Y-%m-%d") + ".log")

def log_error(context: str, error: Exception, extra: str = None) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"[{timestamp}] ERROR [{context}] {error}"]
    if extra:
        lines.append(f"  {extra}")
    tb = traceback.format_exc()
    if tb and tb.strip() != "NoneType: None":
        for line in tb.strip().splitlines():
            lines.append(f"  {line}")
    entry = "\n".join(lines) + "\n"
    with open(_log_path(), "a") as f:
        f.write(entry)
    print(f"[log] {lines[0]}")

def cleanup_tmp(directory: str) -> int:
    removed = 0
    for f in glob.glob(os.path.join(directory, "tmp_*.mp4")):
        try:
            os.remove(f)
            removed += 1
        except OSError:
            pass
    if removed:
        print(f"[log] cleaned {removed} tmp file(s) from {directory}")
    return removed
```

### downloader.py
```python
#!/usr/bin/env python3
"""
downloader.py - core download module
Importable by parent project or run standalone.

Usage:
  python3 downloader.py <URL or file> [URL or file ...]
"""

import os, sys, shutil, random
import yt_dlp

from config.settings import DEFAULT_DEST


def _rand_id(dest: str) -> str:
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
        "buffersize":                    16 * 1024,
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
    os.makedirs(dest, exist_ok=True)
    if _is_url(source):
        file_id  = _rand_id(dest)
        out_path = os.path.join(dest, f"{file_id}.mp4")
        with yt_dlp.YoutubeDL(_yt_opts(dest, file_id)) as ydl:
            ydl.download([source])
        return out_path
    else:
        return _copy_file(source, dest)

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
```

### ffmpeg.py
```python
#!/usr/bin/env python3
"""
ffmpeg.py - enhance + upscale module
Importable by enxr.py or run standalone on any mp4.

Usage:
  python3 ffmpeg.py <####.mp4> [level 1-4] [--passes N] [--filters "f1,f2,..."]
                               [--auto] [--720|--1080|--1440|--source]
"""

import os, sys, subprocess, json

from config.settings import AUTO_DEFAULT_LEVEL, UPSCALE_CEILING, UPSCALE_STEPS
from filters.presets import PRESETS, Preset
from logger import log_error, cleanup_tmp


def _get_dims(path: str) -> tuple:
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
    if ceiling == 0:
        return []
    cap = ceiling if ceiling is not None else UPSCALE_CEILING
    return [t for t in UPSCALE_STEPS if short_side < t <= cap]


def _filter_chain(level: int, target: int, user_filters: list = None,
                  is_portrait: bool = False, do_upscale: bool = True) -> str:
    try:
        preset = Preset(level)
    except ValueError:
        raise ValueError(f"invalid level: {level} -- must be 1, 2, or 3")

    p = PRESETS[preset]
    filters = [p["deblock"], p["denoise"]]
    if p["has_deband"]:
        filters.append(p["deband"])
    if user_filters:
        filters.extend(user_filters)
    filters.append(p["sharpen"])
    if do_upscale:
        if is_portrait:
            filters.append(f"zscale=w={target}:h=-2:filter=lanczos:dither=error_diffusion")
        else:
            filters.append(f"zscale=w=-2:h={target}:filter=lanczos:dither=error_diffusion")
    filters.append("format=yuv420p")
    return ",".join(filters)


def _try_encode(cmd: list) -> bool:
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False


def _encode(path: str, tmp_path: str, vf: str) -> None:
    base_args = [
        "ffmpeg", "-y", "-hwaccel", "none",
        "-i", path,
        "-map", "0:v:0", "-map", "0:a:0",
        "-c:a", "aac", "-vf", vf,
        "-map_metadata", "-1",
    ]
    if _try_encode(base_args + ["-c:v", "h264_videotoolbox", tmp_path]):
        return
    if _try_encode(base_args + ["-c:v", "libkvazaar", tmp_path]):
        print("[ffmpeg] VideoToolbox unavailable, used libkvazaar (H.265)")
        return
    print("[ffmpeg] VideoToolbox unavailable, falling back to libx264 (H.264)")
    subprocess.run(base_args + ["-c:v", "libx264", tmp_path], check=True)


def prompt_level(batch: bool = False, skip_prompts: bool = False) -> int:
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
            passes: int = 1, ceiling: int = None) -> str:
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
    dirname = os.path.dirname(path)
    name    = os.path.splitext(os.path.basename(path))[0]

    is_high_res = (short_side >= 1440)
    source_lock = (ceiling == 0)

    if is_high_res and not source_lock:
        return path

    if level is None:
        level = prompt_level()

    if level == 4:
        return path

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

    for i, target in enumerate(step_list):
        is_last      = (i == len(step_list) - 1)
        do_upscale   = do_upscales[i]
        pass_level   = level
        pass_filters = user_filters

        tmp_path = os.path.join(dirname, f"tmp_{name}_enc.mp4")
        out_path = os.path.join(dirname, f"ex{name}.mp4") if is_last \
                   else os.path.join(dirname, f"tmp_{name}_p{i + 1}.mp4")

        if do_upscale:
            print(f"[ffmpeg] pass {i + 1}/{len(step_list)}: {current_height}p -> {target}p (level {pass_level})")
        else:
            print(f"[ffmpeg] pass {i + 1}/{len(step_list)}: {current_height}p refine (level {pass_level})")

        vf = _filter_chain(pass_level, target, pass_filters, is_portrait, do_upscale)

        try:
            _encode(current_path, tmp_path, vf)
            os.replace(tmp_path, out_path)
            if current_path != path:
                os.remove(current_path)
            current_path   = out_path
            current_height = target if do_upscale else current_height

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            log_error("enhance", e, extra=f"file={os.path.basename(path)} pass={i+1}/{len(step_list)}")
            cleanup_tmp(dirname)
            if current_path != path and os.path.exists(current_path):
                os.remove(current_path)
            return path

    if os.path.exists(path) and current_path != path:
        os.remove(path)

    return current_path


def _parse_args(args: list):
    path = None; level = None; user_filters = None
    passes = 1; auto = False; ceiling = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--filters" and i + 1 < len(args):
            user_filters = [f.strip() for f in args[i + 1].split(",")]; i += 2
        elif a == "--passes" and i + 1 < len(args):
            passes = int(args[i + 1]); i += 2
        elif a == "--auto":
            auto = True; i += 1
        elif a == "--720":
            ceiling = 720; i += 1
        elif a == "--1080":
            ceiling = 1080; i += 1
        elif a == "--1440":
            ceiling = 1440; i += 1
        elif a == "--source":
            ceiling = 0; i += 1
        elif a.isdigit() and 1 <= int(a) <= 4 and level is None:
            level = int(a); i += 1
        elif path is None and not a.startswith("--"):
            path = a; i += 1
        else:
            i += 1
    if auto and level is None:
        level = AUTO_DEFAULT_LEVEL
    return path, level, user_filters, passes, ceiling


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__); sys.exit(0 if args else 1)
    path, level, user_filters, passes, ceiling = _parse_args(args)
    if not path:
        print("error: no input file specified", file=sys.stderr); sys.exit(1)
    try:
        out = enhance(path, level, user_filters, passes, ceiling)
        print(f"[OK] {out}")
    except Exception as e:
        print(f"[!] {e}", file=sys.stderr); sys.exit(1)

if __name__ == "__main__":
    main()
```

### enxgui.py
```python
#!/usr/bin/env python3
"""
enxgui.py - Terminal GUI for ffmpeg.py with interactive stream selection
"""

import os, sys, subprocess, json, re

from ffmpeg import enhance, _get_dims, _get_steps
from config.settings import UPSCALE_CEILING, UPSCALE_STEPS


class Color:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'


def _check_terminal_context() -> dict:
    flags = {'skip_prompts': False, 'auto_mode': False}
    if os.environ.get('SKIP_PROMPTS') == '1' or os.environ.get('SKIP') == 'true':
        flags['skip_prompts'] = True
    if os.environ.get('AUTO') == 'true' or os.environ.get('AUTO_MODE') == '1':
        flags['auto_mode'] = True
    try:
        history_file = os.path.expanduser('~/.bash_history')
        if os.path.exists(history_file):
            with open(history_file, 'r') as f:
                recent = f.readlines()[-20:]
                history_str = ' '.join(recent)
                if re.search(r'skip\s*=\s*[Tt]rue|skip_prompts\s*=\s*1', history_str):
                    flags['skip_prompts'] = True
                if re.search(r'auto\s*=\s*[Tt]rue|auto_mode\s*=\s*1', history_str):
                    flags['auto_mode'] = True
    except:
        pass
    return flags


def _format_resolution(w: int, h: int, is_portrait: bool) -> str:
    orientation = "portrait" if is_portrait else "landscape"
    return f"{w}x{h} ({orientation})"


def _calculate_upscale_options(short_side: int, is_portrait: bool) -> list:
    ceiling = UPSCALE_CEILING
    options = []
    targets = [t for t in UPSCALE_STEPS if short_side < t <= ceiling]
    if short_side >= ceiling:
        return [{"target": short_side, "width": None, "height": None,
                "is_best": True, "label": "Source (enhancement only)"}]
    for target in targets:
        if is_portrait:
            width = target
            height = int(target * 1.777)
        else:
            height = target
            width = int(target * 1.777)
        options.append({
            "target": target,
            "width": width if not is_portrait else target,
            "height": height if is_portrait else target,
            "is_best": (target == targets[-1]),
            "label": f"{target}p"
        })
    return options


def _print_streams_detected(w: int, h: int, short_side: int, is_portrait: bool,
                            options: list) -> None:
    source_res = _format_resolution(w, h, is_portrait)
    print(f"\n{Color.CYAN}-------------------------------------------{Color.RESET}")
    print(f"{Color.BOLD}Source Resolution:{Color.RESET} {source_res}")
    print(f"{Color.BOLD}Short side:{Color.RESET} {short_side}p")
    print(f"{Color.CYAN}-------------------------------------------{Color.RESET}")
    print(f"\n{Color.BOLD}Upscale Options:{Color.RESET}")
    for opt in options:
        label = opt['label']
        is_best = opt['is_best']
        if is_best:
            print(f"  {Color.GREEN}* {label}{Color.RESET}")
        else:
            print(f"    {label}")
    print(f"\n{Color.BOLD}Ceiling:{Color.RESET} 1440p short side")
    if is_portrait:
        print(f"  {Color.DIM}(max 1440x2560 portrait){Color.RESET}")
    else:
        print(f"  {Color.DIM}(max 2560x1440 landscape){Color.RESET}")


def _print_why_skip(short_side: int, ceiling: int = UPSCALE_CEILING) -> None:
    print(f"\n{Color.YELLOW}! Why skip upscale?{Color.RESET}")
    print(f"  Source is {short_side}p (already at ceiling)")
    print(f"  Upscaling would degrade quality")
    print(f"  Recommend: enhancement only (--source flag) for refinement")


def prompt_upscale(skip_prompts: bool = False, is_high_res: bool = False) -> bool:
    if skip_prompts:
        return not is_high_res
    if is_high_res:
        _print_why_skip(UPSCALE_CEILING)
        while True:
            choice = input(f"\n{Color.BOLD}Enhancement only? (y/n):{Color.RESET} ").strip().lower()
            if choice in ('y', 'n'):
                return (choice == 'y')
            print("  invalid, enter y or n")
    print(f"\n{Color.BOLD}Upscale this file?{Color.RESET}")
    while True:
        choice = input("  (yes/no): ").strip().lower()
        if choice in ('yes', 'y'):
            return True
        elif choice in ('no', 'n'):
            return False
        print("  invalid, enter yes or no")


def prompt_level(skip_prompts: bool = False) -> int:
    if skip_prompts:
        return 2
    print(f"\n{Color.BOLD}Choose enhancement level:{Color.RESET}")
    print("  1 - low    (mild deblock, denoise)")
    print("  2 - medium (standard, recommended)")
    print("  3 - high   (aggressive, for heavily compressed)")
    print("  4 - skip   (no enhancement, output=input)")
    while True:
        choice = input(f"{Color.BOLD}Level:{Color.RESET} ").strip()
        if choice in ("1", "2", "3", "4"):
            return int(choice)
        print("  invalid, enter 1-4")


def prompt_passes(skip_prompts: bool = False) -> int:
    if skip_prompts:
        return 1
    print(f"\n{Color.BOLD}Number of passes:{Color.RESET}")
    print("  Each pass upscales one step (720->1080->1440)")
    print("  1 = single pass to next ceiling")
    print("  2+ = multiple refinement passes")
    while True:
        choice = input(f"{Color.BOLD}Passes (1-4):{Color.RESET} ").strip()
        if choice.isdigit() and 1 <= int(choice) <= 4:
            return int(choice)
        print("  invalid, enter 1-4")


def _parse_gui_args(args: list) -> tuple:
    path = None; passes_override = None; skip_prompts_flag = False
    for i, arg in enumerate(args):
        if arg == '--skip':
            skip_prompts_flag = True
        elif arg == '--passes' and i + 1 < len(args):
            passes_override = int(args[i + 1])
        elif not arg.startswith('--') and path is None:
            path = arg
    return path, passes_override, skip_prompts_flag


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__); sys.exit(0 if args else 1)
    path, passes_override, skip_prompts_flag = _parse_gui_args(args)
    if not path:
        print(f"{Color.RED}error: no input file specified{Color.RESET}", file=sys.stderr)
        sys.exit(1)
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        print(f"{Color.RED}error: file not found: {path}{Color.RESET}", file=sys.stderr)
        sys.exit(1)
    context = _check_terminal_context()
    skip_all_prompts = skip_prompts_flag or context['skip_prompts']
    try:
        w, h, is_portrait, short_side = _get_dims(path)
        options = _calculate_upscale_options(short_side, is_portrait)
        _print_streams_detected(w, h, short_side, is_portrait, options)
        is_high_res = (short_side >= UPSCALE_CEILING)
        should_upscale = prompt_upscale(skip_all_prompts, is_high_res)
        if not should_upscale:
            print(f"\n{Color.YELLOW}Skipping enhancement.{Color.RESET}"); sys.exit(0)
        level = prompt_level(skip_all_prompts)
        if level == 4:
            print(f"\n{Color.YELLOW}Level 4: Skipping enhancement.{Color.RESET}"); sys.exit(0)
        passes = passes_override if passes_override else prompt_passes(skip_all_prompts)
        ceiling = 0 if is_high_res else UPSCALE_CEILING
        print(f"\n{Color.CYAN}Processing...{Color.RESET}")
        out = enhance(path, level=level, user_filters=None, passes=passes, ceiling=ceiling)
        print(f"\n{Color.GREEN}* Done!{Color.RESET} {out}")
    except Exception as e:
        print(f"\n{Color.RED}error: {e}{Color.RESET}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
```

### enxr.py
(See full file at c:\enxr\enxr.py — imports: downloader, ffmpeg, logger, config.settings, enxgui)

---

## What Was Built This Session

- Migrated 4 flat scripts into structured package (enxr/, ffmpeg/, filters/, config/, logger)
- Renamed: main.py → enxr.py, enx.py → ffmpeg.py
- Replaced dctdnoiz with hqdn3d across all 3 presets
- Added Preset enum (LOW/MEDIUM/HIGH) to filters/presets.py
- Centralized all constants into config/settings.py (UPSCALE_CEILING, UPSCALE_STEPS, AUTO_DEFAULT_LEVEL, DEFAULT_DEST)
- Added logger.py: log_error() writes timestamped errors + tracebacks to log/YYYY-MM-DD.log, cleanup_tmp() removes tmp_*.mp4 on failure
- tmp files are preserved during active ffmpeg encode; only cleaned on exception
- Removed "pass 2+ uses level 1" rule — all passes now use chosen level + filters
- Encoder fallback chain: h264_videotoolbox → libkvazaar → libx264
- All Unicode chars replaced with ASCII for Windows cp1252 compatibility

---

## NOW IMPLEMENT: Pass / Ceiling / Level Constraint System

### Design Decisions (agreed)

**Ceiling — auto-derive from source, display as info only. User makes no choice.**

| Source short_side | Max ceiling |
|-------------------|-------------|
| < 480p            | 1080p       |
| 480p–719p         | 1080p       |
| 720p–1079p        | 1440p       |
| 1080p–1439p       | 1440p       |
| 1440p+            | source lock (ceiling=0) |

**Passes — hard cap per ceiling, warn if user enters more than allowed, never silent.**

| Ceiling     | Max passes |
|-------------|------------|
| source lock | 4          |
| 1440p       | 3          |
| 1080p       | 2          |
| 720p        | 2          |

Level 3 hard cap: max 2 passes regardless of ceiling.

**Refinement loop (source lock) — free, soft warn at pass 3+:**
```
[warn] pass 3+ -- verify output quality, diminishing returns likely
```

**Level stays fully independent. No coupling to ceiling or passes except level 3 pass cap.**

**No --force flag for now.**

### UX Flow Change

Before pass prompt, display:
```
Source: 720p
Max output: 1440p
Available passes: 2  (720->1080, 1080->1440)
```
User sees real number before picking. No silent cap.

### Aggressive settings soft warning (level 3 + passes >= 2):
```
[warn] Aggressive settings -- verify output quality before keeping
```
One line, no confirm, printed before encode starts.

### Where to implement

1. **config/settings.py** — add:
   - `SOURCE_CEILING_MAP` — maps source res ranges to ceiling int
   - `CEILING_MAX_PASSES` — maps ceiling to max passes int
   - `LEVEL3_MAX_PASSES = 2`

2. **ffmpeg.py** — add two functions:
   - `get_ceiling(short_side: int) -> int` — derives ceiling from source using SOURCE_CEILING_MAP
   - `cap_passes(passes: int, ceiling: int, level: int) -> int` — caps passes, prints warn if capped, returns capped value

3. **enxgui.py / enxr.py** — update prompt flow:
   - Call `get_ceiling(short_side)` instead of hardcoding 1440
   - Display source/ceiling/available passes info block before pass prompt
   - Call `cap_passes()` after user enters passes
   - Print aggressive settings warning when level==3 and passes>=2, before enhance() call
   - Refinement warn inside enhance() loop at pass index >= 2 when source_lock

### Verify after each change
Run: `echo "6" | python enxr.py` — must exit cleanly before moving to next step.

---

## Open Questions (Claude Code / Sonnet to answer if needed)

- Should `get_ceiling()` live in ffmpeg.py or config/settings.py? (suggestion: ffmpeg.py, it's logic not data)
- Should the pass info display ("Available passes: 2") live in enxgui.py `_print_streams_detected()` or as its own function?
- Is the refinement warn best placed in `enhance()` loop or in the caller (enxr.py / enxgui.py)?

---

## Environment

- Platform: Windows 10, testing. Target: iOS (a-shell)
- Python 3.11.9
- FFmpeg 8.1 (Windows build with libx264, libx265, no VideoToolbox)
- yt-dlp 2026.3.17
- Run from: c:\enxr\
- Shell: Git Bash (defaultShell: bash)
- Contact: gleeky@tuta.io
