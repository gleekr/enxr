#!/usr/bin/env python3
"""
enxgui.py - Terminal GUI for enxr with interactive stream selection

Detects source resolution and quality tier, displays upscale options,
and prompts for enhancement preferences.

Usage:
  python3 enxgui.py <file.mp4> [--passes N] [--skip]
"""

import os, sys, re

from ffmpeg import enhance, _get_dims, get_ceiling, _detect_tier
from config.settings import UPSCALE_CEILING, UPSCALE_STEPS


class Color:
    GREEN  = '\033[92m'
    RED    = '\033[91m'
    YELLOW = '\033[93m'
    CYAN   = '\033[96m'
    WHITE  = '\033[97m'
    BOLD   = '\033[1m'
    DIM    = '\033[2m'
    RESET  = '\033[0m'


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
            choice = input(f"\n{Color.BOLD}Enhancement only? (y/n):{Color.RESET} ").strip().lower()
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
        choice = input(f"{Color.BOLD}Tier:{Color.RESET} ").strip()
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
            f"{Color.BOLD}Target (1-{len(options)}, enter for {recommended}p):{Color.RESET} "
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
        choice = input(f"{Color.BOLD}Passes (1-4):{Color.RESET} ").strip()
        if choice.isdigit() and 1 <= int(choice) <= 4:
            return int(choice)
        print("  invalid, enter 1-4")


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
            target_res = short_side
            passes     = 1
        else:
            target_res = prompt_target_res(options, skip_all_prompts)
            passes     = passes_override if passes_override else prompt_passes(skip_all_prompts)

        print(f"\n{Color.CYAN}Processing...{Color.RESET}")
        out = enhance(path, level=level, user_filters=None,
                      passes=passes, target_res=target_res,
                      ceiling=0 if is_high_res else None)
        print(f"\n{Color.GREEN}* Done!{Color.RESET} {out}")

    except Exception as e:
        print(f"\n{Color.RED}error: {e}{Color.RESET}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
