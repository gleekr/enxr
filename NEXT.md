# Handoff — smart-4k-pipeline branch

Cross-device note (built on Android/Termux, continuing on Windows desktop).

## What landed
Resolution + quality-aware enhance pipeline, all-CPU, outputs mp4, upscales up to 4K
only when the source justifies it.

- `config.py`
  - Ladder extended to 2160 (4K).
  - `smart_target(short_side, tier)` — quality-gated auto target.
    excellent→+2 (1080→4K), good→+1 (1440→4K), fair→+1 cap 1440, poor/broken→no upscale.
  - Tier-driven restore tables: `DEBLOCK` (pp7/fspp), `DEBAND_TIERS` (gradfun),
    `TIER_SIGMA` denoise (bm3d on `slow`, nlmeans otherwise), `SHARPEN_CAS` (CAS).
  - `build_chain`: deblock → denoise → deband → zscale/lanczos → CAS.
- `ffmpeg.py`
  - Auto path probes tier and uses `smart_target`.
  - `_detect_tier` normalizes by **sqrt** of the area ratio (sub-linear) so clean
    low-res clips aren't mis-rated "excellent". Verified against all 5 testclips.
  - libx264 high profile, res-tuned CRF, +faststart; `h264_mediacodec` HW path for
    `very_fast`/batch; libx264 always the guaranteed fallback.
  - CLI flags `--2160` / `--4k`.

Downloader untouched (project rule).

## Verified
All 5 testclips → valid uncorrupted h264 mp4. good_1440p → 3840×2160 (4K).
Tier→action after the sqrt fix:
broken_360p→restore, fair_480p→720, fair_1080p_banding→restore,
poor_720p→1080, good_1440p→4K.

## Still open / next
- **4K encode speed**: good_1440p→4K took ~96s for a 2s clip (libx264 `medium`).
  Consider a faster preset (`faster`/`fast`) or capped CRF at ≥2160.
- **libplacebo/Vulkan dropped**: software-rasterized under Termux proot, too slow.
  On a real GPU (e.g. the Windows NVIDIA box) it's worth re-introducing for
  ewa_lanczos upscaling + deband — gate it behind a working-GPU probe.
- **VMAF/XPSNR verification** (task #4) deferred — add to score output vs source.
- **Tier thresholds** are calibrated against 5 synthetic clips; revisit against
  real downloaded content.
