#!/usr/bin/env python3
"""
enxr.py - Video restore & enhance pipeline

Usage:
  python3 enxr.py                 # Interactive menu
  python3 enxr.py <URL|file>      # Fetch or load, then enhance

Environment flags (skip prompts for entire session):
  export SKIP_PROMPTS=1
  export SKIP=true
"""

import os, sys, shutil

import time

from downloader import download, _is_url, DEFAULT_DEST
from ffmpeg import _check_ffmpeg_tools, _get_dims, get_ceiling, enhance
from logger import log_error
from config import UPRES_DEST, build_chain
from calibration import (load_calibration, run_calibration, estimate_time,
                         update_calibration, get_duration)
import enxgui
from enxgui import GoBack, Color, _rl_safe


def _input(prompt: str) -> str:
    """input() wrapper.
    'exit'/'quit'/'q' quits; 'back'/'go back'/'b' returns to the menu.
    """
    val = input(_rl_safe(prompt)).strip()
    if val.lower() in ('exit', 'quit', 'q'):
        print(f"\n{Color.GREEN}Bye!{Color.RESET}\n")
        sys.exit(0)
    if val.lower() in ('back', 'go back', 'b'):
        raise GoBack()
    return val


def _check_skip_context() -> bool:
    """Check if session has SKIP_PROMPTS flag."""
    return os.environ.get('SKIP_PROMPTS') == '1' or \
           os.environ.get('SKIP') == 'true'


def _check_deps() -> bool:
    """Verify ffmpeg + ffprobe are on PATH. Returns True if all present."""
    if not _check_ffmpeg_tools():
        print(f"{Color.RED}Missing required tool(s): ffmpeg, ffprobe{Color.RESET}")
        print(f"  {Color.DIM}Install FFmpeg and ensure it's on PATH "
              f"(a-shell: 'pkg install ffmpeg').{Color.RESET}")
        return False
    return True


def _check_yt_dlp() -> bool:
    """Verify yt-dlp is on PATH. Print a clear message if not."""
    if shutil.which("yt-dlp") is None:
        print(f"{Color.RED}Missing required tool: yt-dlp{Color.RESET}")
        print(f"  {Color.DIM}Install yt-dlp and ensure it's on PATH.{Color.RESET}")
        return False
    return True


def print_header():
    print(f"\n{Color.CYAN}{'='*60}{Color.RESET}")
    print(f"{Color.BOLD}  Video Restore & Enhance{Color.RESET}")
    print(f"{Color.CYAN}{'='*60}{Color.RESET}\n")


def print_menu():
    print(f"{Color.BOLD}Choose action:{Color.RESET}")
    print("  1 - Load / fetch + Enhance  (URL or local file)")
    print("  2 - Enhance only (existing file)")
    print("  3 - Batch process folder")
    print("  4 - Exit")
    print()


def prompt_choice() -> str:
    while True:
        choice = _input(f"{Color.BOLD}Enter (1-4):{Color.RESET} ")
        if choice in ('1', '2', '3', '4'):
            return choice
        print(f"  {Color.RED}invalid, enter 1-4{Color.RESET}")


def prompt_file(prompt_text: str = "Enter file path") -> str:
    """Get file path from user."""
    while True:
        path = _input(f"{Color.BOLD}{prompt_text}:{Color.RESET} ")
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isfile(path):
            return path
        print(f"  {Color.RED}file not found: {path}{Color.RESET}")


def prompt_folder(prompt_text: str = "Enter folder path") -> str:
    """Get directory path from user."""
    while True:
        path = _input(f"{Color.BOLD}{prompt_text}:{Color.RESET} ")
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isdir(path):
            return path
        print(f"  {Color.RED}folder not found: {path}{Color.RESET}")



