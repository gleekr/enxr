#!/usr/bin/env python3
"""
enxr.py - Master orchestrator for download -> enhance workflow

Combines downloader.py and enxgui.py with interactive menu.
Works standalone or in batch with session flags.

Usage:
  python3 enxr.py                 # Interactive menu
  python3 enxr.py <URL|file>      # Auto-download or load, then enhance

Environment flags (skip prompts for entire session):
  export SKIP_PROMPTS=1
  export SKIP=true

Examples:
  python3 enxr.py https://youtube.com/watch?v=...
  python3 enxr.py ~/Documents/0000.mp4
  SKIP_PROMPTS=1 python3 enxr.py ~/Downloads/video.mp4
"""

import os, sys

import time

from downloader import download, download_batch, DEFAULT_DEST
from ffmpeg import _get_dims, get_ceiling, enhance
from logger import log_error
from config.settings import UPRES_DEST, BATCH_DEST, UPSCALE_CEILING
from calibration import (load_calibration, run_calibration, estimate_time,
                         update_calibration, get_duration)
from ffmpeg import _main_chain
import enxgui


class Color:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'


def _input(prompt: str) -> str:
    """input() wrapper -- type 'exit', 'quit', or 'q' at any prompt to quit."""
    val = input(prompt).strip()
    if val.lower() in ('exit', 'quit', 'q'):
        print(f"\n{Color.GREEN}Bye!{Color.RESET}\n")
        sys.exit(0)
    return val


def _check_skip_context() -> bool:
    """Check if session has SKIP_PROMPTS flag."""
    return os.environ.get('SKIP_PROMPTS') == '1' or \
           os.environ.get('SKIP') == 'true'


def print_header():
    """Display welcome header."""
    print(f"\n{Color.CYAN}{'='*60}{Color.RESET}")
    print(f"{Color.BOLD}  Video Download -> Enhance Workflow{Color.RESET}")
    print(f"{Color.CYAN}{'='*60}{Color.RESET}\n")


def print_menu():
    """Display main menu."""
    print(f"{Color.BOLD}Choose action:{Color.RESET}")
    print("  1 - Download from URL + Enhance")
    print("  2 - Load local file + Enhance")
    print("  3 - Download only (no enhancement)")
    print("  4 - Enhance only (existing file)")
    print("  5 - Batch process folder")
    print("  6 - Download channel Shorts + Enhance")
    print("  7 - Exit")
    print()


def prompt_choice() -> str:
    """Get menu choice."""
    while True:
        choice = _input(f"{Color.BOLD}Enter (1-7):{Color.RESET} ")
        if choice in ('1', '2', '3', '4', '5', '6', '7'):
            return choice
        print(f"  {Color.RED}invalid, enter 1-7{Color.RESET}")


def prompt_url() -> str:
    """Get URL from user."""
    url = _input(f"{Color.BOLD}Paste URL:{Color.RESET} ")
    if not url.startswith(('http://', 'https://', 'ftp://')):
        print(f"  {Color.RED}invalid URL{Color.RESET}")
        return prompt_url()
    return url


def prompt_file(prompt_text: str = "Enter file path") -> str:
    """Get file path from user."""
    path = _input(f"{Color.BOLD}{prompt_text}:{Color.RESET} ")
    path = os.path.abspath(os.path.expanduser(path))

    if not os.path.isfile(path):
        print(f"  {Color.RED}file not found: {path}{Color.RESET}")
        return prompt_file(prompt_text)

    return path


def prompt_passes(skip: bool = False) -> int:
    """Get number of passes."""
    if skip:
        return 1

    print(f"\n{Color.BOLD}Enhancement passes:{Color.RESET}")
    print("  1 = single upscale")
    print("  2+ = refinement passes (slower, better quality)")

    while True:
        choice = _input(f"{Color.BOLD}Passes (1-4):{Color.RESET} ")
        if choice.isdigit() and 1 <= int(choice) <= 4:
            return int(choice)
        print(f"  {Color.RED}invalid, enter 1-4{Color.RESET}")


