#!/bin/bash
# Sets up a local venv on first run, then launches the test.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "First run - setting up (this takes a minute or two)..."
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
  echo "Done."
fi

exec ./.venv/bin/python airkey_test.py
