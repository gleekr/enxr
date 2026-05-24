#!/usr/bin/env python3
"""
enxgui.py - Terminal GUI for enx.py with interactive stream selection

Detects source resolution, displays upscale options with best highlighted,
shows ceiling limits, and prompts for upscale preference.

Reads terminal context to detect skip=True flags for skipping prompts entirely.

Usage:
  python3 enxgui.py <####.mp4> [passes N]
  
Environment flags (skip prompts for entire session):
  export SKIP_PROMPTS=1
  python3 enxgui.py <file> [passes]
  
CLI flags:
  --skip       Skip all prompts, use defaults
  --passes N   Number of passes (default 1)
"""

import os, sys, subprocess, json, re

from ffmpeg import enhance, _get_dims, _get_steps, get_ceiling
from config.settings import UPSCALE_CEILING, UPSCALE_STEPS


# ANSI Colors
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
    """
    Read terminal context to detect session flags.
    Looks for patterns like: skip=True, skip_prompts=1, auto=True, etc.
    
    Returns dict of flags:
      skip_prompts: bool
      auto_mode: bool
    """
    flags = {
        'skip_prompts': False,
        'auto_mode': False,
    }
    
    # Check environment variables
    if os.environ.get('SKIP_PROMPTS') == '1' or os.environ.get('SKIP') == 'true':
        flags['skip_prompts'] = True
    
    if os.environ.get('AUTO') == 'true' or os.environ.get('AUTO_MODE') == '1':
        flags['auto_mode'] = True
    
    # Try to read bash history (a-shell may not support this, but try anyway)
    try:
        history_file = os.path.expanduser('~/.bash_history')
        if os.path.exists(history_file):
            with open(history_file, 'r') as f:
                recent = f.readlines()[-20:]  # last 20 lines
                history_str = ' '.join(recent)
                
                if re.search(r'skip\s*=\s*[Tt]rue|skip_prompts\s*=\s*1', history_str):
                    flags['skip_prompts'] = True
                if re.search(r'auto\s*=\s*[Tt]rue|auto_mode\s*=\s*1', history_str):
                    flags['auto_mode'] = True
    except:
        pass
    
    return flags


def _format_resolution(w: int, h: int, is_portrait: bool) -> str:
    """Format resolution as readable string with orientation."""
    orientation = "portrait" if is_portrait else "landscape"
    return f"{w}x{h} ({orientation})"


def _calculate_upscale_options(short_side: int, is_portrait: bool) -> list:
    """
    Calculate all valid upscale targets up to 1440p short side.
    Returns list of dicts: {"target": int, "width": int, "height": int, "is_best": bool}
    """
    ceiling = UPSCALE_CEILING
    options = []
    targets = [t for t in UPSCALE_STEPS if short_side < t <= ceiling]
    
    # If already at ceiling, offer source-lock (enhancement only, no upscale)
    if short_side >= ceiling:
        return [{"target": short_side, "width": None, "height": None, 
                "is_best": True, "label": "Source (enhancement only)"}]
    
    # Build options for each valid target
    for target in targets:
        if is_portrait:
            # Portrait: target is width
            width = target
            height = int(target * (1280 / 720)) if short_side == 720 else int(target * (h / w) if 'h' in locals() and 'w' in locals() else target * 1.777)
        else:
            # Landscape: target is height
            height = target
            width = int(target * 1.777)  # approximate 16:9
        
        options.append({
            "target": target,
            "width": width if not is_portrait else target,
            "height": height if is_portrait else target,
            "is_best": (target == targets[-1]),  # last (highest) is best
            "label": f"{target}p"
        })
    
    return options


