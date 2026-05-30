# ENXR Changelog & Restore Guide

**Date: 2026-05-30**  
**Project**: Video Fixer/Beautifier Swiss Army Knife VFX Suite  
**Vision**: Open source, free, cross-platform video restoration + upscaling with local processing + optional remote SSH

---

## Major Changes Log

### 1. OS-Specific Codec Strategy (ffmpeg.py)

**What Changed:**
- Refactored encoder fallback chain from hardcoded h264/hevc/libx264 to **dynamic OS-specific codec strategies**
- Added `platform` module import for OS detection
- Created `_get_encoder_chain()` function that returns hardware-first encoder chains per OS
- Created `_encoder_args()` function for codec-specific FFmpeg flags (preset, crf, cpu-used)
- Refactored `_encode()` to loop through dynamic encoder chain instead of hardcoded sequence

**Why:**
- Enable cross-platform compatibility (Windows NVIDIA/Intel hardware, macOS VideoToolbox, Linux software, Android MediaCodec)
- Hardware encoding prioritized for speed, software fallbacks for compatibility
- Different codecs need different optimization flags

**Codec Strategies:**
```python
"Darwin": ["h264_videotoolbox", "hevc_videotoolbox", "libx264"]
"Windows": ["h264_nvenc", "h264_qsv", "libx264"]  # NVIDIA/Intel hardware first
"Linux": ["libx264", "libx265", "libvpx", "libaom"]  # Software + VP9/AV1 options
"Android": ["mediacodec_h264", "libx264"]
```

**Files Modified:** `ffmpeg.py`

**Key Code Additions:**
```python
import platform

def _get_encoder_chain() -> list:
    """Return OS-specific encoder chain, hardware-first."""
    os_name = platform.system()
    strategies = {
        "Darwin": ["h264_videotoolbox", "hevc_videotoolbox", "libx264"],
        "Windows": ["h264_nvenc", "h264_qsv", "libx264"],
        "Linux": ["libx264", "libx265", "libvpx", "libaom"],
        "Android": ["mediacodec_h264", "libx264"],
    }
    chain = strategies.get(os_name, ["libx264"])
    print(f"[ffmpeg] {os_name} encoder chain: {' > '.join(chain)}")
    return chain

def _encoder_args(codec: str) -> list:
    """Return codec-specific FFmpeg args."""
    if codec in ("libx264", "libx265"):
        return ["-preset", "fast", "-crf", "23"]
    if codec == "libvpx":
        return ["-deadline", "good", "-cpu-used", "4", "-crf", "30"]
    if codec == "libaom":
        return ["-cpu-used", "4", "-crf", "30"]
    return []
```

Updated `_encode()` to use `_get_encoder_chain()` and loop through codecs with appropriate args.

---

### 2. Interactive Channel Shorts Downloader (downloader.py)

**What Changed:**
- Added interactive channel URL detection (`/shorts`, `/videos`)
- Implemented range parsing system (`3,2,7,23-30,25-59`)
- Added media type filtering (shorts ≤60s vs videos >60s)
- Created `download_channel_interactive()` function with CLI menu
- Added failure tracking and reporting by index
- Integrated batch enhance option with range selection

**Why:**
- Users can paste @channel/shorts URL and browse/select without manual URL construction
- Flexible selection (first X, custom ranges, all)
- Seamless download → enhance pipeline
- No YouTube app interference (uses existing player_client strategy)

**New Functions:**
```python
def _parse_selection(selection_str: str, total: int) -> list[int]:
    """Parse '3,2,7,23-30,25-59' into sorted unique indices (0-based)."""
    # Handles ranges: '23-30' = items 23-30 inclusive
    # Handles lists: '3,2,7' = pick indices 3, 2, 7
    # Returns sorted list of 0-based indices

def _filter_entries_by_type(entries: list, filter_type: str) -> list:
    """Filter entries by 'shorts' (≤60s), 'videos' (>60s), or 'all'."""

def download_channel_interactive(url: str, dest: str = BATCH_OG) -> tuple[list[str], list[int]]:
    """Interactive channel browser. Returns (downloaded_paths, failed_indices)."""
```

**Updated main() Flow:**
1. Detect channel URLs (`/shorts`, `/videos`)
2. Fetch playlist metadata
3. Show menu:
   - Option 1: First X (default 60)
   - Option 2: Custom ranges
   - Option 3: All shorts
   - Option 4: All videos
   - Option 5: All (mixed)
