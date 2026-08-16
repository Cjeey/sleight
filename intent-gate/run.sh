#!/bin/bash
# Reuses the venv from the keyboard test if it exists, otherwise builds one.
set -e
cd "$(dirname "$0")"

SHARED="../keyboard-test/.venv"

if [ ! -d .venv ]; then
  if [ -d "$SHARED" ]; then
    echo "Using the venv from keyboard-test."
    exec "$SHARED/bin/python" intent_gate.py
  fi
  echo "First run - setting up (a minute or two)..."
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
  echo "Done."
fi

exec ./.venv/bin/python intent_gate.py