def action_fetch_enhance(skip_prompts: bool = False):
    """Action 1: URL or local file -> Enhance"""
    print(f"\n{Color.BOLD}[ACTION 1] Load / Fetch + Enhance{Color.RESET}")

    source = _input(f"{Color.BOLD}Paste URL or file path:{Color.RESET} ")

    if _is_url(source):
        if not _check_yt_dlp():
            return
        dl_format = enxgui.prompt_download_format(skip_prompts)
        print(f"\n{Color.YELLOW}Downloading ({dl_format})...{Color.RESET}")
        try:
            video_file = download(source, DEFAULT_DEST, fmt=dl_format)
        except Exception as e:
            log_error("download", e, extra=f"url={source}")
            print(f"{Color.RED}Download failed: {e}{Color.RESET}")
            return

        if not video_file:
            print(f"{Color.RED}Download failed.{Color.RESET}")
            return
        print(f"{Color.GREEN}* Downloaded:{Color.RESET} {video_file}")
    else:
        video_file = os.path.abspath(os.path.expanduser(source))
        if not os.path.isfile(video_file):
            print(f"  {Color.RED}file not found: {video_file}{Color.RESET}")
            return

    action_enhance_file(video_file, skip_prompts)


def action_enhance_only(skip_prompts: bool = False):
    """Action 4: Enhance existing file"""
    print(f"\n{Color.BOLD}[ACTION 4] Enhance Only{Color.RESET}")

    file_path = prompt_file("Enter video path")
    action_enhance_file(file_path, skip_prompts)


def action_enhance_file(file_path: str, skip_prompts: bool = False):
    """Run enhancement on file via enxgui.

    Prompts run as a step machine: typing 'back' at any prompt returns to the
    previous prompt; 'back' at the first prompt unwinds to the main menu.
    """
    print(f"\n{Color.YELLOW}Analyzing...{Color.RESET}")

    try:
        w, h, is_portrait, short_side, codec = _get_dims(file_path)
    except Exception as e:
        log_error("enhance_file", e, extra=f"file={file_path}")
        print(f"{Color.RED}Error: {e}{Color.RESET}")
        return

    orientation = "portrait" if is_portrait else "landscape"
    print(f"{Color.GREEN}* Resolution:{Color.RESET} {w}x{h} ({orientation})")

    options     = enxgui._calculate_upscale_options(short_side, is_portrait)
    tier        = enxgui._detect_tier(file_path, w, h)
    enxgui._print_streams_detected(w, h, short_side, is_portrait, options, tier)

    # ── 3-prompt step machine: resolution -> restore -> enhance ───────────────
    # 'back' steps to the previous prompt; 'back' at the first unwinds to menu.
    ans   = {}
    steps = ['resolution', 'denoise', 'enhance']
    i = 0
    while i < len(steps):
        step = steps[i]
        try:
            if step == 'resolution':
                ans['target_res'] = enxgui.prompt_resolution(options, short_side, skip_prompts)
            elif step == 'denoise':
                tier_to_preset = {1: "fast", 2: "med", 3: "med", 4: "slow", 5: "slow"}
                ans['denoise'] = enxgui.prompt_denoise(skip_prompts, suggested=tier_to_preset.get(tier, "med"))
            elif step == 'enhance':
                ans['enhance'] = enxgui.prompt_enhance(skip_prompts)
        except GoBack:
            if i == 0:
                print(f"\n{Color.DIM}Back to menu.{Color.RESET}")
                return
            i -= 1
            continue
        i += 1

    target_res      = ans['target_res']
    denoise_preset  = ans['denoise']
    enhance_level   = ans['enhance']

    try:
        # Render time estimate / calibration
        duration = get_duration(file_path)
        cal     = load_calibration()
        cal_key = str(target_res)
        if cal_key not in cal:
            print(f"\n  {Color.DIM}[first run] calibrating encoder speed...{Color.RESET}")
            try:
                cal_vf = build_chain(denoise_preset, enhance_level, target_res,
                                     is_portrait, target_res > short_side)
                run_calibration(file_path, cal_vf, target_res)
                cal = load_calibration()
            except Exception:
                pass
        if cal_key in cal and duration > 0:
            est = estimate_time(duration, 1, target_res, cal)
            if est:
                print(f"  {Color.DIM}Estimated time: {est}  (at {target_res}p){Color.RESET}")

        print(f"\n{Color.CYAN}Processing...{Color.RESET}")
        t0  = time.time()
        out = enhance(file_path, denoise_preset=denoise_preset,
                      enhance_level=enhance_level, target_res=target_res,
                      out_dir=UPRES_DEST)
        elapsed = time.time() - t0
        try:
            update_calibration(target_res, elapsed, duration)
        except Exception:
            pass
        mins, secs = divmod(int(elapsed), 60)
        t_str = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
        print(f"\n{Color.GREEN}* Complete!{Color.RESET} {out}  {Color.DIM}({t_str}){Color.RESET}")

    except Exception as e:
        log_error("enhance_file", e, extra=f"file={file_path}")
        print(f"{Color.RED}Error: {e}{Color.RESET}")


