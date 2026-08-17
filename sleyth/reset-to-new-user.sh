#!/bin/bash
# Wipe every trace of Sleyth from this Mac, so the next launch is exactly
# what a brand-new user gets: permission prompts, palm calibration, the
# tutorial, and the generic hand rules.
#
# Your trained model and recorded gestures are BACKED UP first, not deleted -
# retraining takes 3 minutes and there is no reason to lose them by accident.
#
#   ./reset-to-new-user.sh            # keep the installed app, wipe its state
#   ./reset-to-new-user.sh --all      # also delete /Applications/Sleyth.app
set -e
cd "$(dirname "$0")"

SUPPORT="$HOME/Library/Application Support/Sleyth"
STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP="$HOME/Desktop/sleyth-backup-$STAMP"

echo "Quitting Sleyth..."
pkill -f "Sleyth.app/Contents/MacOS/Sleyth" 2>/dev/null || true
sleep 1

if [ -d "$SUPPORT" ]; then
  mkdir -p "$BACKUP"
  # the model and clips are the only things that took real effort to make
  [ -f "$SUPPORT/gesture_model.npz" ] && cp "$SUPPORT/gesture_model.npz" "$BACKUP/" 2>/dev/null || true
  [ -d "$SUPPORT/gestures" ] && cp -R "$SUPPORT/gestures" "$BACKUP/" 2>/dev/null || true
  [ -f "$SUPPORT/sleyth_config.json" ] && cp "$SUPPORT/sleyth_config.json" "$BACKUP/" 2>/dev/null || true
  echo "Backed up your model/clips/config to:"
  echo "  $BACKUP"
  rm -rf "$SUPPORT"
  echo "Cleared $SUPPORT"
else
  echo "No saved state to clear."
fi

# forget the permission decisions, so macOS asks like it is the first time
echo "Forgetting Camera + Accessibility grants..."
tccutil reset Camera com.sleyth.app >/dev/null 2>&1 || true
tccutil reset Accessibility com.sleyth.app >/dev/null 2>&1 || true

if [ "$1" = "--all" ]; then
  rm -rf /Applications/Sleyth.app
  echo "Removed /Applications/Sleyth.app"
fi

echo
echo "Done - this Mac now looks like it has never seen Sleyth."
echo
echo "To test the real first-run experience:"
echo "  ./install.sh"
echo
echo "You should get, in order:"
echo "  1. camera permission prompt      (widget says ALLOW CAMERA meanwhile)"
echo "  2. palm calibration              (palm, then back of hand)"
echo "  3. the tutorial                  (6 gestures, gated on real reps)"
echo "  4. DRY until you grant Accessibility from the menu-bar icon"
echo
echo "Your old model is in $BACKUP if you want it back:"
echo "  cp \"$BACKUP/gesture_model.npz\" \"$SUPPORT/\""
