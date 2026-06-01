#!/usr/bin/env python3
"""
test_batch.py - Batch test filter combinations on a single video.

Usage:
  python3 test_batch.py <video_file> [output_dir]

Encodes the video with multiple restore/enhance combinations.
Outputs all results to output_dir with a manifest file.
"""

import sys, os, json, time, subprocess
from pathlib import Path

from ffmpeg import enhance, _get_dims, get_ceiling, get_duration
from config import UPRES_DEST, build_chain


# Test matrix: restore levels x enhance levels
# Pruned to avoid combinatorial explosion
TEST_COMBOS = [
    (0, 0),  # baseline: no processing
    (1, 0), (0, 1),  # single-axis
    (1, 1), (1, 2), (2, 1), (2, 2),  # light combos
    (2, 3), (3, 2), (3, 3),  # moderate
    (4, 2), (3, 4),  # heavier
]


def capture_frame(video_file: str, output_png: str, timestamp: float = 2.0) -> bool:
    """Extract a frame from video at timestamp and save as PNG."""
    try:
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(timestamp), "-i", video_file,
            "-vframes", "1", "-q:v", "2", output_png
        ], capture_output=True, timeout=10, check=True)
        return True
    except Exception:
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 test_batch.py <video_file> [output_dir]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "test_results"

    if not os.path.isfile(input_file):
        print(f"Error: file not found: {input_file}")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    # Get source info
    try:
        w, h, is_portrait, short_side, codec = _get_dims(input_file)
    except Exception as e:
        print(f"Error analyzing file: {e}")
        sys.exit(1)

    ceiling = get_ceiling(short_side)
    target_res = ceiling if ceiling else short_side

    print(f"Source: {w}x{h} ({short_side}p short side)")
    print(f"Target: {target_res}p")
    print(f"Testing {len(TEST_COMBOS)} combinations...\n")

    results = []
    base_name = Path(input_file).stem

    for i, (restore, enhance_lvl) in enumerate(TEST_COMBOS, 1):
        output_file = os.path.join(output_dir, f"{base_name}_{restore}-{enhance_lvl}.mp4")

        print(f"[{i}/{len(TEST_COMBOS)}] restore={restore} enhance={enhance_lvl}...", end=" ", flush=True)
        t0 = time.time()

        try:
            actual_output = enhance(input_file, restore_level=restore, enhance_level=enhance_lvl,
                                   target_res=target_res, out_dir=output_dir)
            elapsed = time.time() - t0

            # Capture frame for quick comparison
            frame_png = os.path.join(output_dir, f"{base_name}_{restore}-{enhance_lvl}.png")
            capture_frame(actual_output, frame_png, timestamp=2.0)

            results.append({
                "restore": restore,
                "enhance": enhance_lvl,
                "file": os.path.basename(actual_output),
                "screenshot": os.path.basename(frame_png),
                "time": round(elapsed, 1),
            })
            print(f"{elapsed:.1f}s")
        except Exception as e:
            print(f"FAILED: {e}")

    # Write manifest
    manifest = {
        "source": input_file,
        "source_info": {"width": w, "height": h, "short_side": short_side, "codec": codec},
        "target_res": target_res,
        "combos_tested": len(TEST_COMBOS),
        "results": results,
    }

    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nDone. Results in: {output_dir}/")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
