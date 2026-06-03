#!/bin/bash
# Shortcuts for enxr test suite

usage() {
    cat <<EOF
Usage: ./run_tests.sh [command]

Commands:
  quick       Run comprehensive test (quick mode, 2 presets per clip)
  full        Run comprehensive test (full, all 5 presets)
  pipeline    Run pipeline validation test (15 encodes, consistency checks)
  batch VID   Run test_batch.py on a video file
  help        Show this message

Examples:
  ./run_tests.sh quick
  ./run_tests.sh batch ~/Videos/test.mp4
EOF
}

cd "$(dirname "$0")" || exit 1

case "$1" in
    quick)
        echo "Running comprehensive test (quick mode)..."
        python test_comprehensive.py --quick
        ;;
    full)
        echo "Running comprehensive test (full)..."
        python test_comprehensive.py
        ;;
    pipeline)
        echo "Running pipeline validation test..."
        python pipeline_test.py
        ;;
    batch)
        if [ -z "$2" ]; then
            echo "Error: no video file specified"
            echo "Usage: ./run_tests.sh batch <video_file>"
            exit 1
        fi
        echo "Running test_batch on $2..."
        python test_batch.py "$2"
        ;;
    help|--help|-h|"")
        usage
        ;;
    *)
        echo "Unknown command: $1"
        usage
        exit 1
        ;;
esac
