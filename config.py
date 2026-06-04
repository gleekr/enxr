import os, platform
from enum import Enum

# ── Paths ─────────────────────────────────────────────────────────────────────
DEFAULT_DEST = os.path.expanduser("~/Documents/vids/og")
UPRES_DEST   = os.path.expanduser("~/Documents/vids/hd")
BATCH_OG     = os.path.expanduser("~/Documents/vids/batch/og")
BATCH_HD     = os.path.expanduser("~/Documents/vids/batch/hd")

# ── Upscale ladder ────────────────────────────────────────────────────────────
UPSCALE_CEILING = 1440
UPSCALE_STEPS   = [480, 720, 1080, 1440]
AUTO_DEFAULT_LEVEL = 2

# Standard short-side sizes. Any source snaps to the closest one before lookup.
STANDARD_SIZES = [360, 480, 720, 1080, 1440]

# ── Source tier -> upscale ceiling (short side). 0 = already high enough ───────
SOURCE_CEILING = {
    360:  480,
    480:  720,
    720:  1080,
    1080: 1440,
    1440: 0,
}


def _snap_standard(short_side: int) -> int:
    """Snap an arbitrary short side to the closest standard size (ties -> lower)."""
    return min(STANDARD_SIZES, key=lambda s: (abs(s - short_side), s))


def get_ceiling(short_side: int) -> int:
    """Upscale ceiling for a source, snapped to the nearest standard tier.
    Returns 0 when the source is already at/above 1440 (no upscale)."""
    if short_side >= 1440:
        return 0
    return SOURCE_CEILING[_snap_standard(short_side)]

# ── Download workers ──────────────────────────────────────────────────────────
BATCH_WORKERS          = 20
BATCH_FRAGMENT_THREADS = 4

# ── YouTube player clients (tried in order) ───────────────────────────────────
YT_PLAYER_CLIENTS = ["web", "android", "ios"]

# ── Browser cookie source ─────────────────────────────────────────────────────
def _find_cookie_file() -> str | None:
    for p in ("~/cookies.txt", "~/Documents/cookies.txt"):
        expanded = os.path.expanduser(p)
        if os.path.isfile(expanded):
            return expanded
    return None

COOKIE_FILE_PATH = _find_cookie_file() or os.path.expanduser("~/cookies.txt")

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

# ── PO Token server ───────────────────────────────────────────────────────────
# Set env var POT_SERVER_URL to activate, e.g.:
#   Windows/macOS (local):  http://127.0.0.1:4416
#   iOS → Windows on WiFi:  http://192.168.x.x:4416
POT_SERVER_URL: str | None = os.environ.get("POT_SERVER_URL") or None

# ── Quality tiers ─────────────────────────────────────────────────────────────
class QualityTier(Enum):
    EXCELLENT = 1
    GOOD      = 2
    FAIR      = 3
    POOR      = 4
    BROKEN    = 5

# ── Denoise presets (nlmeans by quality/speed tier) ──────────────────────────
# Tuned for: slow (best), med (1x realtime), fast (clean clips), very_fast (batch)
DENOISE = {
    "slow":      ["nlmeans=s=4:p=9:r=18"],
    "med":       ["nlmeans=s=2:p=6:r=12"],
    "fast":      ["nlmeans=s=1:p=4:r=8"],
    "very_fast": [],
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


def build_chain(denoise_preset: str, enhance_level: int, target: int,
                is_portrait: bool, do_scale: bool, user_filters=None) -> str:
    """Single-pass filtergraph: format -> denoise -> sharpen -> [scale] -> format."""
    filters = ["format=yuv420p"]
    filters += DENOISE.get(denoise_preset, [])
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
