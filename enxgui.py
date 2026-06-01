#!/usr/bin/env python3
"""
enxgui.py - Terminal GUI for enxr with interactive stream selection

Detects source resolution and quality tier, displays upscale options,
and prompts for enhancement preferences.

Usage:
  python3 enxgui.py <file.mp4> [--passes N] [--skip]
"""

import os, sys, re

import time

from ffmpeg import enhance, _get_dims, get_ceiling, _detect_tier
from config import UPSCALE_STEPS, build_chain
from config import UPSCALE_CEILING  # noqa: F401  (kept for external/back-compat imports)
from calibration import (load_calibration, run_calibration, estimate_time,
                         update_calibration, get_duration)


class Color:
    GREEN  = '\033[92m'
    RED    = '\033[91m'
    YELLOW = '\033[93m'
    CYAN   = '\033[96m'
    WHITE  = '\033[97m'
    BOLD   = '\033[1m'
    DIM    = '\033[2m'
    RESET  = '\033[0m'


def _rl_safe(s: str) -> str:
    """Wrap ANSI escapes so readline counts cursor width correctly."""
    if os.name == 'nt':
        return s
    return re.sub(r'(\033\[[0-9;]*m)', r'\001\1\002', s)


class GoBack(Exception):
    """Raised when the user types 'back' at a prompt -- unwinds to the menu."""
    pass


def _ask(prompt: str) -> str:
    """input() wrapper -- type 'back'/'go back'/'b' to return to the menu."""
    val = input(_rl_safe(prompt)).strip()
    if val.lower() in ('back', 'go back', 'b'):
        raise GoBack()
    return val


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
                history_str = ' '.join(f.readlines()[-20:])
            if re.search(r'skip\s*=\s*[Tt]rue|skip_prompts\s*=\s*1', history_str):
                flags['skip_prompts'] = True
    except Exception:
        pass
    return flags


def _format_resolution(w: int, h: int, is_portrait: bool) -> str:
    return f"{w}x{h} ({'portrait' if is_portrait else 'landscape'})"


def _calculate_upscale_options(short_side: int, is_portrait: bool) -> list:
    ceiling = get_ceiling(short_side)
    targets = [t for t in UPSCALE_STEPS if short_side < t <= ceiling] if ceiling else []
    if not targets:
        return [{"target": short_side, "is_best": True,
                 "label": "Source (enhancement only)"}]
    return [{"target": t, "is_best": (t == targets[-1]), "label": f"{t}p"}
            for t in targets]


def _print_streams_detected(w: int, h: int, short_side: int,
                            is_portrait: bool, options: list,
                            tier: int = None) -> None:
    tier_names = {1: "excellent", 2: "good", 3: "fair", 4: "poor", 5: "broken"}
    print(f"\n{Color.CYAN}-------------------------------------------{Color.RESET}")
    print(f"{Color.BOLD}Source:{Color.RESET} {_format_resolution(w, h, is_portrait)}")
    print(f"{Color.BOLD}Short side:{Color.RESET} {short_side}p")
    if tier:
        print(f"{Color.BOLD}Quality tier:{Color.RESET} {tier} "
              f"({Color.DIM}{tier_names.get(tier, '?')}{Color.RESET})")
    print(f"{Color.CYAN}-------------------------------------------{Color.RESET}")
    print(f"\n{Color.BOLD}Upscale options:{Color.RESET}")
    for opt in options:
        if opt['is_best']:
            print(f"  {Color.GREEN}* {opt['label']}{Color.RESET}")
        else:
            print(f"    {opt['label']}")
    ceiling = get_ceiling(short_side)
    orientation = "portrait" if is_portrait else "landscape"
    if ceiling:
        w = int(ceiling * 16 / 9) if not is_portrait else int(ceiling * 9 / 16)
        print(f"\n{Color.BOLD}Ceiling:{Color.RESET} {ceiling}p short side")
        print(f"  {Color.DIM}(max {ceiling}x{w} {orientation}){Color.RESET}")
    else:
        print(f"\n{Color.BOLD}Ceiling:{Color.RESET} {Color.DIM}at or above 1440p (no upscale){Color.RESET}")


