import os, platform
from enum import Enum

# ── Paths ─────────────────────────────────────────────────────────────────────
DEFAULT_DEST = os.path.expanduser("~/Documents/vids/og")
UPRES_DEST   = os.path.expanduser("~/Documents/vids/hd")
BATCH_OG     = os.path.expanduser("~/Documents/vids/batch/og")
BATCH_HD     = os.path.expanduser("~/Documents/vids/batch/hd")

# ── Upscale ladder ────────────────────────────────────────────────────────────
# Extended to 2160 (4K). The ladder is purely resolution; whether a given source
# is *allowed* to climb it is decided by smart_target() using the quality tier.
UPSCALE_CEILING = 2160
UPSCALE_STEPS   = [480, 720, 1080, 1440, 2160]
AUTO_DEFAULT_LEVEL = 2

LADDER = [360, 480, 720, 1080, 1440, 2160]

# Standard short-side sizes. Any source snaps to the closest one before lookup.
STANDARD_SIZES = LADDER

# ── Source tier -> single-step upscale ceiling (short side). 0 = already top ────
# Used by the interactive GUI to offer the next sensible rung. The smart auto
# path uses smart_target() instead, which can climb further for good footage.
SOURCE_CEILING = {
    360:  480,
    480:  720,
    720:  1080,
    1080: 1440,
    1440: 2160,
    2160: 0,
}


def _snap_standard(short_side: int) -> int:
    """Snap an arbitrary short side to the closest standard size (ties -> lower)."""
    return min(STANDARD_SIZES, key=lambda s: (abs(s - short_side), s))


def get_ceiling(short_side: int) -> int:
    """Single-rung upscale ceiling for a source, snapped to the nearest tier.
    Returns 0 when the source is already at/above 2160 (no upscale)."""
    if short_side >= 2160:
        return 0
    return SOURCE_CEILING[_snap_standard(short_side)]


# ── Quality-gated smart target ────────────────────────────────────────────────
# How far (in ladder steps) a source may climb, and the absolute ceiling, by
# detected quality tier. This is the "upscale only if good enough" rule:
#   excellent -> up to +2 steps, reaching 4K (e.g. 1080 -> 2160)
#   good      -> up to +1 step,  reaching 4K (e.g. 1440 -> 2160)
#   fair      -> up to +1 step,  capped at 1440 (gentle, e.g. 480 -> 720)
#   poor      -> no upscale (restore only — upscaling magnifies artifacts)
#   broken    -> no upscale (restore only)
TIER_STEPS   = {1: 2, 2: 1, 3: 1, 4: 0, 5: 0}
TIER_CEILING = {1: 2160, 2: 2160, 3: 1440, 4: 0, 5: 0}


def smart_target(short_side: int, tier: int) -> int:
    """Resolution + quality aware target short-side. Never below the source."""
    if short_side >= 2160:
        return short_side
    steps = TIER_STEPS.get(tier, 1)
    cap   = TIER_CEILING.get(tier, 1440)
    if steps == 0 or cap == 0:
        return short_side
    snap = _snap_standard(short_side)
    idx  = LADDER.index(snap)
    by_steps = LADDER[min(idx + steps, len(LADDER) - 1)]
    return max(short_side, min(by_steps, cap))

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


# ══════════════════════════════════════════════════════════════════════════════
#  FILTER PIPELINE
#
#  Order (matters):  deblock -> denoise -> deband -> upscale -> sharpen
#    * deblock/denoise run at SOURCE resolution (cheaper, and you don't want to
#      enlarge artifacts before removing them)
#    * deband (gradfun) then upscale (zscale/lanczos) -- all CPU, the 8 cores are
#      plenty and far faster here than software-rasterized Vulkan under proot
#    * sharpen (CAS) runs LAST, at target resolution
#
#  Restore strength (deblock/deband/denoise sigma) is chosen by the detected
#  quality TIER. The user's denoise_preset only picks the speed/quality engine,
#  and enhance_level only picks sharpen strength.
# ══════════════════════════════════════════════════════════════════════════════