def action_download_enhance(skip_prompts: bool = False):
    """Action 1: Download + Enhance"""
    print(f"\n{Color.BOLD}[ACTION 1] Download + Enhance{Color.RESET}")

    url = prompt_url()

    print(f"\n{Color.YELLOW}Downloading...{Color.RESET}")
    try:
        video_file = download(url, DEFAULT_DEST)
        print(f"{Color.GREEN}* Downloaded:{Color.RESET} {video_file}")
    except Exception as e:
        log_error("download", e, extra=f"url={url}")
        print(f"{Color.RED}Download failed: {e}{Color.RESET}")
        return

    action_enhance_file(video_file, skip_prompts)


def action_load_enhance(skip_prompts: bool = False):
    """Action 2: Load local file + Enhance"""
    print(f"\n{Color.BOLD}[ACTION 2] Load + Enhance{Color.RESET}")

    file_path = prompt_file("Enter local video path")
    action_enhance_file(file_path, skip_prompts)


def action_download_only():
    """Action 3: Download only"""
    print(f"\n{Color.BOLD}[ACTION 3] Download Only{Color.RESET}")

    url = prompt_url()

    print(f"\n{Color.YELLOW}Downloading...{Color.RESET}")
    try:
        video_file = download(url, DEFAULT_DEST)
        print(f"{Color.GREEN}* Downloaded:{Color.RESET} {video_file}")
    except Exception as e:
        print(f"{Color.RED}Download failed: {e}{Color.RESET}")


def action_enhance_only(skip_prompts: bool = False):
    """Action 4: Enhance existing file"""
    print(f"\n{Color.BOLD}[ACTION 4] Enhance Only{Color.RESET}")

    file_path = prompt_file("Enter video path")
    action_enhance_file(file_path, skip_prompts)


def action_enhance_file(file_path: str, skip_prompts: bool = False):
    """Run enhancement on file via enxgui."""
    print(f"\n{Color.YELLOW}Analyzing...{Color.RESET}")

    try:
        w, h, is_portrait, short_side, codec = _get_dims(file_path)
        orientation = "portrait" if is_portrait else "landscape"

        print(f"{Color.GREEN}* Resolution:{Color.RESET} {w}x{h} ({orientation})")

        options = enxgui._calculate_upscale_options(short_side, is_portrait)
        enxgui._print_streams_detected(w, h, short_side, is_portrait, options)

        is_high_res = (short_side >= UPSCALE_CEILING)

        should_upscale = enxgui.prompt_upscale(skip_prompts, is_high_res)

        if not should_upscale:
            print(f"\n{Color.YELLOW}Skipped.{Color.RESET}")
            return

        level = enxgui.prompt_level(skip_prompts)
        if level == 0:
            print(f"\n{Color.YELLOW}Skipped.{Color.RESET}")
            return

        # Enhancement-only (high-res source): lock to source, 1 pass, no prompts
        if is_high_res:
            target_res     = short_side
            passes         = 1
            preset         = None
            secret_filters = None
        else:
            target_res = enxgui.prompt_target_res(options, skip_prompts)
            passes     = prompt_passes(skip_prompts)
            if passes > 1:
                preset, secret_filters = enxgui.prompt_preset(skip_prompts)
            else:
                preset         = None
                secret_filters = None

        # Render time estimate / calibration
        duration = get_duration(file_path)
        tier_for_cal = enxgui._detect_tier(file_path, w, h)
        cal     = load_calibration()
        cal_key = str(target_res)
        if cal_key not in cal:
            print(f"\n  {Color.DIM}[first run] calibrating encoder speed...{Color.RESET}")
            try:
                cal_vf = _main_chain(tier_for_cal, target_res, is_portrait,
                                     target_res > short_side)
                run_calibration(file_path, cal_vf, target_res)
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
        out = enhance(file_path, level=level, preset=preset,
                      user_filters=secret_filters,
                      passes=passes, target_res=target_res,
                      ceiling=0 if is_high_res else None, out_dir=UPRES_DEST)
        elapsed = time.time() - t0
        try:
            update_calibration(target_res, elapsed, duration)
        except Exception:
            pass

        print(f"\n{Color.GREEN}* Complete!{Color.RESET} {out}")

    except Exception as e:
        log_error("enhance_file", e, extra=f"file={file_path}")
        print(f"{Color.RED}Error: {e}{Color.RESET}")


