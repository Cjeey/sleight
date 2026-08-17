#!/bin/bash
# Sleyth v1 launcher. Reuses the keyboard-test venv, tops up its deps.
set -e
cd "$(dirname "$0")"

VENV="../keyboard-test/.venv"
if [ ! -d "$VENV" ]; then
  echo "Setting up (a minute or two)..."
  python3 -m venv .venv
  VENV=".venv"
  "$VENV/bin/pip" install --quiet --upgrade pip
fi
"$VENV/bin/pip" install --quiet -r requirements.txt

MODEL="hand_landmarker.task"
if [ ! -f "$MODEL" ]; then
  echo "Downloading the modern hand-tracking model (7.7MB, one-time)..."
  curl -fsSL -o "$MODEL" "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task" \
    || echo "Download failed - Sleyth will use the built-in tracker."
fi

if [ "$1" = "--train" ]; then
  exec "$VENV/bin/python" train_gestures.py
fi

exec "$VENV/bin/python" sleyth.py "$@"