def action_batch_folder(skip_prompts: bool = False):
    """Action 5: Batch process folder"""
    print(f"\n{Color.BOLD}[ACTION 5] Batch Process Folder{Color.RESET}")

    folder = prompt_folder("Enter folder path")

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

    denoise_preset = enxgui.prompt_denoise(skip_prompts)
    enhance_level = enxgui.prompt_enhance(skip_prompts)

    success = 0
    failed = 0

    for filename in mp4_files:
        file_path = os.path.join(folder, filename)
        print(f"\n{Color.CYAN}Processing: {filename}{Color.RESET}")

        try:
            _, _, _, short_side, _ = _get_dims(file_path)
            ceiling = get_ceiling(short_side)

            out = enhance(file_path, denoise_preset=denoise_preset,
                          enhance_level=enhance_level, ceiling=ceiling,
                          skip_existing=True)
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


def main():
    """Main loop."""
    args = sys.argv[1:]
    skip_prompts = _check_skip_context()

    print_header()

    if not _check_deps():
        sys.exit(1)

    if args:
        file_or_url = args[0]

        if file_or_url.startswith(('http://', 'https://', 'ftp://')):
            print(f"{Color.BOLD}Processing URL...{Color.RESET}")
            if not _check_yt_dlp():
                sys.exit(1)
            print(f"\n{Color.YELLOW}Downloading...{Color.RESET}")
            try:
                video_file = download(file_or_url, DEFAULT_DEST)
                print(f"{Color.GREEN}* Downloaded:{Color.RESET} {video_file}")
            except Exception as e:
                log_error("download", e, extra=f"url={file_or_url}")
                print(f"{Color.RED}Download failed: {e}{Color.RESET}")
                return
            action_enhance_file(video_file, skip_prompts)
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
        try:
            choice = prompt_choice()

            if choice == '1':
                action_fetch_enhance(skip_prompts)
            elif choice == '2':
                action_enhance_only(skip_prompts)
            elif choice == '3':
                action_batch_folder(skip_prompts)
            elif choice == '4':
                print(f"\n{Color.GREEN}Bye!{Color.RESET}\n")
                sys.exit(0)

            _input(f"\n{Color.DIM}Press Enter to continue ('back' for menu, 'exit' to quit)...{Color.RESET}")
        except GoBack:
            continue


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Color.YELLOW}Interrupted.{Color.RESET}")
        # Sweep stray tmp_*.mp4 left mid-encode. enhance() writes tmp files in
        # the input file's dir, which for batches is a per-channel subfolder --
        # so walk the roots recursively rather than globbing the top level.
        from logger import cleanup_tmp
        for root in (DEFAULT_DEST, UPRES_DEST):
            if not os.path.isdir(root):
                continue
            for dirpath, _, _ in os.walk(root):
                cleanup_tmp(dirpath)
        sys.exit(130)
