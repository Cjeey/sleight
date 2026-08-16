"""
Air keyboard viability test.

Answers one question: can you type on a virtual keyboard using only a webcam?

Runs three phases and prints hard numbers:
  1. STEADINESS  - can you hold your fingertip on a spot, or does it drift?
  2. TARGETS     - can you hit a specific key on demand?
  3. PHRASE      - how fast and accurate is real typing?

Press methods (switch live with keys 1/2/3):
  pinch  - thumb and index touch          (most reliable, Vision Pro style)
  dwell  - hover over a key for 600ms     (slow but forgiving)
  push   - poke forward toward the camera (what a real keyboard feels like)

Controls:  n = next phase   r = restart phase   1/2/3 = press method   q = quit
"""

import cv2
import json
import math
import time
import sys
from collections import deque
from datetime import datetime

try:
    import mediapipe as mp
except ImportError:
    sys.exit("mediapipe not installed. Run: pip install -r requirements.txt")


# ---------------------------------------------------------------- config

CAM_INDEX = 0
CAM_W, CAM_H = 1280, 720

# Keyboard occupies this fraction of the frame.
KB_X0, KB_X1 = 0.10, 0.90
KB_Y0, KB_Y1 = 0.34, 0.92

STEADY_SECONDS = 10.0      # phase 1 duration
STEADY_SETTLE = 2.0        # ignore the first N seconds while you get in position
TARGET_TRIALS = 15         # phase 2 number of keys to hit
TARGET_TIMEOUT = 8.0       # give up on a target after this long
PHRASE = "the quick brown fox"

DWELL_MS = 600
PINCH_ON, PINCH_OFF = 0.38, 0.50     # normalised by hand size, with hysteresis
PUSH_ON, PUSH_OFF = -0.055, -0.025   # mediapipe z delta from a slow baseline

ROWS = [
    "1234567890",
    "QWERTYUIOP",
    "ASDFGHJKL",
    "ZXCVBNM",
]
SPACE_ROW_H = 1.0

# Landmark indices
WRIST, THUMB_TIP, INDEX_TIP, MIDDLE_MCP = 0, 4, 8, 9


# ---------------------------------------------------------------- filtering

class OneEuro:
    """One Euro filter. Kills jitter when still, stays responsive when moving.

    Included deliberately: without good filtering you'd be measuring a bad
    filter rather than measuring whether air typing works.
    """

    def __init__(self, freq=30.0, mincutoff=0.8, beta=0.010, dcutoff=1.0):
        self.freq, self.mincutoff, self.beta, self.dcutoff = freq, mincutoff, beta, dcutoff
        self.x_prev = None
        self.dx_prev = 0.0
        self.t_prev = None

    @staticmethod
    def _alpha(cutoff, freq):
        tau = 1.0 / (2 * math.pi * cutoff)
        te = 1.0 / freq
        return 1.0 / (1.0 + tau / te)

    def __call__(self, x, t):
        if self.t_prev is not None:
            dt = t - self.t_prev
            if dt > 0:
                self.freq = 1.0 / dt
        self.t_prev = t

        if self.x_prev is None:
            self.x_prev = x
            return x

        dx = (x - self.x_prev) * self.freq
        a_d = self._alpha(self.dcutoff, self.freq)
        dx_hat = a_d * dx + (1 - a_d) * self.dx_prev
        self.dx_prev = dx_hat

        cutoff = self.mincutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, self.freq)
        x_hat = a * x + (1 - a) * self.x_prev
        self.x_prev = x_hat
        return x_hat


# ---------------------------------------------------------------- keyboard

class Key:
    def __init__(self, label, x, y, w, h):
        self.label, self.x, self.y, self.w, self.h = label, x, y, w, h

    def contains(self, px, py):
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    @property
    def center(self):
        return self.x + self.w / 2, self.y + self.h / 2


