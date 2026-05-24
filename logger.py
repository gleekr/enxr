import os
import glob
import traceback
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")


def _log_path() -> str:
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, datetime.now().strftime("%Y-%m-%d") + ".log")


def log_error(context: str, error: Exception, extra: str = None) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"[{timestamp}] ERROR [{context}] {error}"]
    if extra:
        lines.append(f"  {extra}")
    tb = traceback.format_exc()
    if tb and tb.strip() != "NoneType: None":
        for line in tb.strip().splitlines():
            lines.append(f"  {line}")
    entry = "\n".join(lines) + "\n"
    with open(_log_path(), "a") as f:
        f.write(entry)
    print(f"[log] {lines[0]}")


def cleanup_tmp(directory: str) -> int:
    """Delete all tmp_*.mp4 files in directory. Returns count removed."""
    removed = 0
    for f in glob.glob(os.path.join(directory, "tmp_*.mp4")):
        try:
            os.remove(f)
            removed += 1
        except OSError:
            pass
    if removed:
        print(f"[log] cleaned {removed} tmp file(s) from {directory}")
    return removed