def prompt_resolution(options: list, short_side: int,
                      skip_prompts: bool = False) -> int:
    """Prompt 1 -- target resolution based on source. Returns target short-side.
    Always shows source (0) as an option, plus any valid upscale targets.
    """
    recommended = options[-1]['target'] if options else short_side
    if skip_prompts:
        return recommended
    print(f"\n{Color.BOLD}1. Resolution:{Color.RESET} "
          f"{Color.DIM}(source {short_side}p){Color.RESET}")
    print(f"  0 - source {short_side}p {Color.DIM}(no upscale){Color.RESET}")
    for i, opt in enumerate(options):
        star = f"  {Color.DIM}(best){Color.RESET}" if opt['target'] == recommended else ""
        print(f"  {i + 1} - {opt['label']}{star}")
    while True:
        choice = _ask(f"{Color.BOLD}Choice (0-{len(options)}, enter for {recommended}p):{Color.RESET} ")
        if choice == "":
            return recommended
        if choice == "0":
            return short_side
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1]['target']
        print(f"  invalid, enter 0-{len(options)}, enter for best (or 'back')")


def _prompt_level(title: str, lines: list, default: int,
                  skip_prompts: bool = False) -> int:
    """Shared 0-5 level prompt. Returns 0-5 (0 = off)."""
    if skip_prompts:
        return default
    print(f"\n{Color.BOLD}{title}:{Color.RESET} {Color.DIM}(enter for {default}){Color.RESET}")
    for ln in lines:
        print(ln)
    while True:
        choice = _ask(f"{Color.BOLD}Level (0-5):{Color.RESET} ")
        if choice == "":
            return default
        if choice in ("0", "1", "2", "3", "4", "5"):
            return int(choice)
        print("  invalid, enter 0-5, enter for default (or 'back')")


def prompt_restore(skip_prompts: bool = False, suggested: int = 2) -> int:
    """Prompt 2 -- restore (deblock/deband) strength 0-5. suggested = auto tier."""
    return _prompt_level(
        "2. Restore level",
        ["  0 - none",
         "  1 - light",
         "  2 - mild       (clean source)",
         "  3 - standard   (typical YT)",
         "  4 - aggressive (compressed)",
         "  5 - max        (broken source)"],
        default=max(0, min(5, suggested)),
        skip_prompts=skip_prompts,
    )


def prompt_enhance(skip_prompts: bool = False, default: int = 3) -> int:
    """Prompt 3 -- enhance (sharpen) strength 0-5."""
    return _prompt_level(
        "3. Enhance level",
        ["  0 - none",
         "  1 - subtle",
         "  2 - light",
         "  3 - standard",
         "  4 - strong",
         "  5 - max sharp"],
        default=default,
        skip_prompts=skip_prompts,
    )


def _parse_gui_args(args: list) -> tuple:
    path = None
    skip_prompts_flag = False
    for arg in args:
        if arg == '--skip':
            skip_prompts_flag = True
        elif not arg.startswith('--') and path is None:
            path = arg
    return path, skip_prompts_flag


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0 if args else 1)

    path, skip_prompts_flag = _parse_gui_args(args)

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
        w, h, is_portrait, short_side, codec = _get_dims(path)
        tier    = _detect_tier(path, w, h)
        options = _calculate_upscale_options(short_side, is_portrait)

        _print_streams_detected(w, h, short_side, is_portrait, options, tier)

        # 3 prompts: resolution -> restore -> enhance
        target_res    = prompt_resolution(options, short_side, skip_all_prompts)
        restore_level = prompt_restore(skip_all_prompts, suggested=tier)
        enhance_level = prompt_enhance(skip_all_prompts)

        # Render time estimate / calibration
        duration = get_duration(path)
        cal      = load_calibration()
        cal_key  = str(target_res)
        if cal_key not in cal:
            print(f"\n  {Color.DIM}[first run] calibrating encoder speed...{Color.RESET}")
            try:
                cal_vf = build_chain(restore_level, enhance_level, target_res,
                                     is_portrait, target_res > short_side)
                run_calibration(path, cal_vf, target_res)
                cal = load_calibration()
            except Exception:
                pass
        if cal_key in cal and duration > 0:
            est = estimate_time(duration, 1, target_res, cal)
            if est:
                print(f"  {Color.DIM}Estimated time: {est}  (at {target_res}p){Color.RESET}")

        print(f"\n{Color.CYAN}Processing...{Color.RESET}")
        t0  = time.time()
        out = enhance(path, restore_level=restore_level, enhance_level=enhance_level,
                      target_res=target_res)
        elapsed = time.time() - t0
        try:
            update_calibration(target_res, elapsed, duration)
        except Exception:
            pass
        print(f"\n{Color.GREEN}* Done!{Color.RESET} {out}")

    except GoBack:
        print(f"\n{Color.YELLOW}Cancelled.{Color.RESET}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Color.RED}error: {e}{Color.RESET}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