# Deblock (compression block removal) by tier. Clean tiers skip it.
DEBLOCK = {
    1: [],
    2: [],
    3: ["pp7=qp=4:mode=medium"],
    4: ["fspp=quality=5"],
    5: ["fspp=quality=5", "pp7=qp=5:mode=hard"],
}

# Deband by tier (skies/gradients banding from low-bitrate encodes).
DEBAND_TIERS = {1: False, 2: False, 3: True, 4: True, 5: True}

# Denoise sigma by tier (0 = skip). Engine chosen by preset below.
TIER_SIGMA = {1: 0.0, 2: 1.5, 3: 3.0, 4: 5.0, 5: 7.0}

# Sharpen: CAS (Contrast Adaptive Sharpen) strength 0-1 by enhance level.
# CAS is used instead of unsharp because it doesn't ring/halo on upscaled edges.
SHARPEN_CAS = {0: 0.0, 1: 0.20, 2: 0.35, 3: 0.50, 4: 0.65, 5: 0.80}


def _clamp(level: int) -> int:
    return max(0, min(5, int(level)))


def _denoise_filters(preset: str, tier: int) -> list:
    """Denoise stage: engine from preset, strength (sigma) from tier.

    bm3d is reserved for the explicit "slow" preset (it is the best quality but
    far heavier than everything else). Everything faster uses nlmeans / hqdn3d.
    """
    sigma = TIER_SIGMA.get(tier, 3.0)
    if sigma <= 0:
        return []
    if preset == "slow":
        return [f"bm3d=sigma={sigma}:block=8:bstep=4"]           # best, slowest
    if preset == "med":
        s = max(1, int(round(sigma)))
        return [f"nlmeans=s={s}:p=7:r=11"]                       # balanced
    if preset == "fast":
        s = max(1, int(round(sigma / 2)))
        return [f"nlmeans=s={s}:p=5:r=9"]                        # quick
    # very_fast (batch): only bother on genuinely noisy footage, use cheap hqdn3d
    if sigma >= 5:
        return [f"hqdn3d={sigma}:{sigma}:{sigma * 1.5}:{sigma * 1.5}"]
    return []


def _sharpen_filters(level: int) -> list:
    s = SHARPEN_CAS.get(_clamp(level), 0.5)
    return [f"cas={s}"] if s > 0 else []


def build_chain(denoise_preset: str, enhance_level: int, target: int,
                is_portrait: bool, do_scale: bool, user_filters=None, *,
                tier: int = 3, do_deband=None,
                target_w: int = None, target_h: int = None) -> str:
    """Assemble the single-pass, all-CPU filtergraph.

    Positional args are kept compatible with older callers (calibration uses the
    5-arg form). The keyword args drive the tier-aware pipeline:
      tier        1-5 quality tier (selects deblock/deband/denoise strength)
      do_deband   override the per-tier deband decision
      target_w/h  explicit output dimensions (preferred over -2 autoscale)

    Order: deblock -> denoise -> deband -> upscale (zscale/lanczos) -> sharpen(CAS)
    """
    if do_deband is None:
        do_deband = DEBAND_TIERS.get(tier, False)

    filters = ["format=yuv420p"]
    filters += DEBLOCK.get(tier, [])
    filters += _denoise_filters(denoise_preset, tier)
    if user_filters:
        filters += list(user_filters)

    if do_deband:
        filters.append("gradfun=1.2:16")

    if do_scale:
        if target_w and target_h:
            filters.append(
                f"zscale=w={target_w}:h={target_h}:filter=lanczos:dither=error_diffusion")
        else:
            filters.append(
                f"zscale=w={target}:h=-2:filter=lanczos:dither=error_diffusion"
                if is_portrait else
                f"zscale=w=-2:h={target}:filter=lanczos:dither=error_diffusion")

    filters += _sharpen_filters(enhance_level)
    filters.append("format=yuv420p")
    return ",".join(filters)