4. Filter by type (shorts/videos/all)
5. Download batch with failure tracking
6. Post-download menu:
   - Y/N: Enhance batch?
   - If Y: All / Specify range / Cancel
   - Enhance selected with default settings (restore=2, enhance=3)

**Files Modified:** `downloader.py`

**Example Flow:**
```
$ python3 downloader.py @channelname/shorts

[channel] @channelname/shorts

[channel] fetching metadata...
[channel] 87 total videos found

Filter by:
  1. First X (shorts only)
  2. Custom ranges (e.g., 3,2,7,23-30)
  3. All shorts
  4. All videos
  5. All (shorts + videos)

Select [1-5]: 2
Indices (e.g., 3,2,7,23-30): 3,2,7,23-30

[download] 30 video(s) selected

  [1/30] vidabc123
  [2/30] videfg456
  ...
  [28/30] vidxyz789

[!] Failed: 7, 15

[enhance] Enhance batch? (Y/N): Y

[enhance] 28 video(s) downloaded
  1. All
  2. Specify range (e.g., 4-9, 3, 21)
  3. Cancel

Select [1-3]: 2
Indices (e.g., 4-9, 3, 21): 4-9, 3

[enhancing] 8 video(s)...
  [1/8] exvid004.mp4
  [2/8] exvid005.mp4
  ...
```

---

## Architecture Summary

### Pipeline Stages
1. **Download** → Channel URL → Interactive selection → Batch download
2. **Filter** → By media type (shorts/videos) and custom ranges
3. **Enhance** → Optional post-download batch processing (restore + sharpen + upscale)

### Quality Detection
- Bitrate-normalized quality tier detection (1-5, where 1 = excellent)
- Automatically suggests restore/enhance levels based on source quality

### Encoding Pipeline (Single-Pass)
```
format (yuv420p) 
  → restore (deblock/deband) 
  → sharpen (unsharp, luma-only) 
  → scale (zscale, lanczos, error diffusion) 
  → format (yuv420p)
```

### Error Handling
- Per-codec fallback chain
- Failed downloads tracked by index, not skipped silently
- Graceful degradation (iOS SIGINT recovery, archive deduplication)

---

## How to Recreate if Lost

### Step 1: ffmpeg.py - OS-Specific Codecs
1. Open `ffmpeg.py`
2. Add `import platform` at top
3. Before `_file_valid()`, add `_get_encoder_chain()` and `_encoder_args()` functions (see above)
4. Replace entire `_encode()` function to:
   - Call `_get_encoder_chain()`
   - Loop through encoders with `_encoder_args(codec)`
   - Report which encoder succeeded if not first in chain
   - Track last error for final RuntimeError

### Step 2: downloader.py - Interactive Channel Selector
1. Open `downloader.py`
2. Add three new functions before `# ── CLI`:
   - `_parse_selection()` — parse range strings
   - `_filter_entries_by_type()` — filter by duration
   - `download_channel_interactive()` — main interactive flow
3. Replace `main()` to:
   - Detect `/shorts` or `/videos` in URL
   - Call `download_channel_interactive()` for channels
   - Keep existing single-download logic
   - Add post-download enhance menu with range selection

### Step 3: Test Points
- **ffmpeg.py**: Run on each OS, verify correct encoder chain prints
- **downloader.py**: Paste test channel URL, verify menu appears and selection works
- **Full pipeline**: Download → enhance with ranges

---

## Config Dependencies

**ffmpeg.py depends on:**
- `config.settings.SOURCE_CEILING` — upscale limit table
- `filters.presets.build_chain()` — filter chain builder

**downloader.py depends on:**
- `config.settings.DEFAULT_DEST, BATCH_OG, BATCH_WORKERS, BATCH_FRAGMENT_THREADS`
- `config.settings.YT_PLAYER_CLIENT, YT_PLAYER_CLIENT_FALLBACK` — player client strategy

Verify these exist in `config/settings.py` before recreating.

---

## Future Considerations

- **Cross-platform testing**: Windows (NVIDIA/Intel probing), Linux, Android (via Termux)
- **UI Layer**: Currently CLI-only; could wrap in Qt/web UI later
- **Codec Presets**: Currently hardcoded (preset=fast, crf=23); could expose as config
- **Remote SSH**: Optional step after enhance for heavy processing on remote box

---

## Notes
- All changes maintain backward compatibility with existing enhance() API
- No new dependencies added
- Player_client strategy prevents YouTube app opening (iOS/TV clients prioritized)
- Archive deduplication prevents re-downloading same video across runs
