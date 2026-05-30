# enxr

Free, open source, cross-platform video enhancer. Downloads via **yt-dlp**, processes with **FFmpeg**.

Single-pass pipeline: restore compression artifacts → sharpen → upscale. One encode, no quality loss from chaining.

---

## What it does

- Download single videos or full channel batches (YouTube + any yt-dlp-supported site)
- Batch select by popularity: download all / first N / custom ranges (`3,6,8,9-18,34-50`)
- Deblock, deband, and sharpen at source resolution before upscaling
- Upscale to 720p / 1080p / 1440p using Lanczos
- Hardware encoding: NVENC / QSV on Windows, VideoToolbox on macOS, software fallback everywhere

---

## Requirements

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) on PATH
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (`pip install yt-dlp`)

---

## Usage

```bash
# Interactive menu
python enxr.py

# Enhance a local file
python enxr.py video.mp4

# Download + enhance a URL
python enxr.py https://youtube.com/watch?v=...

# Batch download from a channel (interactive selection)
python downloader.py https://youtube.com/@channel/shorts
python downloader.py https://youtube.com/@channel/videos

# Benchmark encode speed on local clips
python test_bench.py
python test_bench.py clip.mp4
```

---

## Files

| File | Role |
|---|---|
| `enxr.py` | Main entry point — interactive menu |
| `downloader.py` | yt-dlp wrapper: single + batch download |
| `ffmpeg.py` | FFmpeg encode pipeline |
| `enxgui.py` | Terminal UI: prompts + calibration display |
| `config.py` | All constants: paths, filter tables, chain builder |
| `calibration.py` | Encoder speed calibration + ETA |
| `test_bench.py` | Render time benchmark |
| `logger.py` | Error logging |

---

## Platforms

Windows · macOS · Linux · iOS (iSH) · Android (in progress)
