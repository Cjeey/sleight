"""
Teach Sleyth YOUR hand - about 3 minutes, once.

Sleyth's built-in pose rules are geometry I wrote by hand ("a finger counts
as extended if its tip is farther from the wrist than its middle joint").
Those rules are generic. Your hand is not.

This records your own hand doing each pose, from several angles and
distances, and trains a small classifier on it. Nothing leaves your machine,
no dataset licences, no TensorFlow - just your hand.

    ./run.sh --train        (or: python train_gestures.py)

For each pose you get ~6 seconds. SLOWLY rotate and tilt your hand and move it
nearer/farther the whole time - the variety is what makes it robust.
"""

import math
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sleyth as sl                                          # noqa: E402

SECONDS = 6.0
TARGET_PER_POSE = 130

PROMPTS = [
    ("point", "ONE finger up (the CURSOR pose)",
     "rotate + tilt your hand, move near and far"),
    ("two", "TWO fingers up (the SCROLL pose)",
     "keep both fingers together, vary the angle"),
    ("palm", "OPEN PALM, all fingers spread (SUMMON / BACK)",
     "tilt it, turn it slightly, near and far"),
    ("fist", "CLOSED FIST (does nothing - taught so it never misfires)",
     "rotate it, thumb in and out"),
    ("other", "EVERYTHING ELSE - relaxed, half-curled, reaching, waving",
     "be messy on purpose: this is what teaches it to stay quiet"),
]


def main():
    cam = sl.LatestFrameCamera(sl.CAM_INDEX, sl.CAM_W, sl.CAM_H)
    if not cam.isOpened():
        sys.exit("Camera would not open.")
    engine = sl.HandEngine()
    drawer = mp_draw = __import__("mediapipe").solutions.drawing_utils
    styles = __import__("mediapipe").solutions.drawing_styles
    aspect = sl.CAM_W / sl.CAM_H

    cv2.namedWindow("Sleyth - training", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Sleyth - training", 960, 540)

    X, y = [], []
    print(__doc__)

    for idx, (label, title, hint) in enumerate(PROMPTS):
        # ---- get ready ----
        ready_until = time.time() + 3.0
        while time.time() < ready_until:
            ok, frame = cam.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            sl.draw_text(frame, f"{idx + 1}/{len(PROMPTS)}  {title}",
                         (30, 60), 0.85, sl.AMBER, 2)
            sl.draw_text(frame, hint, (30, 100), 0.6, sl.WHITE, 2)
            sl.draw_text(frame, f"starting in {ready_until - time.time():.0f}",
                         (30, h - 40), 1.0, sl.GREEN, 3)
            cv2.imshow("Sleyth - training", frame)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                cam.release(); cv2.destroyAllWindows(); sys.exit("cancelled")

        # ---- record ----
        got = 0
        t_end = time.time() + SECONDS
        while time.time() < t_end and got < TARGET_PER_POSE:
            ok, frame = cam.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            now = time.time()
            r = engine.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), now)
            if r is not None:
                lms = r[0]
                f = sl.pose_features(lms, aspect)
                if f is not None:
                    X.append(f)
                    y.append(idx)
                    got += 1
                sl.draw_hand(frame, lms, drawer, styles, w, h)
            frac = 1.0 - max(0.0, (t_end - now) / SECONDS)
            cv2.rectangle(frame, (30, h - 60),
                          (30 + int((w - 60) * frac), h - 34), sl.GREEN, -1)
            sl.draw_text(frame, f"RECORDING  {title}", (30, 60), 0.8, sl.GREEN, 2)
            sl.draw_text(frame, hint, (30, 100), 0.6, sl.WHITE, 2)
            sl.draw_text(frame, f"{got} samples", (30, h - 74), 0.6, sl.WHITE, 2)
            cv2.imshow("Sleyth - training", frame)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                cam.release(); cv2.destroyAllWindows(); sys.exit("cancelled")
        print(f"  {label}: {got} samples")
        if got < 25:
            print(f"  !! too few samples for '{label}' - rerun with your hand "
                  f"clearly in frame")

    cam.release()
    cv2.destroyAllWindows()

    if len(X) < 100:
        sys.exit("Not enough data captured - nothing saved.")

    X = np.asarray(X, dtype=np.float32)
    y = np.asarray(y, dtype=np.int32)

    # honest self-check: hold out 20% and score it
    rng = np.random.default_rng(0)
    order = rng.permutation(len(X))
    X, y = X[order], y[order]
    cut = int(len(X) * 0.8)
    Xtr, ytr, Xte, yte = X[:cut], y[:cut], X[cut:], y[cut:]

    correct = 0
    for f, truth in zip(Xte, yte):
        d = np.linalg.norm(Xtr - f, axis=1)
        idx = np.argpartition(d, sl.KNN_K - 1)[:sl.KNN_K]
        votes = {}
        for i in idx:
            votes[int(ytr[i])] = votes.get(int(ytr[i]), 0.0) + 1.0 / (1e-3 + d[i])
        if max(votes.items(), key=lambda kv: kv[1])[0] == int(truth):
            correct += 1
    acc = 100.0 * correct / max(len(yte), 1)

    np.savez(sl.GESTURE_MODEL, X=X, y=y,
             labels=np.array([p[0] for p in PROMPTS]))
    print("\n" + "=" * 56)
    print(f"  trained on {len(X)} samples of YOUR hand")
    print(f"  held-out accuracy: {acc:.1f}%")
    print(f"  saved: {os.path.basename(sl.GESTURE_MODEL)}")
    if acc < 90:
        print("  (under 90% - rerun and vary your angles more)")
    print("=" * 56)
    print("\nRun ./run.sh - it will say 'poses: LEARNED from your hand'.")
    print("Delete gesture_model.npz any time to go back to the built-in rules.")


if __name__ == "__main__":
    main()