def build_keyboard(frame_w, frame_h):
    x0, x1 = int(KB_X0 * frame_w), int(KB_X1 * frame_w)
    y0, y1 = int(KB_Y0 * frame_h), int(KB_Y1 * frame_h)
    region_w, region_h = x1 - x0, y1 - y0

    n_rows = len(ROWS) + SPACE_ROW_H
    key_h = region_h / n_rows
    key_w = region_w / max(len(r) for r in ROWS)

    keys = []
    for r, row in enumerate(ROWS):
        row_w = key_w * len(row)
        # last letter row also carries backspace
        extra = key_w * 1.6 if r == len(ROWS) - 1 else 0
        offset = x0 + (region_w - row_w - extra) / 2
        for c, ch in enumerate(row):
            keys.append(Key(ch, offset + c * key_w, y0 + r * key_h, key_w, key_h))
        if extra:
            keys.append(Key("<BK", offset + row_w, y0 + r * key_h, extra, key_h))

    space_w = key_w * 5
    keys.append(Key("SPACE", x0 + (region_w - space_w) / 2,
                    y0 + len(ROWS) * key_h, space_w, key_h * SPACE_ROW_H))

    return keys, key_w, key_h


def key_at(keys, px, py):
    for k in keys:
        if k.contains(px, py):
            return k
    return None


# ---------------------------------------------------------------- helpers

def levenshtein(a, b):
    if not a:
        return len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def draw_text(img, text, org, scale=0.7, color=(255, 255, 255), thick=2):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 3, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


# ---------------------------------------------------------------- press detection

class PressDetector:
    """Turns hand landmarks into discrete press events."""

    def __init__(self, method="pinch"):
        self.method = method
        self.down = False
        self.dwell_key = None
        self.dwell_start = 0.0
        self.dwell_consumed = False
        self.z_baseline = None

    def set_method(self, method):
        if method != self.method:
            self.method = method
            self.down = False
            self.dwell_key = None
            self.dwell_consumed = False
            self.z_baseline = None

    def update(self, lm, hovered_key, now):
        """Returns (pressed_now, progress) where progress is 0..1 for dwell UI."""
        if self.method == "pinch":
            return self._pinch(lm), 0.0
        if self.method == "push":
            return self._push(lm), 0.0
        return self._dwell(hovered_key, now)

    def _hand_scale(self, lm):
        dx = lm[WRIST].x - lm[MIDDLE_MCP].x
        dy = lm[WRIST].y - lm[MIDDLE_MCP].y
        return max(math.hypot(dx, dy), 1e-6)

    def _pinch(self, lm):
        dx = lm[THUMB_TIP].x - lm[INDEX_TIP].x
        dy = lm[THUMB_TIP].y - lm[INDEX_TIP].y
        ratio = math.hypot(dx, dy) / self._hand_scale(lm)
        if not self.down and ratio < PINCH_ON:
            self.down = True
            return True
        if self.down and ratio > PINCH_OFF:
            self.down = False
        return False

    def _push(self, lm):
        z = lm[INDEX_TIP].z          # negative = toward camera
        if self.z_baseline is None:
            self.z_baseline = z
        # slow baseline so a sustained lean doesn't count as a press
        self.z_baseline = 0.97 * self.z_baseline + 0.03 * z
        delta = z - self.z_baseline
        if not self.down and delta < PUSH_ON:
            self.down = True
            return True
        if self.down and delta > PUSH_OFF:
            self.down = False
        return False

    def _dwell(self, hovered_key, now):
        if hovered_key is None:
            self.dwell_key = None
            self.dwell_consumed = False
            return False, 0.0
        if hovered_key is not self.dwell_key:
            self.dwell_key = hovered_key
            self.dwell_start = now
            self.dwell_consumed = False
            return False, 0.0
        elapsed = (now - self.dwell_start) * 1000
        if elapsed >= DWELL_MS:
            if not self.dwell_consumed:
                self.dwell_consumed = True
                return True, 1.0
            return False, 1.0
        return False, elapsed / DWELL_MS


# ---------------------------------------------------------------- main test

