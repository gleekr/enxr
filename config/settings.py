import os

# ── Enhancement defaults ──────────────────────────────────────────────────────
AUTO_DEFAULT_LEVEL = 2

# Strength decay per pass index (index 0 = pass 1, full strength)
PASS_STRENGTH_DECAY = [1.0, 0.6, 0.35, 0.2]

# ── Paths ─────────────────────────────────────────────────────────────────────
DEFAULT_DEST = os.path.expanduser("~/Documents/outputs/original")   # single-file download dest
UPRES_DEST   = os.path.expanduser("~/Documents/outputs/enhanced")   # single-file enhanced output
BATCH_DEST   = os.path.expanduser("~/Documents/outputs/batches")    # batch channel download root

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

# ── Max passes per ceiling ────────────────────────────────────────────────────
CEILING_MAX_PASSES = {
    0:    4,   # source lock (refinement passes)
    1440: 3,   # e.g. 720->1080->1440 + 1 refine
    1080: 2,
    720:  2,
}

# ── Download workers ──────────────────────────────────────────────────────────
BATCH_WORKERS          = 2
BATCH_FRAGMENT_THREADS = 4