def action_batch_folder(skip_prompts: bool = False):
    """Action 5: Batch process folder"""
    print(f"\n{Color.BOLD}[ACTION 5] Batch Process Folder{Color.RESET}")

    folder = prompt_file("Enter folder path")
    if not os.path.isdir(folder):
        print(f"{Color.RED}Not a folder{Color.RESET}")
        return

    mp4_files = [f for f in os.listdir(folder) if f.lower().endswith('.mp4')]

    if not mp4_files:
        print(f"{Color.YELLOW}No MP4 files found{Color.RESET}")
        return

    print(f"\n{Color.GREEN}Found {len(mp4_files)} files{Color.RESET}")
    for f in mp4_files:
        print(f"  {f}")

    confirm = _input(f"\n{Color.BOLD}Enhance all? (yes/no):{Color.RESET} ").lower()
    if confirm not in ('y', 'yes'):
        return

    passes = prompt_passes(skip_prompts)

    success = 0
    failed = 0

    for filename in mp4_files:
        file_path = os.path.join(folder, filename)
        print(f"\n{Color.CYAN}Processing: {filename}{Color.RESET}")

        try:
            from ffmpeg import enhance
            _, _, _, short_side, _ = _get_dims(file_path)
            ceiling = get_ceiling(short_side)

            out = enhance(file_path, level=2, user_filters=None, passes=passes, ceiling=ceiling)
            print(f"  {Color.GREEN}* {os.path.basename(out)}{Color.RESET}")
            success += 1
        except Exception as e:
            log_error("batch", e, extra=f"file={filename}")
            print(f"  {Color.RED}x {e}{Color.RESET}")
            failed += 1

    print(f"\n{Color.CYAN}{'='*60}{Color.RESET}")
    print(f"{Color.GREEN}Completed: {success}/{len(mp4_files)}{Color.RESET}")
    if failed > 0:
        print(f"{Color.RED}Failed: {failed}{Color.RESET}")


def prompt_batch_selection() -> str:
    """Returns a yt-dlp playlist_items string or None for all."""
    print(f"\n{Color.CYAN}-------------------------------------------{Color.RESET}")
    print(f"{Color.BOLD}Select videos:{Color.RESET}")
    print("  1 - All")
    print("  2 - First N")
    print(f"  3 - Specific  {Color.DIM}(e.g. 1,3,6-10,22){Color.RESET}")
    print(f"{Color.CYAN}-------------------------------------------{Color.RESET}")

    while True:
        choice = _input(f"{Color.BOLD}Choice (1-3):{Color.RESET} ")
        if choice == "1":
            return None
        elif choice == "2":
            while True:
                n = _input(f"{Color.BOLD}How many:{Color.RESET} ")
                if n.isdigit() and int(n) > 0:
                    return f"1-{n}"
                print(f"  {Color.RED}enter a number{Color.RESET}")
        elif choice == "3":
            val = _input(f"{Color.BOLD}Indices:{Color.RESET} ")
            if val:
                return val
            print(f"  {Color.RED}enter at least one index{Color.RESET}")
        else:
            print(f"  {Color.RED}enter 1, 2, or 3{Color.RESET}")


