from enum import Enum


class QualityTier(Enum):
    EXCELLENT = 1
    GOOD      = 2
    FAIR      = 3
    POOR      = 4
    BROKEN    = 5


class EnhancePreset(Enum):
    CLEAN      = "clean"
    RESTORE    = "restore"
    SHARP      = "sharp"
    CINEMATIC  = "cinematic"
    DEEP_CLEAN = "deep_clean"
    STABILIZE  = "stabilize"


# Presets that skip decay (stabilization is binary, decay not meaningful)
NO_DECAY_PRESETS = {EnhancePreset.STABILIZE}


PRESET_FILTERS = {
    EnhancePreset.CLEAN: [
        "deblock=filter=strong:block=4:alpha=0.05:beta=0.05:gamma=0.05:delta=0.05",
        "deband=range=14:direction=0:blur=1",
    ],
    EnhancePreset.RESTORE: [
        "deblock=filter=strong:block=4:alpha=0.07:beta=0.07:gamma=0.07:delta=0.07",
        "deband=range=16:direction=0:blur=1",
        "dctdnoiz=sigma=4:overlap=2",
    ],
    EnhancePreset.SHARP: [
        "deblock=filter=weak:block=4:alpha=0.03:beta=0.03:gamma=0.03:delta=0.03",
        "unsharp=lx=5:ly=5:la=0.6:cx=5:cy=5:ca=0.0",
    ],
    EnhancePreset.CINEMATIC: [
        "huesaturation=saturation=0.15:lightness=0.0",
        "vibrance=intensity=0.2",
        "curves=r='0/0 0.5/0.48 1/1':g='0/0 0.5/0.5 1/1':b='0/0 0.5/0.52 1/1'",
    ],
    EnhancePreset.DEEP_CLEAN: [
        "deblock=filter=strong:block=8:alpha=0.12:beta=0.12:gamma=0.12:delta=0.12",
        "deband=range=22:direction=0:blur=1",
        "fftdnoiz=sigma=5:amount=0.8:block=32:overlap=0.5",
    ],
    EnhancePreset.STABILIZE: [
        "deshake=x=-1:y=-1:w=-1:h=-1:rx=64:ry=64",
        "deflicker=size=5:mode=am",
    ],
}

# Secret menu filter chains (raw, no QualityTier detection)
SECRET_FILTERS = {
    'a': ["unsharp=lx=5:ly=5:la=0.5:cx=5:cy=5:ca=0.0"],
    'b': ["dctdnoiz=sigma=4:overlap=2"],
    'c': ["fftdnoiz=sigma=5:amount=0.8:block=32:overlap=0.5"],
    'd': ["deflicker=size=5:mode=am"],
}


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
        "unsharp=lx=5:ly=5:la=0.6:cx=5:cy=5:ca=0.0",
    ],
    QualityTier.GOOD: [
        "format=yuv420p",
        "unsharp=lx=5:ly=5:la=0.55:cx=5:cy=5:ca=0.0",
    ],
    QualityTier.FAIR: [
        "format=yuv420p",
        "deband=range=12:direction=0:blur=1",
        "unsharp=lx=5:ly=5:la=0.6:cx=5:cy=5:ca=0.0",
    ],
    QualityTier.POOR: [
        "format=yuv420p",
        "deband=range=16:direction=0:blur=1",
        "unsharp=lx=5:ly=5:la=0.7:cx=5:cy=5:ca=0.0",
    ],
    QualityTier.BROKEN: [
        "format=yuv420p",
        "deband=range=20:direction=0:blur=1",
        "unsharp=lx=5:ly=5:la=0.8:cx=5:cy=5:ca=0.0",
    ],
}
