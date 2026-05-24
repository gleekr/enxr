from enum import Enum


class Preset(Enum):
    LOW    = 1
    MEDIUM = 2
    HIGH   = 3


PRESETS = {
    Preset.LOW: {
        "deblock":    "deblock=filter=strong:block=4:alpha=0.02:beta=0.02:gamma=0.02:delta=0.02",
        "denoise":    "dctdnoiz=4.5",
        "has_deband": False,
        "deband":     None,
        "sharpen":    "unsharp=lx=3:ly=3:la=0.15:cx=3:cy=3:ca=0.0",
    },
    Preset.MEDIUM: {
        "deblock":    "deblock=filter=strong:block=4:alpha=0.07:beta=0.07:gamma=0.07:delta=0.07",
        "denoise":    "dctdnoiz=10",
        "has_deband": True,
        "deband":     "deband=range=14:direction=0:blur=1",
        "sharpen":    "unsharp=lx=3:ly=3:la=0.3:cx=3:cy=3:ca=0.0",
    },
    Preset.HIGH: {
        "deblock":    "deblock=filter=strong:block=8:alpha=0.15:beta=0.15:gamma=0.15:delta=0.15",
        "denoise":    "dctdnoiz=15",
        "has_deband": True,
        "deband":     "deband=range=22:direction=0:blur=1",
        "sharpen":    "unsharp=lx=3:ly=3:la=0.45:cx=3:cy=3:ca=0.0",
    },
}
