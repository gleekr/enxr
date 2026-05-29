import os

# ── Enhancement defaults ──────────────────────────────────────────────────────
AUTO_DEFAULT_LEVEL = 2

# ── Paths ─────────────────────────────────────────────────────────────────────
DEFAULT_DEST = os.path.expanduser("~/Documents/vids/og")         # single download (non-batch)
UPRES_DEST   = os.path.expanduser("~/Documents/vids/hd")         # single enhanced output
BATCH_OG     = os.path.expanduser("~/Documents/vids/batch/og")   # batch originals root (per-channel inside)
BATCH_HD     = os.path.expanduser("~/Documents/vids/batch/hd")   # batch enhanced root (per-channel inside)

# ── Upscale ladder ────────────────────────────────────────────────────────────
UPSCALE_CEILING = 1440
UPSCALE_STEPS   = [720, 1080, 1440]

# ── Source -> ceiling mapping ─────────────────────────────────────────────────
# Used by ffmpeg.get_ceiling(short_side).
# Keys are thresholds checked descending; first match wins.
#   1440p+  -> 0     (source lock, no upscale)
#   720-1439 -> 1440
#   0-719   -> 1080
SOURCE_CEILING = {
    1440: 0,      # at or above 1440p -> source lock
    720:  1440,   # 720p to 1439p     -> cap at 1440
    0:    1080,   # below 720p        -> cap at 1080
}

# ── Download workers ──────────────────────────────────────────────────────────
BATCH_WORKERS          = 2
BATCH_FRAGMENT_THREADS = 4

# ── YouTube player clients ────────────────────────────────────────────────────
# ios/tv return pre-signed stream URLs, so the apple-webkit-jsi challenge solver
# never launches WebKit -- WebKit navigating youtube.com is what opens the
# YouTube app on iOS via universal links. web is the fallback ONLY: it forces
# the solver and may briefly open the app, so it is used only if ios/tv yield
# nothing. Keep web out of the primary list.
YT_PLAYER_CLIENT          = ["ios", "tv"]
YT_PLAYER_CLIENT_FALLBACK = ["web"]