def action_channel_shorts(skip_prompts: bool = False):
    """Action 6: Download channel Shorts tab + Enhance"""
    print(f"\n{Color.BOLD}[ACTION 6] Channel Shorts Batch{Color.RESET}")
    print(f"  {Color.DIM}e.g. https://www.youtube.com/@handle/shorts{Color.RESET}\n")

    url             = prompt_url()
    playlist_items  = None if skip_prompts else prompt_batch_selection()

    print(f"\n{Color.YELLOW}Downloading...{Color.RESET}")
    try:
        files, channel_dir = download_batch(url, BATCH_DEST, playlist_items)
    except Exception as e:
        log_error("channel_shorts_download", e, extra=f"url={url}")
        print(f"{Color.RED}Download failed: {e}{Color.RESET}")
        return

    if not files:
        print(f"{Color.YELLOW}No files downloaded.{Color.RESET}")
        return

    channel_name = os.path.basename(channel_dir)
    upres_dir    = os.path.join(channel_dir, "upres")

    print(f"\n{Color.CYAN}-------------------------------------------{Color.RESET}")
    print(f"{Color.BOLD}Channel:{Color.RESET}  {channel_name}")
    print(f"{Color.BOLD}Files:{Color.RESET}    {len(files)} downloaded")
    print(f"{Color.BOLD}noenx/{Color.RESET}    originals")
    print(f"{Color.BOLD}upres/{Color.RESET}    enhanced output")
    print(f"{Color.CYAN}-------------------------------------------{Color.RESET}")

    confirm = _input(f"\n{Color.BOLD}Enhance all? (yes/no):{Color.RESET} ").lower()
    if confirm not in ('y', 'yes'):
        print(f"\n{Color.YELLOW}Skipped enhancement.{Color.RESET}")
        return

    passes  = prompt_passes(skip_prompts)
    success = 0
    failed  = 0

    print()
    for file_path in files:
        filename = os.path.basename(file_path)
        print(f"{Color.CYAN}Processing: {filename}{Color.RESET}")
        try:
            from ffmpeg import enhance
            _, _, _, short_side, _ = _get_dims(file_path)
            ceiling = get_ceiling(short_side)
            out = enhance(file_path, level=2, user_filters=None, passes=passes,
                          ceiling=ceiling, out_dir=upres_dir)
            print(f"  {Color.GREEN}* {os.path.basename(out)}{Color.RESET}")
            success += 1
        except Exception as e:
            log_error("channel_shorts_enhance", e, extra=f"file={filename}")
            print(f"  {Color.RED}x {e}{Color.RESET}")
            failed += 1

    print(f"\n{Color.CYAN}-------------------------------------------{Color.RESET}")
    print(f"{Color.GREEN}Done: {success}/{len(files)}{Color.RESET}", end="")
    if failed:
        print(f"  {Color.RED}Failed: {failed}{Color.RESET}", end="")
    print()


def main():
    """Main loop."""
    args = sys.argv[1:]
    skip_prompts = _check_skip_context()

    print_header()

    if args:
        file_or_url = args[0]

        if file_or_url.startswith(('http://', 'https://', 'ftp://')):
            print(f"{Color.BOLD}Processing URL...{Color.RESET}")
            action_download_enhance(skip_prompts)
        else:
            file_path = os.path.abspath(os.path.expanduser(file_or_url))
            if os.path.isfile(file_path):
                print(f"{Color.BOLD}Processing file...{Color.RESET}")
                action_enhance_file(file_path, skip_prompts)
            else:
                print(f"{Color.RED}File not found: {file_or_url}{Color.RESET}")
                sys.exit(1)
        return

    while True:
        print_menu()
        choice = prompt_choice()

        if choice == '1':
            action_download_enhance(skip_prompts)
        elif choice == '2':
            action_load_enhance(skip_prompts)
        elif choice == '3':
            action_download_only()
        elif choice == '4':
            action_enhance_only(skip_prompts)
        elif choice == '5':
            action_batch_folder(skip_prompts)
        elif choice == '6':
            action_channel_shorts(skip_prompts)
        elif choice == '7':
            print(f"\n{Color.GREEN}Bye!{Color.RESET}\n")
            sys.exit(0)

        _input(f"\n{Color.DIM}Press Enter to continue (or 'exit' to quit)...{Color.RESET}")


if __name__ == "__main__":
    main()
