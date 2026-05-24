from enum import Enum


class QualityTier(Enum):
    EXCELLENT = 1
    GOOD      = 2
    FAIR      = 3
    POOR      = 4
    BROKEN    = 5


# Table A: Cleanup -- deblock + deband only, no transform filters, no sharpening.
# Fast SIMD filters that stabilise the signal in one pass at source resolution.
CLEANUP = {
    QualityTier.EXCELLENT: [
        "format=yuv420p",
        "deblock=filter=weak:block=4:alpha=0.02:beta=0.02:gamma=0.02:delta=0.02",
        "format=yuv420p",
    ],
    QualityTier.GOOD: [
        "format=yuv420p",
        "deblock=filter=strong:block=4:alpha=0.04:beta=0.04:gamma=0.04:delta=0.04",
        "format=yuv420p",
    ],
    QualityTier.FAIR: [
        "format=yuv420p",
        "deblock=filter=strong:block=4:alpha=0.07:beta=0.07:gamma=0.07:delta=0.07",
        "deband=range=14:direction=0:blur=1",
        "format=yuv420p",
    ],
    QualityTier.POOR: [
        "format=yuv420p",
        "deblock=filter=strong:block=8:alpha=0.10:beta=0.10:gamma=0.10:delta=0.10",
        "deband=range=18:direction=0:blur=1",
        "format=yuv420p",
    ],
    QualityTier.BROKEN: [
        "format=yuv420p",
        "deblock=filter=strong:block=8:alpha=0.14:beta=0.14:gamma=0.14:delta=0.14",
        "deband=range=22:direction=0:blur=1",
        "format=yuv420p",
    ],
}

# Table B: Main -- sharpen + upscale on cleaned signal.
# unsharp is fast SIMD. zscale lanczos is the heaviest filter here.
# No dctdnoiz -- cleanup handled blocking/banding, main focuses on detail recovery.
# zscale and final format=yuv420p appended dynamically by _main_chain().
MAIN = {
    QualityTier.EXCELLENT: [
        "format=yuv420p",
        "unsharp=lx=5:ly=5:la=0.5:cx=5:cy=5:ca=0.0",
    ],
    QualityTier.GOOD: [
        "format=yuv420p",
        "deblock=filter=weak:block=4:alpha=0.02:beta=0.02:gamma=0.02:delta=0.02",
        "unsharp=lx=3:ly=3:la=0.4:cx=3:cy=3:ca=0.0",
    ],
    QualityTier.FAIR: [
        "format=yuv420p",
        "deblock=filter=strong:block=4:alpha=0.05:beta=0.05:gamma=0.05:delta=0.05",
        "deband=range=12:direction=0:blur=1",
        "unsharp=lx=3:ly=3:la=0.45:cx=3:cy=3:ca=0.0",
    ],
    QualityTier.POOR: [
        "format=yuv420p",
        "deblock=filter=strong:block=4:alpha=0.07:beta=0.07:gamma=0.07:delta=0.07",
        "deband=range=16:direction=0:blur=1",
        "unsharp=lx=5:ly=5:la=0.55:cx=5:cy=5:ca=0.0",
    ],
    QualityTier.BROKEN: [
        "format=yuv420p",
        "deblock=filter=strong:block=8:alpha=0.10:beta=0.10:gamma=0.10:delta=0.10",
        "deband=range=20:direction=0:blur=1",
        "unsharp=lx=5:ly=5:la=0.65:cx=5:cy=5:ca=0.0",
    ],
}
