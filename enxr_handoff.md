# enxr — Handoff Document
# For: Claude Code (autonomous loop, code-only changes)
# Updated: 2026-05-24 (full session rewrite)

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
├── filters/
│   └── presets.py       # QualityTier enum + CLEANUP/MAIN filter dicts
├── config/
│   └── settings.py      # all constants
└── log/                 # runtime only, YYYY-MM-DD.log
```

---

## Current State of Each File (as of end of session)

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

### filters/presets.py — STABLE, needs EXPANSION (see task 3 below)
Current structure: QualityTier enum (EXCELLENT/GOOD/FAIR/POOR/BROKEN),
CLEANUP dict (deblock + deband per tier), MAIN dict (deblock + deband + unsharp per tier).
This is the source-quality-based system. It stays. New named presets are ADDED alongside it.

### ffmpeg.py — ENCODER FIX APPLIED TONIGHT, stable
Key fix applied this session:
- Removed `-q:v 85` from VideoToolbox calls (caused -22 Invalid argument on iOS)
- Removed libx264 fallback entirely (libx264 is GPL, compiled out of iOS ffmpeg build)
- _encode() now: h264_videotoolbox → hevc_videotoolbox → RuntimeError (clean message)
- `high_quality` param kept in signature for API compat but does nothing (VTB manages quality internally)
DO NOT CHANGE _encode().

### enxgui.py — TWO FIXES APPLIED TONIGHT, stable
Fixes applied:
1. Enhancement-only mode (is_high_res): passes forced to 1, no passes prompt shown
2. is_high_res derived correctly from `short_side >= UPSCALE_CEILING` not from ceiling return value

### enxr.py — TWO FIXES APPLIED TONIGHT, stable
Fixes applied:
1. is_high_res fixed: was `ceiling == 0` (always False), now `short_side >= UPSCALE_CEILING`
2. ceiling derived as `0 if is_high_res else get_ceiling(short_side)`
3. passes forced to 1 when is_high_res, no passes prompt
4. Added UPSCALE_CEILING to config.settings import

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

## WHAT TO BUILD NEXT (in order)

---

### TASK 1: Decouple Resolution from Passes

**Current behavior (broken):**
Passes = number of steps up the resolution ladder (720→1080→1440).
Max passes is locked to ceiling which is locked to source resolution.
User picking "3 passes" on a 720p source silently gets capped to 2.

**New behavior:**
- Resolution target: user picks explicitly (or auto = ceiling)
- Passes: how many times the filter chain runs at the TARGET resolution
- Resolution jump (upscale) happens ONCE, before the passes loop
- Each pass runs at target resolution with DECAYING filter strength (see below)
- Pass 1 = full strength, pass 2 = 60%, pass 3 = 35%, pass 4 = 20%

**Decay curve (agreed):**
```python
PASS_STRENGTH_DECAY = [1.0, 0.6, 0.35, 0.2]  # index = pass number - 1
```
Apply decay to filter intensity params, not by swapping presets.
For unsharp: multiply `la` (luma amount) by decay factor.
For deblock: multiply alpha/beta/gamma/delta by decay factor.
For deband: scale range by decay (range * decay, floor 8).

**New enhance() signature:**
```python
def enhance(path, level=None, preset=None, user_filters=None,
            passes=1, target_res=None, ceiling=None, out_dir=None)
```
- `target_res`: explicit resolution target (e.g. 1440). None = auto (ceiling).
- Upscale to target_res in one step before passes loop.
- passes loop runs N times at target_res with decaying strength.

**New prompt flow in enxgui.py:**
```
Source: 720p (portrait)
Target resolution: [720 / 1080 / 1440*]   <- user picks, * = recommended ceiling
Passes: [1-4]                               <- always available, no ceiling cap
  1 = single enhancement
  2+ = refinement passes (strength auto-reduces each pass)
```

**In enxr.py action_enhance_file():**
Same flow — remove ceiling-based pass cap, add resolution picker before passes prompt.

---

### TASK 2: Render Time Estimator

**Goal:** Show estimated time to user as they select options, updates live as they change selections.

**Method:**
1. Probe file duration with ffprobe (already imported).
2. First time a user runs enhancement, do a 3-second calibration encode:
   - Encode first 3 seconds of file with chosen filter chain
   - Measure wall time
   - Calculate encode_speed = 3.0 / wall_time (e.g. 0.5x realtime)
   - Store in `~/.enxr_calibration.json` as `{resolution: speed_factor}`
3. On subsequent runs, load calibration and estimate:
   ```
   estimated_seconds = (duration / encode_speed) * passes * resolution_factor
   ```
   Where resolution_factor scales by pixel count relative to 1080p.
4. Display before encode starts:
   ```
   Estimated time: ~4 min 30 sec  (2 passes at 1440p)
   ```
5. If no calibration exists yet, show:
   ```
   [first run] calibrating encoder speed...
   ```

**Calibration file:** `~/.enxr_calibration.json`
```json
{"720": 1.8, "1080": 0.9, "1440": 0.45}
```
(these are example speed factors, actual values filled by calibration run)

**Where to implement:**
- New file: `calibration.py` — `run_calibration(path, resolution)`, `load_calibration()`, `estimate_time(duration, passes, resolution)`
- Call from `enxgui.py` after user finishes all selections, before Processing... line
- Update calibration silently after each real encode (compare estimated vs actual)

---

### TASK 3: Named Preset System (Multi-Pass Menu)

**Trigger:** Only shown when passes > 1. Single pass uses QualityTier auto-detect as before.

**New presets to add to filters/presets.py:**

```python
class EnhancePreset(Enum):
    CLEAN      = "clean"       # deblock + deband only, no sharpen
    RESTORE    = "restore"     # deblock + deband + light denoise (dctdnoiz)
    SHARP      = "sharp"       # unsharp focused, minimal denoise
    CINEMATIC  = "cinematic"   # huesaturation + vibrance + curves tone
    DEEP_CLEAN = "deep_clean"  # fftdnoiz + deblock + deband, max artifact removal
    STABILIZE  = "stabilize"   # deshake + deflicker (for shaky/flickery sources)
