"""
Record a tutorial gesture with YOUR hand - once per gesture.

The tutorial normally teaches with a drawn schematic hand. This replaces it
with the real thing: your hand's landmarks, captured for ~2 seconds and
replayed forever as the monochrome skeleton. A few KB per gesture, no video.

    ./run.sh --record click        # one of: palm point click two hold flick
    ./run.sh --record all          # walk through every gesture in order

Perform the gesture ONCE, naturally, during the recording window. You get an
instant replay - keep it or redo it on the spot.
"""

import os
import sys
import time

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sleyth as sl                                           # noqa: E402

KINDS = ["palm", "point", "click", "two", "hold", "flick"]
RECORD_S = 2.2                     # capture window; resampled to 1.8s loop

TITLES = {
    "palm": "Open palm, hold it still",
    "point": "Point, sweep gently side to side",
    "click": "Tap thumb and index together",
    "two": "Two fingers, wave up and down",
    "hold": "Pinch thumb + pinky, move, release",
    "flick": "Open palm, flick to the side",
}


def scrim(frame, y0, y1, strength=0.72):
    band = frame.copy()
    cv2.rectangle(band, (0, y0), (frame.shape[1], y1), (0, 0, 0), -1)
    cv2.addWeighted(band, strength, frame, 1 - strength, 0, frame)


def record_one(cam, engine, kind):
    """countdown -> capture -> instant replay -> keep / redo / quit"""
    aspect = sl.CAM_W / sl.CAM_H
    while True:
        # ---- countdown ----
        until = time.time() + 3.0
        while time.time() < until:
            ok, frame = cam.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            now = time.time()
            scrim(frame, 0, 150)
            sl.draw_tracked(frame, f"RECORD   {kind.upper()}", (40, 52), 0.6,
                            sl.PAPER, 1, tracking=10, halo=True)
            sl.draw_serif(frame, TITLES[kind], (40, 100), 0.75, sl.PAPER, 1,
                          halo=True)
            sl.draw_serif(frame, f"performing in {until - now:.0f}...",
                          (40, 136), 0.55, sl.SILVER, 1, halo=True)
            cv2.imshow("Sleyth - record", frame)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                return False

        # ---- capture ----
        frames, t_end = [], time.time() + RECORD_S
        while time.time() < t_end:
            ok, frame = cam.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            now = time.time()
            r = engine.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), now)
            if r is not None:
                lms = r[0]
                frames.append([(l.x, l.y) for l in lms])
                sl.draw_hand(frame, lms, None, None, w, h)
            scrim(frame, 0, 96)
            frac = 1.0 - (t_end - now) / RECORD_S
            cv2.line(frame, (40, 64), (w - 40, 64), sl.HAIR, 3, cv2.LINE_AA)
            cv2.line(frame, (40, 64), (40 + int((w - 80) * frac), 64),
                     sl.PAPER, 3, cv2.LINE_AA)
            sl.draw_tracked(frame, "GO", (40, 44), 0.7, sl.PAPER, 1,
                            tracking=14, halo=True)
            cv2.imshow("Sleyth - record", frame)
            cv2.waitKey(1)

        if len(frames) < 12:
            print(f"  only {len(frames)} tracked frames - hand not seen well,"
                  " trying again")
            continue

        clip = sl.resample_clip(sl.normalize_clip(frames))

        # ---- instant replay: keep it only if it looks right ----
        choice = None
        t0 = time.time()
        while choice is None:
            ok, frame = cam.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            scrim(frame, 0, h)
            box = 260
            bx, by = (w - box) // 2, (h - box) // 2 - 20
            sl.rounded_rect(frame, (bx, by), (bx + box, by + box), 16,
                            sl.RAISED, -1)
            sl.rounded_rect(frame, (bx, by), (bx + box, by + box), 16,
                            sl.HAIR, 1)
            sl.draw_clip(frame, bx + 20, by + 20, box - 40, clip,
                         time.time() - t0)
            sl.draw_serif(frame, "this is how the tutorial will show it",
                          (bx - 40, by - 24), 0.6, sl.PAPER, 1, halo=True)
            sl.draw_tracked(frame, "Y KEEP     R REDO     Q QUIT",
                            (bx - 10, by + box + 40), 0.5, sl.SILVER, 1,
                            tracking=8, halo=True)
            cv2.imshow("Sleyth - record", frame)
            k = cv2.waitKey(1) & 0xFF
            if k in (ord("y"), 13):
                choice = "keep"
            elif k == ord("r"):
                choice = "redo"
            elif k == ord("q"):
                return False
        if choice == "redo":
            continue
        path = sl.save_clip(kind, clip)
        print(f"  saved {kind}: {len(clip)} frames -> {path}")
        return True


def main():
    kinds = KINDS if (len(sys.argv) < 2 or sys.argv[1] == "all") \
        else [sys.argv[1]]
    for k in kinds:
        if k not in KINDS:
            sys.exit(f"unknown gesture '{k}' - one of: {' '.join(KINDS)}")

    cam = sl.LatestFrameCamera(sl.CAM_INDEX, sl.CAM_W, sl.CAM_H)
    if not cam.isOpened():
        sys.exit("Camera would not open.")
    engine = sl.HandEngine()
    cv2.namedWindow("Sleyth - record", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Sleyth - record", 960, 540)

    print(__doc__)
    for k in kinds:
        if not record_one(cam, engine, k):
            print("cancelled")
            break
    cam.release()
    cv2.destroyAllWindows()
    print("\nDone. The tutorial now replays your real hand. "
          "Delete files in gestures/ to go back to the drawn ones.")


if __name__ == "__main__":
    main()
