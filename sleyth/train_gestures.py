"""
Teach Sleyth YOUR hand - about 3 minutes, once.

Sleyth's built-in pose rules are geometry written by hand ("a finger counts
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
import sleyth as sl                                           # noqa: E402

SECONDS = 6.0
TARGET_PER_POSE = 130

#          key      anim     title                     serif hint
PROMPTS = [
    ("point", "point", "One finger",
     "rotate and tilt it, move near and far"),
    ("two", "two", "Two fingers",
     "keep them together, vary the angle"),
    ("palm", "palm", "Open palm",
     "fingers spread - tilt it, turn it, near and far"),
    ("fist", "fist", "Closed fist",
     "it does nothing - taught so it never misfires"),
    ("other", "free", "Everything else",
     "be messy on purpose: this teaches it to stay quiet"),
]


def scrim(frame, y0, y1, strength=0.72):
    band = frame.copy()
    cv2.rectangle(band, (0, y0), (frame.shape[1], y1), (0, 0, 0), -1)
    cv2.addWeighted(band, strength, frame, 1 - strength, 0, frame)


def header(frame, idx, title, hint, now):
    h, w = frame.shape[:2]
    scrim(frame, 0, 176)
    sl.draw_tracked(frame, f"TEACH IT YOUR HAND   {idx + 1} / {len(PROMPTS)}",
                    (40, 52), 0.5, sl.GREY, 1, tracking=10, halo=True)
    sl.draw_serif(frame, title, (40, 106), 1.1, sl.PAPER, 2, halo=True)
    sl.draw_serif(frame, hint, (40, 148), 0.6, sl.SILVER, 1, halo=True)
    # the pose, performed by the schematic hand on its own chip
    ax = w - 190
    sl.rounded_rect(frame, (ax, 22), (ax + 150, 172), 12, sl.RAISED, -1)
    sl.rounded_rect(frame, (ax, 22), (ax + 150, 172), 12, sl.HAIR, 1)
    return ax


def main():
    cam = sl.LatestFrameCamera(sl.CAM_INDEX, sl.CAM_W, sl.CAM_H)
    if not cam.isOpened():
        sys.exit("Camera would not open.")
    engine = sl.HandEngine()
    aspect = sl.CAM_W / sl.CAM_H

    cv2.namedWindow("Sleyth - training", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Sleyth - training", 960, 540)

    X, y = [], []
    print(__doc__)

    for idx, (label, anim, title, hint) in enumerate(PROMPTS):
        # ---- get ready ----
        ready_until = time.time() + 3.0
        while time.time() < ready_until:
            ok, frame = cam.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            now = time.time()
            ax = header(frame, idx, title, hint, now)
            sl.draw_gesture_anim(frame, ax + 15, 32, 130, anim, now)
            left = ready_until - now
            rr = int(28)
            cv2.ellipse(frame, (64, h - 64), (rr, rr), -90, 0,
                        int(360 * (1 - left / 3.0)), sl.PAPER, 3, cv2.LINE_AA)
            sl.draw_text(frame, f"{left:.0f}", (56, h - 56), 0.7, sl.PAPER, 2)
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
            seen = r is not None
            if seen:
                lms = r[0]
                f = sl.pose_features(lms, aspect)
                if f is not None:
                    X.append(f)
                    y.append(idx)
                    got += 1
                sl.draw_hand(frame, lms, None, None, w, h)
            ax = header(frame, idx, title, hint, now)
            sl.draw_gesture_anim(frame, ax + 15, 32, 130, anim, now)
            scrim(frame, h - 96, h)
            frac = 1.0 - max(0.0, (t_end - now) / SECONDS)
            cv2.line(frame, (40, h - 56), (w - 40, h - 56), sl.HAIR, 3,
                     cv2.LINE_AA)
            cv2.line(frame, (40, h - 56),
                     (40 + int((w - 80) * frac), h - 56), sl.PAPER, 3,
                     cv2.LINE_AA)
            cv2.circle(frame, (46, h - 26), 5,
                       sl.PAPER if seen else sl.HAIR, -1, cv2.LINE_AA)
            cv2.putText(frame, f"{got} samples" if seen
                        else "hold your hand up, well lit",
                        (60, h - 21), sl.FONT, 0.5,
                        sl.PAPER if seen else sl.SILVER, 1, cv2.LINE_AA)
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
