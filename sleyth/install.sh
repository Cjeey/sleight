#!/bin/bash
# Install the freshly built Sleyth into /Applications and launch it.
#
# Why not just run dist/Sleyth.app? Because rebuilding replaces the files
# underneath a running copy, and a PyInstaller app loads its code lazily -
# so the running one freezes mid-session. Installing to /Applications keeps
# the copy you USE separate from the copy I rebuild.
set -e
cd "$(dirname "$0")"

SRC="dist/Sleyth.app"
DST="/Applications/Sleyth.app"

[ -d "$SRC" ] || { echo "No build found. Run: pyinstaller Sleyth.spec"; exit 1; }

# a running instance would keep the old code and hold the camera
if pgrep -f "Sleyth.app/Contents/MacOS/Sleyth" >/dev/null 2>&1; then
  echo "Quitting the running Sleyth..."
  pkill -f "Sleyth.app/Contents/MacOS/Sleyth" || true
  sleep 1
fi

echo "Installing to $DST ..."
rm -rf "$DST"
ditto "$SRC" "$DST"

# strip the quarantine flag: without it macOS runs the app from a random
# read-only mount and no permission you grant ever sticks
xattr -dr com.apple.quarantine "$DST" 2>/dev/null || true

echo "Version: $(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$DST/Contents/Info.plist" 2>/dev/null)"
open "$DST"
echo "Launched. Grant Accessibility from the menu-bar icon if it says DRY."
