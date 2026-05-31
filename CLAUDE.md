# enxr

enxr is a free, open source, cross-platform video fixer and enhancer.

It uses **yt-dlp** for downloading and **FFmpeg** for processing. The core idea is a single-pass filter pipeline: restore compression artifacts (deblock/deband), sharpen, and upscale — all in one encode, no quality loss from chaining passes.

The goal is to expand this into a comprehensive video enhancement suite. We test and fine-tune the filter chain against real-world content across quality tiers (excellent / good / fair / poor / broken) to make sure the output actually looks better, not just technically processed.

## Stack

- `yt-dlp` — downloading (YouTube + many other sites). Player client strategy: ios/tv first (avoids CAPTCHA), web fallback.
- `FFmpeg` — encode pipeline. libx264 is the default everywhere; a hardware encoder is used only when its GPU is present (h264_nvenc on Windows/Linux with a dedicated NVIDIA GPU, h264_videotoolbox on macOS). Output forced to yuv420p.
- Python 3.11 (Windows), 3.10+ required.

## Files

| File | Role |
|---|---|
| `config.py` | All constants: paths, quality tiers, filter tables, filter chain builder |
| `downloader.py` | yt-dlp wrapper: single download, batch/channel, interactive selection |
| `ffmpeg.py` | FFmpeg encode pipeline: restore + sharpen + scale |
| `enxgui.py` | Terminal GUI: resolution/restore/enhance prompts, calibration display |
| `enxr.py` | Main entry point |
| `calibration.py` | Encoder speed calibration and ETA estimation |
| `test_bench.py` | Benchmark: encodes local test clips, logs results to `log/` |
| `logger.py` | Error logging |

## Current focus: batch download

Batch download (`downloader.py`) supports:

- `@channel/shorts` and `@channel/videos` URLs
- Any playlist URL on any yt-dlp-supported site
- Sort by popular (view_count descending)
- Interactive prompt: download all / first # / specify ranges (e.g. `3,6,8,9-18,34-50`)
- Up to 20 parallel downloads (`BATCH_WORKERS` in `config.py`)

**Critical rule: do not break the downloader.** The download logic (`download`, `download_batch`, `_dl_one`) is not to be touched when adding features. Only add prompts and routing around the existing engine.

## Platforms

- Windows PC (primary dev, VS Code + Claude Code)
- iOS (A-Shell / iSH)
- Android Snapdragon (incoming)

## Key constraints

- Never push to GitHub without explicit user permission.
- Fine-grained PAT scoped to `gleekr/enxr` is stored in `git config --global github.token`.
- Do not write new memory files. Token and auth are not persisted to disk.
