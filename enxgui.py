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

from ffmpeg import enhance, _get_dims, get_ceiling, _detect_tier, _main_chain
from config.settings import UPSCALE_CEILING, UPSCALE_STEPS
from calibration import (load_calibration, run_calibration, estimate_time,
                         update_calibration, get_duration)
from filters.presets import EnhancePreset, SECRET_FILTERS


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
    ceiling = UPSCALE_CEILING
    if short_side >= ceiling:
        return [{"target": short_side, "is_best": True,
                 "label": "Source (enhancement only)"}]
    targets = [t for t in UPSCALE_STEPS if short_side < t <= ceiling]
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
    orientation = "portrait" if is_portrait else "landscape"
    print(f"\n{Color.BOLD}Ceiling:{Color.RESET} 1440p short side")
    print(f"  {Color.DIM}(max {'1440x2560' if is_portrait else '2560x1440'} "
          f"{orientation}){Color.RESET}")


def _print_why_skip(short_side: int, ceiling: int = UPSCALE_CEILING) -> None:
    print(f"\n{Color.YELLOW}! Source is {short_side}p (at ceiling){Color.RESET}")
    print(f"  Upscaling would degrade quality")
    print(f"  Enhancement-only mode recommended")


def prompt_upscale(skip_prompts: bool = False, is_high_res: bool = False) -> bool:
    if skip_prompts:
        return not is_high_res
    if is_high_res:
        _print_why_skip(UPSCALE_CEILING)
        while True:
            choice = input(_rl_safe(f"\n{Color.BOLD}Enhancement only? (y/n):{Color.RESET} ")).strip().lower()
            if choice in ('y', 'n'):
                return choice == 'y'
            print("  invalid, enter y or n")
    print(f"\n{Color.BOLD}Upscale this file?{Color.RESET}")
    while True:
        choice = input("  (yes/no): ").strip().lower()
        if choice in ('yes', 'y'):   return True
        if choice in ('no',  'n'):   return False
        print("  invalid, enter yes or no")


def prompt_level(skip_prompts: bool = False) -> int:
    """
    Prompt for quality tier override.
    Returns tier 1-5, or None for auto-detect, or 0 to skip.
    """
    if skip_prompts:
        return None  # auto

    print(f"\n{Color.BOLD}Quality tier:{Color.RESET} {Color.DIM}(enter for auto-detect){Color.RESET}")
    print("  auto - detect from source bitrate")
    print("  1    - excellent  (sharpen only)")
    print("  2    - good       (light restore)")
    print("  3    - fair       (standard, typical YT)")
    print("  4    - poor       (aggressive restore)")
    print("  5    - broken     (max restore)")
    print("  0    - skip enhancement")

    while True:
        choice = input(_rl_safe(f"{Color.BOLD}Tier:{Color.RESET} ")).strip()
        if choice == "":
            return None
        if choice in ("0", "1", "2", "3", "4", "5"):
            return int(choice)
        print("  invalid, enter 0-5 or press enter for auto")


def prompt_target_res(options: list, skip_prompts: bool = False) -> int:
    """Prompt user to pick target resolution. Returns target resolution integer."""
    if skip_prompts:
        return options[-1]['target']
    recommended = options[-1]['target']
    print(f"\n{Color.BOLD}Target resolution:{Color.RESET}")
    for i, opt in enumerate(options):
        star = f"  {Color.DIM}(recommended){Color.RESET}" if opt['target'] == recommended else ""
        print(f"  {i + 1} - {opt['label']}{star}")
    while True:
        choice = input(
            _rl_safe(f"{Color.BOLD}Target (1-{len(options)}, enter for {recommended}p):{Color.RESET} ")
        ).strip()
        if choice == "":
            return recommended
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1]['target']
        print(f"  invalid, enter 1-{len(options)} or press enter")


def prompt_passes(skip_prompts: bool = False) -> int:
    if skip_prompts:
        return 1
    print(f"\n{Color.BOLD}Number of passes:{Color.RESET}")
    print("  1 = single enhancement")
    print("  2+ = refinement passes (strength auto-reduces each pass)")
    while True:
        choice = input(_rl_safe(f"{Color.BOLD}Passes (1-4):{Color.RESET} ")).strip()
        if choice.isdigit() and 1 <= int(choice) <= 4:
            return int(choice)
        print("  invalid, enter 1-4")


