import os

AUTO_DEFAULT_LEVEL = 2
DEFAULT_DEST       = os.path.expanduser("~/Documents/enxr/noenx")
UPRES_DEST         = os.path.expanduser("~/Documents/enxr/upres")
BATCH_DEST         = os.path.expanduser("~/Documents/enxr/batches")
UPSCALE_CEILING    = 1440
UPSCALE_STEPS      = [720, 1080, 1440]

SOURCE_CEILING = {1440: 0, 1080: 1440, 720: 1440, 480: 1080, 360: 720, 0: 720}
CEILING_MAX_PASSES = {0: 4, 1440: 3, 1080: 2, 720: 2}

BATCH_WORKERS          = 2  # parallel video downloads (safe for 4-6GB iPhone)
BATCH_FRAGMENT_THREADS = 4  # yt-dlp fragment threads per worker (2x4=8 total)
