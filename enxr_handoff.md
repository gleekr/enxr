# enxr — Handoff Document
# For: Claude Code (autonomous loop, code-only changes)
# Updated: 2026-05-25 (full rewrite — tasks 1-4 complete)

---

## RULES FOR CLAUDE CODE

- Touch `.py` files ONLY. No shell scripts, no config files, no docs.
- Do NOT modify `downloader.py` or `logger.py` under any circumstances.
- Do NOT change the `_encode()` function in `ffmpeg.py` (encoder logic is finalized).
- Commit after each working, verified change with a clear message.
- If unsure about intent on anything, re-read this document before guessing.
- Test command after each change: `echo "7" | python enxr.py` must exit cleanly.

---

## Project Overview

enxr is a Python CLI video download + enhancement pipeline.
- Primary target: iOS (a-Shell app)
- Secondary: Windows 10 (development/testing)
- Downloads via yt-dlp, enhances via FFmpeg
- Encoder: h264_videotoolbox (Apple HW) → hevc_videotoolbox fallback → RuntimeError

Run with: `python enxr.py`

---

## File Structure

```
enxr/
├── enxr.py              # interactive menu orchestrator
├── ffmpeg.py            # encode/upscale engine + _encode() + enhance()
├── enxgui.py            # terminal UI / all user prompts
├── downloader.py        # yt-dlp wrapper -- DO NOT TOUCH
├── logger.py            # log_error(), cleanup_tmp() -- DO NOT TOUCH
├── calibration.py       # render time estimator + encoder speed calibration
├── filters/
│   └── presets.py       # QualityTier enum + CLEANUP/MAIN dicts + EnhancePreset
├── config/
│   └── settings.py      # all constants
└── log/                 # runtime only, YYYY-MM-DD.log
```

---

## Current State of Each File

### config/settings.py — STABLE, no changes needed
```python
AUTO_DEFAULT_LEVEL = 2
DEFAULT_DEST       = ~/Documents/outputs/original
UPRES_DEST         = ~/Documents/outputs/enhanced
BATCH_DEST         = ~/Documents/outputs/batches
UPSCALE_CEILING    = 1440
UPSCALE_STEPS      = [720, 1080, 1440]
SOURCE_CEILING     = {1440: 0, 720: 1440, 0: 1080}
CEILING_MAX_PASSES = {0: 4, 1440: 3, 1080: 2, 720: 2}
BATCH_WORKERS      = 2
BATCH_FRAGMENT_THREADS = 4
```

### filters/presets.py — STABLE, complete
Contains:
- `QualityTier` enum (EXCELLENT/GOOD/FAIR/POOR/BROKEN)
- `CLEANUP` dict (deblock + deband per tier, at source resolution)
- `MAIN` dict (deblock + deband + unsharp per tier, before upscale)
- `EnhancePreset` enum (CLEAN/RESTORE/SHARP/CINEMATIC/DEEP_CLEAN/STABILIZE)
- `PRESET_FILTERS` dict (filter list per EnhancePreset)
- `NO_DECAY_PRESETS` set (STABILIZE skips decay — stabilization is binary)
- `SECRET_FILTERS` dict (a/b/c/d raw filter chains for secret menu)

QualityTier system (single-pass path) and EnhancePreset system (multi-pass path) are
separate and independent. Do not conflate them.

### calibration.py — STABLE, complete
- `get_duration(path)` — ffprobe duration in seconds
- `run_calibration(path, vf, resolution)` — 3-second test encode, saves speed factor
- `load_calibration()` — reads `~/.enxr_calibration.json`
- `update_calibration(resolution, actual_seconds, duration)` — 70/30 blend after real encode
- `estimate_time(duration, passes, resolution, cal)` — returns human-readable string or None

Calibration file: `~/.enxr_calibration.json` — `{"720": 1.8, "1080": 0.9, "1440": 0.45}`
(values are encode_speed = clip_secs / wall_time; filled by real calibration runs)

### ffmpeg.py — STABLE, complete
Key facts:
- `_get_dims()` returns `(w, h, is_portrait, short_side, codec_name)` — 5 values
- `_encode()`: h264_videotoolbox → hevc_videotoolbox → RuntimeError. DO NOT CHANGE.
- `_ffmpeg_errors()`: strips `configuration:` line before keyword scan (prevents
  videotoolbox config string from matching as a false error)