```

**Secret menu (accessible by typing 'x' or 'secret' at preset prompt):**
```
  [secret menu]
  a - raw unsharp (no deblock/deband)
  b - dctdnoiz only
  c - fftdnoiz only
  d - deflicker only
  e - custom filter string (advanced)
```

**Menu display when passes > 1:**
```
Enhancement preset:
  1 - Clean       (deblock + deband, safe)
  2 - Restore     (+ light denoise, typical YT)
  3 - Sharp       (sharpening focus)
  4 - Cinematic   (color + tone)
  5 - Deep Clean  (max artifact removal, slow)
  6 - Stabilize   (deshake + deflicker)
  secret..        (type 'x')
```

**Filter strings for each preset (build these carefully):**

CLEAN:
```
deblock=filter=strong:block=4:alpha=0.05:beta=0.05:gamma=0.05:delta=0.05,
deband=range=14:direction=0:blur=1
```

RESTORE:
```
deblock=filter=strong:block=4:alpha=0.07:beta=0.07:gamma=0.07:delta=0.07,
deband=range=16:direction=0:blur=1,
dctdnoiz=sigma=4:overlap=2
```

SHARP:
```
deblock=filter=weak:block=4:alpha=0.03:beta=0.03:gamma=0.03:delta=0.03,
unsharp=lx=5:ly=5:la=0.6:cx=5:cy=5:ca=0.0
```

CINEMATIC:
```
huesaturation=saturation=0.15:lightness=0.0,
vibrance=intensity=0.2,
curves=r='0/0 0.5/0.48 1/1':g='0/0 0.5/0.5 1/1':b='0/0 0.5/0.52 1/1'
```

DEEP_CLEAN:
```
deblock=filter=strong:block=8:alpha=0.12:beta=0.12:gamma=0.12:delta=0.12,
deband=range=22:direction=0:blur=1,
fftdnoiz=sigma=5:amount=0.8:block=32:overlap=0.5
```

STABILIZE:
```
deshake=x=-1:y=-1:w=-1:h=-1:rx=64:ry=64,
deflicker=size=5:mode=am
```

**Decay application per preset:**
- CLEAN, RESTORE, DEEP_CLEAN: decay deblock alpha/beta/gamma/delta, deband range
- SHARP: decay unsharp la value
- CINEMATIC: decay saturation and vibrance intensity
- STABILIZE: no decay (stabilization is binary, either needed or not)

---

### TASK 4: Wire Everything Together

After tasks 1-3 are individually working:

1. Single pass path: auto-detect QualityTier → existing CLEANUP+MAIN chain (unchanged)
2. Multi-pass path: user picks EnhancePreset → N passes with decay at target_res
3. Render estimator runs after all selections made, before encode
4. Secret menu available at preset selection step

---

## Known Issues (Fix These Too)

### 1. `_ffmpeg_errors()` returns wrong lines — FIX THIS
Location: `ffmpeg.py`, `_ffmpeg_errors()` function.

Current keyword list includes `"videotoolbox"` which matches ffmpeg's build
configuration string (the long `--enable-videotoolbox --disable-gpl...` line)
instead of the actual error. Real errors are invisible in the log.

Fix: strip the configuration line before keyword matching.
```python
def _ffmpeg_errors(stderr: str) -> str:
    if not stderr.strip():
        return "encode failed (no output)"
    keywords = ("error", "failed", "invalid", "unknown", "not found", "cannot")
    lines = stderr.strip().splitlines()
    # skip ffmpeg build config line (starts with "configuration:")
    lines = [l for l in lines if not l.strip().startswith("configuration:")]
    relevant = [l.strip() for l in lines if any(k in l.lower() for k in keywords)]
    return " | ".join(relevant[-5:]) if relevant else (lines[-1].strip() if lines else "encode failed")
```
Note: `"videotoolbox"` removed from keywords — it was only matching config output, not real errors.

### 2. AV1 source files are slow — DOCUMENT, no code change needed
When source video is AV1 encoded (libaom-av1), `-hwaccel none` forces full
software decode on CPU. On iPhone this is very slow — a 1080p tier 4 cleanup
pass can take several minutes. This is expected behavior, not a bug.

Consider adding a warning when ffprobe detects AV1 codec:
```
[warn] AV1 source detected -- software decode required, processing will be slow
```
Check codec in `_get_dims()` by adding `codec_name` to ffprobe fields.
Display warning before encode starts, not after.

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