def _print_streams_detected(w: int, h: int, short_side: int, is_portrait: bool, 
                            options: list) -> None:
    """Display source and upscale options with best highlighted in green."""
    
    orientation = "portrait" if is_portrait else "landscape"
    source_res = _format_resolution(w, h, is_portrait)
    
    print(f"\n{Color.CYAN}-------------------------------------------{Color.RESET}")
    print(f"{Color.BOLD}Source Resolution:{Color.RESET} {source_res}")
    print(f"{Color.BOLD}Short side:{Color.RESET} {short_side}p")
    print(f"{Color.CYAN}-------------------------------------------{Color.RESET}")
    
    print(f"\n{Color.BOLD}Upscale Options:{Color.RESET}")
    
    for opt in options:
        target = opt['target']
        label = opt['label']
        is_best = opt['is_best']
        
        if is_best:
            # Highlight best option in green
            print(f"  {Color.GREEN}* {label}{Color.RESET}")
        else:
            print(f"    {label}")
    
    # Show ceiling info
    print(f"\n{Color.BOLD}Ceiling:{Color.RESET} 1440p short side")
    if is_portrait:
        print(f"  {Color.DIM}(max 1440x2560 portrait){Color.RESET}")
    else:
        print(f"  {Color.DIM}(max 2560x1440 landscape){Color.RESET}")


def _print_why_skip(short_side: int, ceiling: int = UPSCALE_CEILING) -> None:
    """Explain why upscale wasn't chosen (already high res)."""
    print(f"\n{Color.YELLOW}! Why skip upscale?{Color.RESET}")
    print(f"  Source is {short_side}p (already at ceiling)")
    print(f"  Upscaling would degrade quality")
    print(f"  Recommend: enhancement only (--source flag) for refinement")


def prompt_upscale(skip_prompts: bool = False, is_high_res: bool = False) -> bool:
    """
    Binary prompt: upscale or not?
    
    skip_prompts: if True, return True (auto-upscale) unless already high-res
    is_high_res: if True, recommend enhancement-only
    """
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
    """
    Prompt for enhancement level 1-4.
    skip_prompts: if True, return 2 (default medium level)
    """
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
    """
    Prompt for number of passes.
    skip_prompts: if True, return 1 (default)
    """
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
    """Parse GUI-specific args. Returns (path, passes_override, skip_prompts_flag)"""
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
    
    # Parse args
    path, passes_override, skip_prompts_flag = _parse_gui_args(args)
    
    if not path:
        print(f"{Color.RED}error: no input file specified{Color.RESET}", file=sys.stderr)
        sys.exit(1)
    
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        print(f"{Color.RED}error: file not found: {path}{Color.RESET}", file=sys.stderr)
        sys.exit(1)
    
    # Check terminal context for session flags
    context = _check_terminal_context()
    skip_all_prompts = skip_prompts_flag or context['skip_prompts']
    
    try:
        # Get source dimensions
        w, h, is_portrait, short_side = _get_dims(path)
        
        # Calculate upscale options
        options = _calculate_upscale_options(short_side, is_portrait)
        
        # Display streams detected
        _print_streams_detected(w, h, short_side, is_portrait, options)
        
        # Check if already high-res
        is_high_res = (short_side >= UPSCALE_CEILING)
        
        # Prompt for upscale
        should_upscale = prompt_upscale(skip_all_prompts, is_high_res)
        
        if not should_upscale:
            print(f"\n{Color.YELLOW}Skipping enhancement.{Color.RESET}")
            sys.exit(0)
        
        # Prompt for level
        level = prompt_level(skip_all_prompts)
        
        if level == 4:
            print(f"\n{Color.YELLOW}Level 4: Skipping enhancement.{Color.RESET}")
            sys.exit(0)
        
        # Determine ceiling from source resolution
        ceiling = 0 if is_high_res else get_ceiling(short_side)

        # Show ceiling info before pass selection
        if not skip_all_prompts:
            from config.settings import CEILING_MAX_PASSES
            max_p = CEILING_MAX_PASSES.get(ceiling, 2)
            if ceiling == 0:
                print(f"\n  Ceiling: source lock (enhancement only)")
            else:
                print(f"\n  Ceiling: {ceiling}p")
            print(f"  Max passes: {max_p}")

        # Prompt for passes
        passes = passes_override if passes_override else prompt_passes(skip_all_prompts)

        from ffmpeg import cap_passes
        passes = cap_passes(passes, ceiling)
        
        # Run enhancement
        print(f"\n{Color.CYAN}Processing...{Color.RESET}")
        out = enhance(path, level=level, user_filters=None, passes=passes, ceiling=ceiling)
        print(f"\n{Color.GREEN}* Done!{Color.RESET} {out}")
        
    except Exception as e:
        print(f"\n{Color.RED}error: {e}{Color.RESET}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