- `_apply_decay(filters, decay)`: scales unsharp la, deblock alpha/beta/gamma/delta,
  deband range (floor 8), huesaturation saturation, vibrance intensity
- `_preset_chain()`: builds filter chain from EnhancePreset with optional decay
- `enhance()` signature:
  ```python
  def enhance(path, level=None, preset=None, user_filters=None,
              passes=1, target_res=None, ceiling=None,
              out_dir=None, keep_original=False)
  ```
- Pass A (cleanup): runs CLEANUP chain at source resolution, always
- Pass B (main): N passes at target_res — upscale on pass 1 only, decay on pass 2+
- `PASS_STRENGTH_DECAY = [1.0, 0.6, 0.35, 0.2]` defined at module level
- AV1 source warning already in enhance() — fires when codec == "av1"
- `cap_passes()` still exists but is now called with `eff_target` not ceiling

### enxgui.py — STABLE, complete
Key prompts:
- `prompt_upscale(skip, is_high_res)` — yes/no, shows enhancement-only msg if high-res
- `prompt_level(skip)` — tier 0-5 or auto
- `prompt_target_res(options, skip)` — picks from UPSCALE_STEPS below ceiling
- `prompt_passes(skip)` — 1-4 (also defined in enxr.py, see known issue below)
- `prompt_preset(skip)` — EnhancePreset 1-6 or 'x' for secret menu
- `_prompt_secret_menu()` — a/b/c/d or 'e' (custom filter string)
- Calibration estimate shown after all selections, before Processing...
- `main()` in enxgui.py is a standalone CLI entry point (rarely used directly)

### enxr.py — STABLE, complete
- `action_enhance_file()` is the main enhancement flow
- High-res path (short_side >= UPSCALE_CEILING): ceiling=0, passes=1, no preset prompt
- Normal path: prompt target_res → prompt passes → if passes > 1, prompt preset
- Calibration: checks cal dict, runs calibration if key missing, shows estimate
- Calls `update_calibration()` after real encode
- `action_batch_folder()` and `action_channel_shorts()` use OLD flow (ceiling=,
  level=2 hardcoded, no target_res/preset prompts) — this is intentional

---

## iOS Environment (CRITICAL)

- App: a-Shell (NOT Alpine, NOT Termux)
- Package manager: `pkg install <name>`
- FFmpeg build: custom iOS build, --disable-gpl, --enable-videotoolbox
- Available video encoders: h264_videotoolbox, hevc_videotoolbox, prores_videotoolbox
- libx264 NOT available (GPL disabled)
- libx265 NOT available (GPL disabled)
- Python 3.11
- All file paths under: /private/var/mobile/Containers/Data/Application/.../Documents/

---

## WHAT TO BUILD NEXT

All four original tasks are complete. Below are remaining work items.

---

### ISSUE: `prompt_passes()` is duplicated

`enxr.py` defines its own `prompt_passes()` (lines ~126-139) instead of using the one
in `enxgui.py`. They are functionally identical. One should be removed.

Fix: delete `prompt_passes()` from `enxr.py` and import `prompt_passes` from `enxgui`.
Check that `action_batch_folder()` and `action_channel_shorts()` call `prompt_passes()`
and update their imports accordingly.

---

### ISSUE: Batch paths don't use new prompt flow

`action_batch_folder()` and `action_channel_shorts()` use `level=2` hardcoded and
`ceiling=` (old style). They don't offer target_res or preset selection.

This is currently intentional (batch keeps simple behavior). If the user later wants
preset selection in batch mode, add it here. Do not change without explicit instruction.

---

### INVESTIGATE: `downloader.py` has an uncommitted modification

`git status` shows `downloader.py` as modified in the working tree. The handoff rule
says never touch this file. Verify whether this change is intentional before committing
or discarding it. Do not silently include it in a commit.

---

## Completed Tasks (for reference)

### Task 1: Decouple Resolution from Passes — DONE
- `target_res` param in `enhance()` sets explicit upscale target
- Upscale happens once on pass 1 only; subsequent passes refine at target_res
- `PASS_STRENGTH_DECAY = [1.0, 0.6, 0.35, 0.2]` applied to filter params
- `prompt_target_res()` in enxgui.py lets user pick 720/1080/1440

