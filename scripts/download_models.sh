#!/usr/bin/env bash
# Download the OpenCV Zoo MediaPipe person-detection ONNX (12 MB, Apache-2.0).
# The file is NOT committed (see .gitignore); CI/judges run this once.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="$ROOT/models/person_detection_mediapipe_2023mar.onnx"
URL="https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/person_detection_mediapipe/person_detection_mediapipe_2023mar.onnx"

if [[ -s "$MODEL" ]]; then
  echo "already present: $MODEL ($(du -h "$MODEL" | cut -f1))"
  exit 0
fi

mkdir -p "$ROOT/models"
curl -sL "$URL" -o "$MODEL"
SIZE=$(wc -c < "$MODEL")
if (( SIZE < 1000000 )); then
  echo "error: downloaded file too small ($SIZE bytes) — LFS pointer?" >&2
  rm -f "$MODEL"
  exit 1
fi
echo "downloaded: $MODEL ($(du -h "$MODEL" | cut -f1))"