def _prompt_secret_menu() -> tuple:
    """Secret preset menu. Returns (None, user_filters list)."""
    print(f"\n{Color.DIM}[secret menu]{Color.RESET}")
    print("  a - raw unsharp (no deblock/deband)")
    print("  b - dctdnoiz only")
    print("  c - fftdnoiz only")
    print("  d - deflicker only")
    print("  e - custom filter string (advanced)")
    while True:
        choice = input(_rl_safe(f"{Color.BOLD}:{Color.RESET} ")).strip().lower()
        if choice in ('a', 'b', 'c', 'd'):
            return (None, list(SECRET_FILTERS[choice]))
        if choice == 'e':
            fstr = input(_rl_safe(f"{Color.BOLD}filter string:{Color.RESET} ")).strip()
            if fstr:
                return (None, [f.strip() for f in fstr.split(',')])
            print("  enter a filter string")
        else:
            print("  enter a, b, c, d, or e")


def prompt_preset(skip_prompts: bool = False) -> tuple:
    """
    Show named preset menu (multi-pass only).
    Returns (EnhancePreset | None, user_filters | None).
    """
    if skip_prompts:
        return (EnhancePreset.CLEAN, None)
    preset_map = {
        '1': EnhancePreset.CLEAN,
        '2': EnhancePreset.RESTORE,
        '3': EnhancePreset.SHARP,
        '4': EnhancePreset.CINEMATIC,
        '5': EnhancePreset.DEEP_CLEAN,
        '6': EnhancePreset.STABILIZE,
    }
    print(f"\n{Color.BOLD}Enhancement preset:{Color.RESET}")
    print("  1 - Clean       (deblock + deband, safe)")
    print("  2 - Restore     (+ light denoise, typical YT)")
    print("  3 - Sharp       (sharpening focus)")
    print("  4 - Cinematic   (color + tone)")
    print("  5 - Deep Clean  (max artifact removal, slow)")
    print("  6 - Stabilize   (deshake + deflicker)")
    print(f"  {Color.DIM}secret..        (type 'x'){Color.RESET}")
    while True:
        choice = input(_rl_safe(f"{Color.BOLD}Preset:{Color.RESET} ")).strip().lower()
        if choice in preset_map:
            return (preset_map[choice], None)
        if choice in ('x', 'secret'):
            return _prompt_secret_menu()
        print("  invalid, enter 1-6 or 'x' for secret menu")


def _parse_gui_args(args: list) -> tuple:
    path = None
    passes_override = None
    skip_prompts_flag = False
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
        print(__doc__)
        sys.exit(0 if args else 1)

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
        w, h, is_portrait, short_side, codec = _get_dims(path)
        tier    = _detect_tier(path, w, h)
        options = _calculate_upscale_options(short_side, is_portrait)

        _print_streams_detected(w, h, short_side, is_portrait, options, tier)

        is_high_res = (short_side >= UPSCALE_CEILING)

        should_upscale = prompt_upscale(skip_all_prompts, is_high_res)
        if not should_upscale:
            print(f"\n{Color.YELLOW}Skipping enhancement.{Color.RESET}")
            sys.exit(0)

        level = prompt_level(skip_all_prompts)
        if level == 0:
            print(f"\n{Color.YELLOW}Skipped.{Color.RESET}")
            sys.exit(0)

        # Enhancement-only (high-res source): lock to source, 1 pass, no prompts
        if is_high_res:
            target_res    = short_side
            passes        = 1
            preset        = None
            secret_filters = None
        else:
            target_res = prompt_target_res(options, skip_all_prompts)
            passes     = passes_override if passes_override else prompt_passes(skip_all_prompts)
            if passes > 1:
                preset, secret_filters = prompt_preset(skip_all_prompts)
            else:
                preset        = None
                secret_filters = None

        # Render time estimate / calibration
        duration = get_duration(path)
        cal      = load_calibration()
        cal_key  = str(target_res)
        if cal_key not in cal:
            print(f"\n  {Color.DIM}[first run] calibrating encoder speed...{Color.RESET}")
            try:
                cal_vf = _main_chain(tier, target_res, is_portrait,
                                     target_res > short_side)
                run_calibration(path, cal_vf, target_res)
                cal = load_calibration()
            except Exception:
                pass
        if cal_key in cal and duration > 0:
            est = estimate_time(duration, passes, target_res, cal)
            if est:
                label = f"{passes} pass{'es' if passes > 1 else ''} at {target_res}p"
                print(f"  {Color.DIM}Estimated time: {est}  ({label}){Color.RESET}")

        print(f"\n{Color.CYAN}Processing...{Color.RESET}")
        t0  = time.time()
        out = enhance(path, level=level, preset=preset,
                      user_filters=secret_filters,
                      passes=passes, target_res=target_res,
                      ceiling=0 if is_high_res else None)
        elapsed = time.time() - t0
        try:
            update_calibration(target_res, elapsed, duration)
        except Exception:
            pass
        print(f"\n{Color.GREEN}* Done!{Color.RESET} {out}")

    except Exception as e:
        print(f"\n{Color.RED}error: {e}{Color.RESET}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