### Task 2: Render Time Estimator — DONE
- `calibration.py` implements calibration + estimation
- First run triggers a 3-second calibration encode, saves speed factor
- Subsequent runs show "Estimated time: ~X min YY sec (N passes at Zp)"
- `update_calibration()` blends observed speed back in after each real encode

### Task 3: Named Preset System — DONE
- `EnhancePreset` enum with CLEAN/RESTORE/SHARP/CINEMATIC/DEEP_CLEAN/STABILIZE
- `PRESET_FILTERS` dict in presets.py
- `prompt_preset()` in enxgui.py, shown only when passes > 1
- Secret menu accessible by typing 'x' at preset prompt

### Task 4: Wire Together — DONE
- Single pass → QualityTier auto-detect → CLEANUP + MAIN chain (unchanged)
- Multi-pass → EnhancePreset → N passes with decay at target_res
- Calibration estimate shown after all selections, before encode
- Secret menu available at preset selection step

---

## Known Issues (all resolved)

### `_ffmpeg_errors()` false matches — FIXED
The `configuration:` line is now stripped before keyword scanning.
`"videotoolbox"` removed from keyword list.
Location: `ffmpeg.py`, `_ffmpeg_errors()`.

### AV1 source warning — IMPLEMENTED
`_get_dims()` now returns `codec_name` as 5th value.
`enhance()` prints warning when `codec == "av1"`.

---

## Key Design Principles (DO NOT VIOLATE)

1. **Never guess at intent** — re-read this doc if unsure
2. **Never touch _encode()** — encoder is finalized and working on iOS
3. **Never touch downloader.py or logger.py**
4. **Decay is applied to filter params, not by swapping presets** — calculate scaled values
5. **Resolution jump is ONE step, always before passes loop** — passes are post-upscale refinement
6. **Single pass = old behavior** — QualityTier auto-detect, no preset menu, no changes to existing path
7. **Commit after each task**, not after each file edit

---

## Environment

- Dev platform: Windows 10, Python 3.11.9
- Target platform: iOS, a-Shell, Python 3.11
- FFmpeg: iOS custom build (videotoolbox only, no GPL codecs)
- yt-dlp: 2026.3.17
- Repo: https://github.com/gleekr/enxr
- Contact: gleeky@tuta.io

---

## iOS FFmpeg — Available Encoders

Flags: V=video, F=frame-level multithreading, S=slice-level multithreading, D=direct rendering

```
V....D h264_videotoolbox    -- PRIMARY encoder (Apple HW H.264)
V....D hevc_videotoolbox    -- FALLBACK encoder (Apple HW H.265)
V....D prores_videotoolbox  -- LAST RESORT (huge files, avoid)
VFS..D ffv1                 -- lossless, not useful for output
VFS..D magicyuv             -- lossless, not useful for output
VF...D utvideo              -- lossless, not useful for output
```

No libx264, no libx265 -- GPL disabled in this build.
Encoder chain in _encode(): h264_videotoolbox -> hevc_videotoolbox -> RuntimeError.
DO NOT add prores or any other encoder to the chain without explicit instruction.

---

## iOS FFmpeg — Available Filters (relevant to enhancement)

Restoration / Cleanup:
- deblock      -- deblocking (already used)
- deband       -- debanding (already used)
- dctdnoiz     -- DCT-based denoising (good for compression artifacts)
- fftdnoiz     -- FFT-based 3D denoising (slower, more thorough)
- gradfun      -- fast gradient-based debanding
- median       -- median filter (salt-pepper noise)
- yaepblur     -- edge-preserving blur

Sharpening:
- unsharp      -- unsharp mask (already used)
- guided       -- guided filter (edge-aware sharpening)

Color / Look:
- huesaturation  -- hue, saturation, intensity
- vibrance       -- saturation boost (protects skin tones)
- curves         -- RGB tone curves
- exposure       -- exposure adjustment
- grayworld      -- auto white balance

Stabilization:
- deshake      -- motion stabilization
- deflicker    -- temporal luminance flicker removal

Scaling:
- zscale       -- high quality resize (already used, lanczos + error diffusion)

NOT available -- do not use:
- hqdn3d       -- was in old presets.py, NOT in this build
- nlmeans      -- not listed in build
- libx264/libx265 -- GPL, not compiled in