class AirKeyTest:
    def __init__(self):
        self.cap = cv2.VideoCapture(CAM_INDEX)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
        if not self.cap.isOpened():
            sys.exit("Could not open the camera. Check macOS camera permission "
                     "for your terminal app in System Settings > Privacy & Security > Camera.")

        self.hands = mp.solutions.hands.Hands(
            max_num_hands=1,
            model_complexity=1,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )
        self.fx = OneEuro()
        self.fy = OneEuro()
        self.detector = PressDetector("pinch")

        self.phase = 0                # 0 steady, 1 targets, 2 phrase, 3 done
        self.results = {}
        self.reset_phase()

        self.flash_key = None
        self.flash_until = 0.0

    # -- phase lifecycle ------------------------------------------------

    def reset_phase(self):
        self.phase_start = None       # set on first frame with a hand
        self.samples = []             # phase 1
        self.trials = []              # phase 2
        self.target_key = None
        self.target_start = None
        self.typed = ""               # phase 3
        self.phrase_start = None

    def next_phase(self):
        self.phase += 1
        self.reset_phase()

    # -- main loop ------------------------------------------------------

    def run(self):
        print(__doc__)
        print(f"Press method: {self.detector.method}\n")

        while True:
            ok, frame = self.cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            keys, key_w, key_h = build_keyboard(w, h)
            now = time.time()

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            res = self.hands.process(rgb)

            cursor = None
            lm = None
            if res.multi_hand_landmarks:
                lm = res.multi_hand_landmarks[0].landmark
                raw_x, raw_y = lm[INDEX_TIP].x * w, lm[INDEX_TIP].y * h
                cursor = (self.fx(raw_x, now), self.fy(raw_y, now))

            hovered = key_at(keys, *cursor) if cursor else None

            pressed, dwell_prog = (False, 0.0)
            if lm is not None:
                pressed, dwell_prog = self.detector.update(lm, hovered, now)

            self.draw_keyboard(frame, keys, hovered, dwell_prog)

            if self.phase == 0:
                self.phase_steady(frame, cursor, now, key_w, w, h)
            elif self.phase == 1:
                self.phase_targets(frame, keys, cursor, hovered, pressed, now, key_w)
            elif self.phase == 2:
                self.phase_phrase(frame, hovered, pressed, now)
            else:
                self.draw_done(frame)

            if cursor:
                cv2.circle(frame, (int(cursor[0]), int(cursor[1])), 12, (0, 255, 255), -1)
                cv2.circle(frame, (int(cursor[0]), int(cursor[1])), 14, (0, 0, 0), 2)
            else:
                draw_text(frame, "no hand detected", (20, h - 20), 0.8, (0, 165, 255))

            draw_text(frame, f"method: {self.detector.method}   [1]pinch [2]dwell [3]push   "
                             f"[n]ext [r]estart [q]uit", (20, h - 55), 0.6, (200, 200, 200), 1)

            if self.flash_key and now < self.flash_until:
                k = self.flash_key
                cv2.rectangle(frame, (int(k.x), int(k.y)),
                              (int(k.x + k.w), int(k.y + k.h)), (0, 255, 0), -1)
                draw_text(frame, k.label, (int(k.x + 8), int(k.y + k.h - 12)), 0.9, (0, 0, 0))

            cv2.imshow("Air keyboard test", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("n"):
                self.finish_phase()
                self.next_phase()
            elif key == ord("r"):
                self.reset_phase()
            elif key == ord("1"):
                self.detector.set_method("pinch")
            elif key == ord("2"):
                self.detector.set_method("dwell")
            elif key == ord("3"):
                self.detector.set_method("push")

            if self.phase > 2:
                # let the user read the done screen, then quit on any key
                pass

        self.cap.release()
        cv2.destroyAllWindows()
        self.report()

    # -- drawing --------------------------------------------------------

    def draw_keyboard(self, frame, keys, hovered, dwell_prog):
        overlay = frame.copy()
        for k in keys:
            x0, y0 = int(k.x), int(k.y)
            x1, y1 = int(k.x + k.w), int(k.y + k.h)
            if k is hovered:
                cv2.rectangle(overlay, (x0, y0), (x1, y1), (80, 160, 255), -1)
            else:
                cv2.rectangle(overlay, (x0, y0), (x1, y1), (60, 60, 60), -1)
            cv2.rectangle(overlay, (x0, y0), (x1, y1), (140, 140, 140), 1)
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

        for k in keys:
            scale = 0.55 if len(k.label) > 1 else 0.7
            draw_text(frame, k.label,
                      (int(k.x + 8), int(k.y + k.h - 10)), scale,
                      (255, 255, 255), 1)

        # dwell progress bar on the hovered key
        if hovered is not None and 0.0 < dwell_prog < 1.0:
            x0, y1 = int(hovered.x), int(hovered.y + hovered.h)
            cv2.rectangle(frame, (x0, y1 - 6),
                          (x0 + int(hovered.w * dwell_prog), y1),
                          (0, 255, 0), -1)

    # -- phase 1: steadiness -------------------------------------------

    def phase_steady(self, frame, cursor, now, key_w, w, h):
        cx, cy = int(w * 0.5), int((KB_Y0 + KB_Y1) / 2 * h)
        cv2.drawMarker(frame, (cx, cy), (0, 0, 255), cv2.MARKER_CROSS, 40, 3)
        cv2.circle(frame, (cx, cy), 6, (0, 0, 255), -1)

        if cursor is None:
            draw_text(frame, "PHASE 1/3  STEADINESS", (20, 40), 0.9)
            draw_text(frame, "Show one hand. Put your index fingertip on the red cross.", (20, 75), 0.7)
            return

        if self.phase_start is None:
            self.phase_start = now

        elapsed = now - self.phase_start
        draw_text(frame, "PHASE 1/3  STEADINESS", (20, 40), 0.9)
        draw_text(frame, "Hold your fingertip on the cross. Do not move.", (20, 75), 0.7)
        draw_text(frame, f"{max(0, STEADY_SECONDS - elapsed):4.1f}s", (20, 115), 1.0, (0, 255, 255))

        if elapsed > STEADY_SETTLE:
            self.samples.append((cursor[0] - cx, cursor[1] - cy))

        if elapsed >= STEADY_SECONDS:
            self.results["key_width_px"] = key_w
            self.finish_phase()
            self.next_phase()

    # -- phase 2: targets ----------------------------------------------

    def phase_targets(self, frame, keys, cursor, hovered, pressed, now, key_w):
        import random

        letter_keys = [k for k in keys if len(k.label) == 1]

        if self.target_key is None:
            if len(self.trials) >= TARGET_TRIALS:
                self.finish_phase()
                self.next_phase()
                return
            self.target_key = random.choice(letter_keys)
            self.target_start = now

        t = self.target_key
        cv2.rectangle(frame, (int(t.x), int(t.y)),
                      (int(t.x + t.w), int(t.y + t.h)), (0, 200, 255), 4)

        draw_text(frame, f"PHASE 2/3  TARGETS   {len(self.trials)}/{TARGET_TRIALS}", (20, 40), 0.9)
        draw_text(frame, f"Press the highlighted key:  {t.label}", (20, 75), 0.8, (0, 200, 255))

        timed_out = (now - self.target_start) > TARGET_TIMEOUT

        if pressed or timed_out:
            dist = None
            if cursor:
                cxk, cyk = t.center
                dist = math.hypot(cursor[0] - cxk, cursor[1] - cyk)
            self.trials.append({
                "target": t.label,
                "pressed": hovered.label if (hovered and pressed) else None,
                "hit": bool(pressed and hovered and hovered.label == t.label),
                "seconds": round(now - self.target_start, 3),
                "miss_distance_px": round(dist, 1) if dist is not None else None,
                "timed_out": bool(timed_out and not pressed),
            })
            if pressed and hovered:
                self.flash_key = hovered
                self.flash_until = now + 0.12
            self.target_key = None

    # -- phase 3: phrase -----------------------------------------------

    def phase_phrase(self, frame, hovered, pressed, now):
        draw_text(frame, "PHASE 3/3  TYPE THE PHRASE", (20, 40), 0.9)
        draw_text(frame, PHRASE.upper(), (20, 78), 0.9, (0, 200, 255))
        draw_text(frame, self.typed or "_", (20, 118), 0.9, (0, 255, 0))

        if pressed and hovered:
            if self.phrase_start is None:
                self.phrase_start = now
            if hovered.label == "<BK":
                self.typed = self.typed[:-1]
            elif hovered.label == "SPACE":
                self.typed += " "
            else:
                self.typed += hovered.label.lower()
            self.flash_key = hovered
            self.flash_until = now + 0.12

            if len(self.typed) >= len(PHRASE):
                self.finish_phase()
                self.next_phase()

    def draw_done(self, frame):
        draw_text(frame, "DONE - press q to see the report", (20, 40), 0.9, (0, 255, 0))

    # -- results --------------------------------------------------------

    def finish_phase(self):
        if self.phase == 0 and self.samples:
            n = len(self.samples)
            rms = math.sqrt(sum(x * x + y * y for x, y in self.samples) / n)
            mx = max(math.hypot(x, y) for x, y in self.samples)
            self.results["steadiness"] = {
                "samples": n,
                "rms_drift_px": round(rms, 1),
                "max_drift_px": round(mx, 1),
            }
        elif self.phase == 1 and self.trials:
            hits = sum(1 for t in self.trials if t["hit"])
            times = [t["seconds"] for t in self.trials if t["hit"]]
            self.results["targets"] = {
                "trials": len(self.trials),
                "hits": hits,
                "accuracy_pct": round(100 * hits / len(self.trials), 1),
                "mean_seconds_per_hit": round(sum(times) / len(times), 2) if times else None,
                "timeouts": sum(1 for t in self.trials if t["timed_out"]),
                "detail": self.trials,
            }
        elif self.phase == 2 and self.typed:
            elapsed = max(time.time() - (self.phrase_start or time.time()), 1e-6)
            minutes = elapsed / 60
            wpm = (len(self.typed) / 5) / minutes
            dist = levenshtein(self.typed.strip(), PHRASE)
            self.results["phrase"] = {
                "target": PHRASE,
                "typed": self.typed,
                "seconds": round(elapsed, 1),
                "wpm": round(wpm, 1),
                "char_errors": dist,
                "error_rate_pct": round(100 * dist / len(PHRASE), 1),
            }

    def report(self):
        self.finish_phase()
        self.results["method"] = self.detector.method
        self.results["timestamp"] = datetime.now().isoformat(timespec="seconds")

        kw = self.results.get("key_width_px")
        print("\n" + "=" * 62)
        print("  AIR KEYBOARD TEST RESULTS")
        print("=" * 62)
        print(f"  press method: {self.results['method']}")
        if kw:
            print(f"  key width:    {kw:.0f} px")

        verdicts = []

        s = self.results.get("steadiness")
        if s:
            kwid = s["rms_drift_px"] / kw if kw else None
            print(f"\n  1. STEADINESS")
            print(f"     drift (rms):  {s['rms_drift_px']:.1f} px", end="")
            if kwid is not None:
                print(f"   = {kwid:.2f} key widths")
            else:
                print()
            print(f"     drift (max):  {s['max_drift_px']:.1f} px")
            if kwid is not None:
                ok = kwid < 0.40
                verdicts.append(ok)
                print(f"     -> {'PASS' if ok else 'FAIL'}  (need < 0.40 key widths)")

        t = self.results.get("targets")
        if t:
            print(f"\n  2. TARGETS")
            print(f"     accuracy:     {t['accuracy_pct']}%  ({t['hits']}/{t['trials']})")
            print(f"     timeouts:     {t['timeouts']}")
            if t["mean_seconds_per_hit"]:
                print(f"     time per key: {t['mean_seconds_per_hit']}s")
            ok = t["accuracy_pct"] >= 90
            verdicts.append(ok)
            print(f"     -> {'PASS' if ok else 'FAIL'}  (need >= 90%)")

        p = self.results.get("phrase")
        if p:
            print(f"\n  3. PHRASE")
            print(f"     typed:        {p['typed']!r}")
            print(f"     target:       {p['target']!r}")
            print(f"     speed:        {p['wpm']} wpm   ({p['seconds']}s)")
            print(f"     errors:       {p['char_errors']} chars ({p['error_rate_pct']}%)")
            ok = p["wpm"] >= 20 and p["error_rate_pct"] <= 10
            verdicts.append(ok)
            print(f"     -> {'PASS' if ok else 'FAIL'}  (need >= 20 wpm and <= 10% errors)")

        print("\n" + "-" * 62)
        if verdicts and all(verdicts):
            print("  VERDICT: viable. Worth building further.")
        elif verdicts:
            print("  VERDICT: not viable with this method. Try another press method,")
            print("           or drop the keyboard and use voice for text.")
        else:
            print("  VERDICT: no phases completed.")
        print("-" * 62)
        print("  Reference: a phone keyboard is ~35 wpm. Voice dictation is ~150 wpm.")

        out = f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(out, "w") as f:
            json.dump(self.results, f, indent=2)
        print(f"\n  Full data saved to {out}\n")


if __name__ == "__main__":
    AirKeyTest().run()
