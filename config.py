import os, platform
from enum import Enum

# ── Paths ─────────────────────────────────────────────────────────────────────
DEFAULT_DEST = os.path.expanduser("~/Documents/vids/og")
UPRES_DEST   = os.path.expanduser("~/Documents/vids/hd")
BATCH_OG     = os.path.expanduser("~/Documents/vids/batch/og")
BATCH_HD     = os.path.expanduser("~/Documents/vids/batch/hd")

# ── Upscale ladder ────────────────────────────────────────────────────────────
UPSCALE_CEILING = 1440
UPSCALE_STEPS   = [720, 1080, 1440]
AUTO_DEFAULT_LEVEL = 2

# ── Source -> ceiling mapping ─────────────────────────────────────────────────
SOURCE_CEILING = {
    1440: 0,
    720:  1440,
    0:    1080,
}

# ── Download workers ──────────────────────────────────────────────────────────
BATCH_WORKERS          = 20
BATCH_FRAGMENT_THREADS = 4

# ── YouTube player clients ────────────────────────────────────────────────────
YT_PLAYER_CLIENT          = ["ios", "tv"]
YT_PLAYER_CLIENT_FALLBACK = ["web"]

# ── Browser cookie source ─────────────────────────────────────────────────────
COOKIE_FILE_PATH = os.path.expanduser("~/cookies.txt")

def _detect_cookie_browser() -> str | None:
    """Return the first available browser name for yt-dlp cookiesfrombrowser."""
    system = platform.system()
    home   = os.path.expanduser("~")
    lad    = os.environ.get("LOCALAPPDATA", "")

    candidates = {
        "safari": {"Darwin":  os.path.join(home, "Library", "Safari")},
        "brave":  {"Darwin":  os.path.join(home, "Library", "Application Support", "BraveSoftware", "Brave-Browser"),
                   "Windows": os.path.join(lad,  "BraveSoftware", "Brave-Browser"),
                   "Linux":   os.path.join(home, ".config", "BraveSoftware", "Brave-Browser")},
        "chrome": {"Darwin":  os.path.join(home, "Library", "Application Support", "Google", "Chrome"),
                   "Windows": os.path.join(lad,  "Google", "Chrome"),
                   "Linux":   os.path.join(home, ".config", "google-chrome")},
    }

    for browser in ("safari", "brave", "chrome"):
        path = candidates[browser].get(system)
        if path and os.path.isdir(path):
            return browser
    return None

COOKIE_BROWSER: str | None = _detect_cookie_browser()
COOKIE_FILE:    str | None = COOKIE_FILE_PATH if (not COOKIE_BROWSER and os.path.isfile(COOKIE_FILE_PATH)) else None

# ── Quality tiers ─────────────────────────────────────────────────────────────
class QualityTier(Enum):
    EXCELLENT = 1
    GOOD      = 2
    FAIR      = 3
    POOR      = 4
    BROKEN    = 5

# ── Restore table (deblock/deband, level 0-5) ─────────────────────────────────
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

# ── Sharpen table (unsharp luma-only, level 0-5) ──────────────────────────────
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
    """Single-pass filtergraph: format -> restore -> sharpen -> [scale] -> format."""
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
