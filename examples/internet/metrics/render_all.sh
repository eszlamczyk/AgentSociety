#!/bin/bash

SCRIPT_DIR="$(dirname "$0")"
OUTPUT_DIR="${SCRIPT_DIR}/output"

for dir in "$OUTPUT_DIR"/*/; do
    [ -f "${dir}steps.csv" ] || continue
    echo "Rendering: $dir"
    python "${SCRIPT_DIR}/render.py" "$dir"
done
