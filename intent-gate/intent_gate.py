"""
M1 - Intent gate.

The whole project rests on one question this answers:

    Can we tell "I am summoning the system" apart from "I am just working"?

Everything else (wake word, menu bar app, scroll, swipe) is easy. This is not.
Existing gesture apps fire on a hand POSE, which is why they misfire constantly -
working hands make poses all day. This gate instead requires four weak signals at
once, and the strong one is STILLNESS, because working hands are never still.

    STILL   hand holds position for 800ms      <- the real discriminator
    PALM    palm faces the camera
    CENTER  hand is in the middle of the frame
    SIZE    hand is deliberately presented, not incidentally in shot

All four, simultaneously, for 800ms -> ARMED.

Two modes:
  FIELD (f)  Work normally. DO NOT try to trigger it. Counts FALSE activations.
             This is the acceptance test: <= 1 false arm per 20 minutes.
  ARM   (a)  Deliberately arm it 20 times. Measures success rate and speed.
             Target: >= 90% first-try success at 1-1.5m.

Controls
  f / a   switch mode          c   flip palm-direction sign (see PALM readout)
  [ / ]   stillness tolerance  - / =  size band
  r       reset counters       q   quit and print report
"""

import cv2
import json
import math
import sys
import time
from collections import deque
from datetime import datetime

try:
    import mediapipe as mp
except ImportError:
    sys.exit("mediapipe missing. Run: pip install -r requirements.txt")


# ---------------------------------------------------------------- tunables

CAM_INDEX = 0
CAM_W, CAM_H = 1280, 720

STILL_MS = 800          # how long every condition must hold before arming
STILL_TOL = 0.25        # max drift as a fraction of hand size (scale invariant)
CENTER_X = (0.20, 0.80) # allowed hand-centre position, fraction of frame
CENTER_Y = (0.12, 0.82)
SIZE_BAND = (0.035, 0.30)   # hand scale as fraction of frame height
PALM_MIN = 0.15         # how squarely the palm must face the camera

ARMED_HOLD_S = 5.0      # stay armed this long after arming
REARM_GAP_S = 1.0       # hand must fail the gate this long before it can re-arm
ARM_TRIALS = 20         # arm-mode trial count
ARM_TIMEOUT_S = 10.0

WRIST, INDEX_MCP, MIDDLE_MCP, PINKY_MCP = 0, 5, 9, 17

GREEN, RED, AMBER, WHITE = (80, 230, 80), (70, 70, 235), (60, 190, 250), (240, 240, 240)


def draw_text(img, text, org, scale=0.7, color=WHITE, thick=2):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 3, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


class Gate:
    """The four-condition intent gate."""

    def __init__(self):
        self.history = deque()      # (t, cx, cy, scale) in normalised frame coords
        self.palm_sign = 1.0
        self.still_tol = STILL_TOL
        self.size_band = list(SIZE_BAND)
        self.last_fail_t = time.time()
        self.conditions = {}
        self.hold_progress = 0.0

    # -- geometry -------------------------------------------------------

    @staticmethod
    def _palm_normal_z(world):
        """Z of the palm normal. Sign tells us which way the palm points."""
        def v(a, b):
            return (world[a].x - world[b].x, world[a].y - world[b].y, world[a].z - world[b].z)
        ax, ay, az = v(INDEX_MCP, WRIST)
        bx, by, bz = v(PINKY_MCP, WRIST)
        nx, ny, nz = (ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx)
        mag = math.sqrt(nx * nx + ny * ny + nz * nz) or 1e-6
        return nz / mag

    # -- evaluation -----------------------------------------------------

    def update(self, lm, world, now, aspect):
        """Returns (all_conditions_met, ready_to_arm)."""
        cx = (lm[WRIST].x + lm[MIDDLE_MCP].x) / 2
        cy = (lm[WRIST].y + lm[MIDDLE_MCP].y) / 2
        scale = math.hypot((lm[WRIST].x - lm[MIDDLE_MCP].x) * aspect,
                           lm[WRIST].y - lm[MIDDLE_MCP].y)

        self.history.append((now, cx, cy, scale))
        while self.history and now - self.history[0][0] > STILL_MS / 1000:
            self.history.popleft()

        # SIZE - deliberately presented toward the camera
        size_ok = self.size_band[0] <= scale <= self.size_band[1]

        # CENTER - work happens at the edges of frame, summoning happens in the middle
        center_ok = (CENTER_X[0] <= cx <= CENTER_X[1] and CENTER_Y[0] <= cy <= CENTER_Y[1])

        # PALM - working hands point down or sideways, not at the camera
        nz = self._palm_normal_z(world) * self.palm_sign
        palm_ok = nz > PALM_MIN

        # STILL - the discriminator. Drift measured relative to hand size.
        drift = 0.0
        window_full = False
        if len(self.history) >= 4:
            span = self.history[-1][0] - self.history[0][0]
            window_full = span >= (STILL_MS / 1000) * 0.9
            mx = sum(h[1] for h in self.history) / len(self.history)
            my = sum(h[2] for h in self.history) / len(self.history)
            ms = sum(h[3] for h in self.history) / len(self.history) or 1e-6
            drift = max(math.hypot((h[1] - mx) * aspect, h[2] - my) for h in self.history) / ms
        still_ok = window_full and drift <= self.still_tol

        self.conditions = {
            "STILL":  (still_ok,  f"{drift:.2f} / {self.still_tol:.2f}"),
            "PALM":   (palm_ok,   f"{nz:+.2f} / {PALM_MIN:.2f}"),
            "CENTER": (center_ok, f"{cx:.2f},{cy:.2f}"),
            "SIZE":   (size_ok,   f"{scale:.3f} / {self.size_band[0]:.3f}-{self.size_band[1]:.3f}"),
        }

        instant_ok = palm_ok and center_ok and size_ok
        if not instant_ok:
            self.history.clear()
            self.last_fail_t = now
            self.hold_progress = 0.0
            return False, False

        if self.history:
            self.hold_progress = min(1.0, (now - self.history[0][0]) / (STILL_MS / 1000))

        all_ok = instant_ok and still_ok
        ready = all_ok and (now - self.last_fail_t) >= REARM_GAP_S
        return all_ok, ready

    def hand_lost(self, now):
        self.history.clear()
        self.last_fail_t = now
        self.hold_progress = 0.0
        self.conditions = {}


