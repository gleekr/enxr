from enum import Enum


class QualityTier(Enum):
    """Source-quality buckets used only for the detected-quality display and
    to suggest a sensible default restore level."""
    EXCELLENT = 1
    GOOD      = 2
    FAIR      = 3
    POOR      = 4
    BROKEN    = 5


# ── Restore table (level 0-5) ──────────────────────────────────────────────────
# Deblock + deband at source resolution. SIMD-only, fast. Level 0 = no restore.
# Runs BEFORE sharpening so artifacts aren't amplified by the sharpen stage.
RESTORE = {
    0: [],
    1: ["deblock=filter=weak:block=4:alpha=0.02:beta=0.02:gamma=0.02:delta=0.02"],
    2: ["deblock=filter=strong:block=4:alpha=0.04:beta=0.04:gamma=0.04:delta=0.04"],
    3: ["deblock=filter=strong:block=4:alpha=0.07:beta=0.07:gamma=0.07:delta=0.07",
        "deband=range=14:direction=0:blur=1"],
    4: ["deblock=filter=strong:block=8:alpha=0.10:beta=0.10:gamma=0.10:delta=0.10",
        "deband=range=18:direction=0:blur=1"],
    5: ["deblock=filter=strong:block=8:alpha=0.14:beta=0.14:gamma=0.14:delta=0.14",
        "deband=range=22:direction=0:blur=1"],
}

# ── Sharpen table (level 0-5) ──────────────────────────────────────────────────
# unsharp is fast SIMD regardless of strength (cost is set by radius, fixed 5x5),
# so sharpening can go strong while staying cheap. Luma only (ca=0.0) to avoid
# chroma ringing. Level 0 = no sharpening. Applied AFTER restore, BEFORE scaling.
SHARPEN = {
    0: [],
    1: ["unsharp=lx=5:ly=5:la=0.4:cx=5:cy=5:ca=0.0"],
    2: ["unsharp=lx=5:ly=5:la=0.6:cx=5:cy=5:ca=0.0"],
    3: ["unsharp=lx=5:ly=5:la=0.85:cx=5:cy=5:ca=0.0"],
    4: ["unsharp=lx=5:ly=5:la=1.1:cx=5:cy=5:ca=0.0"],
    5: ["unsharp=lx=5:ly=5:la=1.4:cx=5:cy=5:ca=0.0"],
}


def _clamp(level: int) -> int:
    return max(0, min(5, int(level)))


def build_chain(restore_level: int, enhance_level: int, target: int,
                is_portrait: bool, do_scale: bool, user_filters=None) -> str:
    """
    Single-pass filtergraph: format -> restore -> sharpen -> [scale] -> format.

    Scaling is always the LAST operation (before the closing pixel-format
    conversion) so sharpening runs at source resolution -- cheaper and crisper.
    format=yuv420p bookends keep the chain VideoToolbox-compatible.
    """
    filters = ["format=yuv420p"]
    filters += RESTORE.get(_clamp(restore_level), [])
    filters += SHARPEN.get(_clamp(enhance_level), [])
    if user_filters:
        filters += list(user_filters)
    if do_scale:
        filters.append(
            f"zscale=w={target}:h=-2:filter=lanczos:dither=error_diffusion"
            if is_portrait else
            f"zscale=w=-2:h={target}:filter=lanczos:dither=error_diffusion"
        )
    filters.append("format=yuv420p")
    return ",".join(filters)