class IntentGateTest:
    def __init__(self):
        self.cap = cv2.VideoCapture(CAM_INDEX)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
        if not self.cap.isOpened():
            sys.exit("Camera would not open. Grant camera access in "
                     "System Settings > Privacy & Security > Camera.")

        self.hands = mp.solutions.hands.Hands(
            max_num_hands=1, model_complexity=1,
            min_detection_confidence=0.6, min_tracking_confidence=0.5)

        self.gate = Gate()
        self.mode = "FIELD"
        self.armed_until = 0.0
        self.reset()

        # arm-mode state
        self.trial_start = None
        self.trial_times = []
        self.trial_misses = 0

    def reset(self):
        self.session_start = time.time()
        self.arm_events = []          # timestamps of every arm
        self.trial_times = []
        self.trial_misses = 0
        self.trial_start = None

    # -- main -----------------------------------------------------------

    def run(self):
        print(__doc__)
        print(f"Mode: {self.mode}\n")

        while True:
            ok, frame = self.cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            aspect = w / h
            now = time.time()

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            res = self.hands.process(rgb)

            armed_now = False
            if res.multi_hand_landmarks and res.multi_hand_world_landmarks:
                lm = res.multi_hand_landmarks[0].landmark
                world = res.multi_hand_world_landmarks[0].landmark
                _, ready = self.gate.update(lm, world, now, aspect)
                if ready and now > self.armed_until:
                    self.armed_until = now + ARMED_HOLD_S
                    self.arm_events.append(now)
                    self.gate.last_fail_t = now
                    armed_now = True
                cx, cy = int(lm[MIDDLE_MCP].x * w), int(lm[MIDDLE_MCP].y * h)
                cv2.circle(frame, (cx, cy), 10, AMBER, 2)
            else:
                self.gate.hand_lost(now)

            is_armed = now < self.armed_until
            self.draw(frame, now, is_armed, w, h)

            if self.mode == "ARM":
                self.tick_arm_mode(now, armed_now)

            cv2.imshow("M1 - intent gate", frame)
            k = cv2.waitKey(1) & 0xFF
            if k == ord("q"):
                break
            elif k == ord("f"):
                self.mode = "FIELD"; self.reset()
            elif k == ord("a"):
                self.mode = "ARM"; self.reset(); self.trial_start = time.time()
            elif k == ord("c"):
                self.gate.palm_sign *= -1
            elif k == ord("r"):
                self.reset()
            elif k == ord("["):
                self.gate.still_tol = max(0.05, self.gate.still_tol - 0.05)
            elif k == ord("]"):
                self.gate.still_tol = min(1.5, self.gate.still_tol + 0.05)
            elif k == ord("-"):
                self.gate.size_band[0] = max(0.005, self.gate.size_band[0] - 0.005)
            elif k == ord("="):
                self.gate.size_band[1] = min(0.8, self.gate.size_band[1] + 0.02)

        self.cap.release()
        cv2.destroyAllWindows()
        self.report()

    # -- arm-test mode --------------------------------------------------

    def tick_arm_mode(self, now, armed_now):
        if len(self.trial_times) + self.trial_misses >= ARM_TRIALS:
            return
        if self.trial_start is None:
            self.trial_start = now
            return
        if armed_now:
            self.trial_times.append(now - self.trial_start)
            self.trial_start = None
        elif now - self.trial_start > ARM_TIMEOUT_S:
            self.trial_misses += 1
            self.trial_start = None

    # -- drawing --------------------------------------------------------

    def draw(self, frame, now, is_armed, w, h):
        panel = frame.copy()
        cv2.rectangle(panel, (0, 0), (w, 150), (25, 25, 25), -1)
        cv2.rectangle(panel, (0, h - 190), (430, h), (25, 25, 25), -1)
        cv2.addWeighted(panel, 0.68, frame, 0.32, 0, frame)

        # big state banner
        if is_armed:
            cv2.rectangle(frame, (0, 0), (w, 150), GREEN, 8)
            draw_text(frame, "ARMED", (30, 100), 2.6, GREEN, 5)
            draw_text(frame, f"{self.armed_until - now:.1f}s", (w - 200, 100), 1.4, GREEN, 3)
        else:
            draw_text(frame, "idle", (30, 100), 2.6, (120, 120, 120), 5)
            if self.gate.hold_progress > 0:
                bw = int((w - 60) * self.gate.hold_progress)
                cv2.rectangle(frame, (30, 120), (30 + bw, 138), AMBER, -1)

        # condition readout - this is what makes it tunable
        y = h - 155
        for name in ("STILL", "PALM", "CENTER", "SIZE"):
            ok, val = self.gate.conditions.get(name, (False, "-"))
            draw_text(frame, f"{'OK ' if ok else '.. '} {name:<7}{val}",
                      (20, y), 0.62, GREEN if ok else RED, 2)
            y += 34

        elapsed = now - self.session_start
        mins = elapsed / 60

        if self.mode == "FIELD":
            n = len(self.arm_events)
            rate = n / mins * 20 if mins > 0.3 else 0.0
            colour = GREEN if rate <= 1.0 else RED
            draw_text(frame, "FIELD TEST  - work normally, do NOT try to trigger",
                      (w - 700, 40), 0.66, WHITE, 2)
            draw_text(frame, f"false arms: {n}   elapsed {int(elapsed//60):02d}:{int(elapsed%60):02d}",
                      (w - 700, 75), 0.7, WHITE, 2)
            draw_text(frame, f"rate: {rate:.2f} per 20min   (target <= 1.0)",
                      (w - 700, 110), 0.75, colour, 2)
        else:
            done = len(self.trial_times) + self.trial_misses
            pct = 100 * len(self.trial_times) / done if done else 0
            draw_text(frame, f"ARM TEST  trial {min(done + 1, ARM_TRIALS)}/{ARM_TRIALS}",
                      (w - 700, 40), 0.66, WHITE, 2)
            draw_text(frame, f"success {len(self.trial_times)}/{done}  ({pct:.0f}%)",
                      (w - 700, 75), 0.7, GREEN if pct >= 90 else RED, 2)
            if self.trial_times:
                draw_text(frame, f"mean {sum(self.trial_times)/len(self.trial_times):.2f}s",
                          (w - 700, 110), 0.7, WHITE, 2)

        draw_text(frame, "[f]ield [a]rm  [c]palm-flip  [ ] still-tol  -/= size  [r]eset [q]uit",
                  (20, h - 12), 0.52, (190, 190, 190), 1)

    # -- report ---------------------------------------------------------

    def report(self):
        elapsed = time.time() - self.session_start
        mins = elapsed / 60
        n = len(self.arm_events)
        rate = n / mins * 20 if mins > 0 else 0

        print("\n" + "=" * 60)
        print("  M1 INTENT GATE - SESSION REPORT")
        print("=" * 60)
        print(f"  mode:      {self.mode}")
        print(f"  duration:  {elapsed/60:.1f} min")
        print(f"  stillness tolerance: {self.gate.still_tol:.2f}"
              f"   size band: {self.gate.size_band[0]:.3f}-{self.gate.size_band[1]:.3f}")

        if self.mode == "FIELD":
            print(f"\n  arm events:   {n}")
            print(f"  rate:         {rate:.2f} per 20 min")
            verdict = rate <= 1.0 and mins >= 15
            print(f"  -> {'PASS' if verdict else 'FAIL' if mins >= 15 else 'TOO SHORT (run 20 min)'}"
                  f"   (target <= 1.00 per 20 min)")
        else:
            done = len(self.trial_times) + self.trial_misses
            pct = 100 * len(self.trial_times) / done if done else 0
            print(f"\n  trials:       {done}")
            print(f"  success:      {len(self.trial_times)} ({pct:.0f}%)")
            if self.trial_times:
                ts = sorted(self.trial_times)
                print(f"  time to arm:  mean {sum(ts)/len(ts):.2f}s   median {ts[len(ts)//2]:.2f}s")
            print(f"  -> {'PASS' if pct >= 90 and done >= 10 else 'FAIL'}   (target >= 90%)")

        data = {
            "mode": self.mode,
            "minutes": round(mins, 2),
            "arm_events": n,
            "false_arms_per_20min": round(rate, 2),
            "arm_trials": len(self.trial_times) + self.trial_misses,
            "arm_successes": len(self.trial_times),
            "arm_times": [round(t, 2) for t in self.trial_times],
            "still_tol": self.gate.still_tol,
            "size_band": self.gate.size_band,
            "palm_sign": self.gate.palm_sign,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        out = f"gate_{self.mode.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(out, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\n  saved to {out}\n")


if __name__ == "__main__":
    IntentGateTest().run()
