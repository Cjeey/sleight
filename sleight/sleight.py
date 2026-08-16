"""
Sleight v7.8 - trackpad in the air.

Gestures (after summoning):

    POINT   1 finger (index)           move the cursor
    CLICK   thumb + INDEX touch         click fires THE MOMENT they meet -
                                        no release needed, no latency
    HOLD    thumb + PINKY touch         mouse HOLD while touched = drag;
                                        release to drop. No timers anywhere
    TWO     2 fingers up/down           scroll - page follows your hand;
                                        curl to pause, flick to coast
    PALM    whole hand flick left/right browser Back / Forward, like a
                                        trackpad swipe (right = back)

Summon: open palm toward the camera, hold still ~0.8s.
Stopping: just lower your hand - no gesture for 6s and it disarms itself.

Views:  a frosted glass WIDGET floating at the bottom of the screen - no
        window, no title bar, transparent background. It stays a small nub
        until you raise a hand, then it opens: state word on the left, your
        hand on its own chip beside it. DRAG it anywhere - it remembers.
        Control it from the menu-bar icon, or the keys below when the full
        view is up (press f).
First run: interactive tutorial (safe dry-run) teaches every gesture.

Keys:  q quit   f widget/full view   p reset widget position   t tutorial
       n next tutorial step   c recalibrate palm   x mark false arm
       v flip scroll   d toggle dry-run   [ / ] stillness   r reset counters
Flags: --dry-run
"""

import argparse
import json
import math
import os
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glass                                                    # noqa: E402

try:
    import mediapipe as mp
except ImportError:
    sys.exit("mediapipe missing. Run: ./run.sh (it installs requirements)")

try:
    import Quartz
except ImportError:
    Quartz = None

try:
    from ApplicationServices import (AXIsProcessTrustedWithOptions,
                                     kAXTrustedCheckOptionPrompt)
except ImportError:
    AXIsProcessTrustedWithOptions = None
    kAXTrustedCheckOptionPrompt = None


HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "sleight_config.json")

CAM_INDEX = 0
CAM_W, CAM_H = 1280, 720
CAM_FPS = 60                   # ask for 60; the camera gives what it can

# ---- intent gate -----------------------------------------------------------
STILL_MS = 800
CENTER_X = (0.20, 0.80)
CENTER_Y = (0.10, 0.85)
PALM_MIN = 0.15
HANDEDNESS_MIN_SCORE = 0.70    # below this the chirality label is untrusted
REARM_GAP_S = 1.2

# ---- armed behaviour -------------------------------------------------------
ARMED_HOLD_S = 6.0             # idle this long -> disarms on its own
POST_ARM_GRACE_S = 0.5         # ignore flicks right after arming - the summon
                               # pose IS a palm, so its exit must stay inert
POSE_STABLE_FRAMES = 3         # a pose change must persist this many frames
POSE_LOST_GRACE_S = 0.3        # hand lost briefly (motion blur) keeps its pose

# ---- flick (directional swipe) --------------------------------------------
SWIPE_WINDOW_S = 0.35          # wider window = more frames survive fast motion
SWIPE_DISP = 0.8               # hand-widths of travel within the window
SWIPE_MIN_SAMPLES = 4
SWIPE_REFRACTORY_S = 0.7
SWIPE_REST_DISP = 0.25
SWIPE_REST_S = 0.15
SWIPE_CONSISTENCY = 0.7
SWIPE_CROSS_RATIO = 0.6        # cross-axis travel above this x primary = diagonal, reject
SWIPE_STEP_JUMP = 1.2          # single-frame step above this = tracking re-lock.
                               # a REAL flick peaks ~0.7-1.0 hw/frame - the old
                               # 0.6 cap was rejecting exactly the good flicks

# ---- scroll (position control: the page follows the hand) ------------------
SCROLL_LIFTOFF_S = 0.06        # output is delayed this long; on release the
                               # undelivered tail is discarded, so the motion
                               # of LETTING GO never scrolls
SCROLL_PX_PER_HW = 900.0       # scroll px per hand-width of vertical travel
SCROLL_DEADBAND_HW = 0.006     # per-frame travel below this = tremor, ignore
SCROLL_FRAME_MAX = 200         # px per frame cap
SCROLL_FLICK_MIN = 30.0        # exit velocity (px/frame) that starts a coast -
                               # a deliberate flick, not a casual release
SCROLL_COAST_DECAY = 0.93      # momentum decay per frame while coasting
SCROLL_TICK_S = 0.45

# ---- pointer: ABSOLUTE - the cursor is where your fingertip is -------------
# this box of the camera frame maps to the whole screen, so screen edges are
# reachable without your hand leaving the frame
# the control box is a SIZE, not a place: it re-anchors to your hand whenever
# you start pointing (cursor continues from where it already is), and pushing
# past an edge drags the box along - you can never be "outside" it
CONTROL_W, CONTROL_H = 0.40, 0.42          # box size, frame fractions
CONTROL_BOX = (0.30, 0.70, 0.28, 0.70)     # initial position only
POINTER_LOOKAHEAD_S = 0.055    # lead the cursor ahead of the hand's velocity
POINTER_LEAD_MAX = 0.08        # to cancel camera latency; capped so direction
                               # changes can't fling it
POINTER_LEAD_MIN_SPEED = 0.25  # screen-fracs/s below which lead is OFF - a
POINTER_LEAD_RAMP = 0.35       # still hand must not wiggle; ramps in smoothly
POINTER_DEADZONE = 0.009       # SOFT deadzone in screen fractions: a resting
                               # hand moves the cursor exactly 0px. Movement
                               # past it continues smoothly (no jump), so fine
                               # aiming still works - it only kills tremor
GLIDE_TAU = 0.022              # output chase - snappy, still step-free
POINTER_RENEW_FRAC = 0.004     # movement below this doesn't renew ARMED
POINTER_MIN_PX = 1.5

# Precision assist - what a real trackpad's acceleration curve buys you.
# A slow hand should cover LESS screen (fine aiming), a fast one the full
# sweep. We get it without abandoning absolute pointing: at low speed the
# mapping box creeps ALONG WITH the hand, so the hand's movement relative to
# the box - and therefore the cursor - is smaller. The box already drifts for
# edge-drag and edge-assist, so this is the same machinery, not a new mode.
PRECISION_MAX = 0.55           # at a standstill the cursor moves 45% as far
PRECISION_SPEED = 0.35         # frame-widths/s where it fades to pure 1:1

# ---- click: thumb+index pinch (the Vision Pro / Quest select gesture) ------
# hysteresis: close below ON, reopen above OFF - no flicker at the boundary
EDGE_MARGIN = 0.03             # click landmarks this close to the frame edge
                               # are HALLUCINATED by the tracker (the finger is
                               # cut off) - phantom touches must not fire
EDGE_ASSIST_PAD = 0.12         # hand near the frame border -> the mapping box
EDGE_ASSIST_RATE = 3.0         # slides along, so the cursor reaches the screen
                               # edge while the fingers stay safely in frame
PINCH_ON = 0.35                # thumb<->index tip distance, hand-width units
PINCH_RELEASE = 0.42           # separate JUST A BIT past contact = released.
                               # The refractory period handles flicker, so the
                               # release gap can be honest instead of huge
HOLD_ON = 0.45                 # pinky contact reads looser than index contact
                               # (shortest finger, noisiest tracking) - so the
                               # hold gets its own, more generous thresholds
HOLD_RELEASE = 0.52            # ...and its release sits ABOVE the noise band,
                               # so a held drag can't drop from jitter
PINCH_OFF = 0.55
PINCH_REACH_MIN = 0.85         # index tip must REACH (fist = curled ~0.5-0.7)
FIST_WRIST_MAX = 0.90
CLICK_STABLE_FRAMES = 3        # debounce for the middle-finger HOLD
CLICK_PRESS_FRAMES = 2         # index click: fires on PRESS after ~65ms
CLICK_REFRACTORY_S = 0.08      # tiny: flicker is handled by hysteresis +
                               # drop-from-rest; this only spaces the events
DOUBLE_CLICK_S = 0.80          # human tap-ease-tap rhythm is ~0.5-0.8s -
                               # be MORE generous than macOS, never less
DOUBLE_CLICK_SLOP_PX = 14
TOUCH_DROP = 0.12              # a touch = a clear DROP below that finger's own
                               # resting distance - a finger that always sits
                               # near the thumb can't fire by existing
HOLD_MARGIN = 0.15             # middle must beat index by this to mean HOLD;
                               # ties and near-ties are ALWAYS a click
PALM_FLICK_GRACE_S = 0.3       # showing the palm (to stop pointing) is inert
                               # this long - so stopping can't hit Back
CLICK_FREEZE_S = 0.18          # cursor pauses this long around the click so it
                               # lands where aimed - then tracking RESUMES
# pointing is a LATCHED mode: once you point, you stay steering - through
# finger curls, through clicks - until you deliberately show palm/two fingers
# or lower the hand. A curled finger must never end pointing by accident
INDEX_DIP = 7
PINKY_DIP = 19

WRIST, THUMB_TIP, INDEX_MCP, MIDDLE_MCP, PINKY_MCP = 0, 4, 5, 9, 17
TIPS = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}
PIPS = {"index": 6, "middle": 10, "ring": 14, "pinky": 18}

# focus-safe actions only: no space/home/end (space = default-button activator
# in dialogs - one misroute from clicking "Delete").
# back/forward = Cmd+[ / Cmd+] - real browser history, like a trackpad swipe
KEY_ACTIONS = {"left": (123, None), "right": (124, None),
               "down": (125, None), "up": (126, None),
               "pagedown": (121, None), "pageup": (116, None),
               "back": (33, "cmd"), "forward": (30, "cmd")}

SOUNDS = {"arm": "/System/Library/Sounds/Glass.aiff",
          "action": "/System/Library/Sounds/Pop.aiff",
          "click": "/System/Library/Sounds/Tink.aiff",
          "disarm": "/System/Library/Sounds/Bottle.aiff"}

# ---- monochrome design system ---------------------------------------------
# One material: light on near-black. State is carried by BRIGHTNESS, never
# by hue - the whole app lives on this six-step ramp.
INK = (8, 8, 8)              # window ground
SURFACE = (17, 17, 17)       # pill / card fill
RAISED = (31, 31, 31)        # active-row fill
HAIR = (54, 54, 54)          # hairline strokes, off states
GREY = (118, 118, 118)       # muted text
SILVER = (178, 178, 178)     # secondary text
PAPER = (246, 246, 246)      # primary text, armed / active

# Legacy names (train_gestures.py imports these) mapped onto the mono ramp.
GREEN, RED, AMBER, GRAY, WHITE = PAPER, GREY, SILVER, GREY, PAPER

FONT = cv2.FONT_HERSHEY_DUPLEX


def play(kind):
    path = SOUNDS.get(kind)
    if path and os.path.exists(path):
        subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


def draw_text(img, text, org, scale=0.6, color=WHITE, thick=2):
    cv2.putText(img, text, org, FONT, scale, (0, 0, 0),
                thick + 3, cv2.LINE_AA)
    cv2.putText(img, text, org, FONT, scale, color,
                thick, cv2.LINE_AA)


def track_w(text, scale=0.5, thick=1, tracking=7):
    """Pixel width of draw_tracked() output, for centering."""
    total = 0
    for ch in text.upper():
        (cw, _), _ = cv2.getTextSize(ch, FONT, scale, thick)
        total += cw + int(tracking * scale)
    return max(0, total - int(tracking * scale))


def draw_tracked(img, text, org, scale=0.5, color=PAPER, thick=1, tracking=7,
                 halo=False):
    """Letter-spaced capitals - the app's display voice. halo=True when the
    text sits on the CAMERA image: light type on a bright wall is invisible
    without it."""
    x, y = org
    for ch in text.upper():
        p = (int(x), int(y))
        if halo:
            cv2.putText(img, ch, p, FONT, scale, (0, 0, 0), thick + 3,
                        cv2.LINE_AA)
        cv2.putText(img, ch, p, FONT, scale, color, thick, cv2.LINE_AA)
        (cw, _), _ = cv2.getTextSize(ch, FONT, scale, thick)
        x += cw + int(tracking * scale)


SERIF = cv2.FONT_HERSHEY_TRIPLEX | cv2.FONT_ITALIC


def draw_serif(img, text, org, scale=0.6, color=PAPER, thick=1, halo=False):
    """Italic serif accent - the editorial voice (countrz-style)."""
    if halo:
        cv2.putText(img, text, org, SERIF, scale, (0, 0, 0), thick + 3,
                    cv2.LINE_AA)
    cv2.putText(img, text, org, SERIF, scale, color, thick, cv2.LINE_AA)


def serif_w(text, scale=0.6, thick=1):
    (w, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_TRIPLEX
                                | cv2.FONT_ITALIC, scale, thick)
    return w


def draw_blob(img, center, radius, energy, t, color):
    """A living blob: a closed liquid curve that breathes with hand motion.
    Still hand = a near-circle barely moving; motion makes it swell and flow.
    Deterministic in t (no randomness)."""
    cx, cy = center
    amp = 0.035 + 0.085 * energy
    r_base = radius * (1.0 + 0.25 * energy)
    pts = []
    for i in range(72):
        th = 2.0 * math.pi * i / 72
        r = r_base * (1.0
                      + amp * math.sin(2 * th + t * 1.7)
                      + amp * 0.45 * math.sin(3 * th - t * 1.1))
        pts.append((cx + r * math.cos(th), cy + r * math.sin(th)))
    cv2.fillPoly(img, [np.array(pts, dtype=np.float32).round()
                       .astype(np.int32)], color, cv2.LINE_AA)


def rounded_rect(img, p0, p1, radius, color, thick=-1):
    x0, y0 = p0
    x1, y1 = p1
    r = max(1, min(radius, (x1 - x0) // 2, (y1 - y0) // 2))
    if thick < 0:
        cv2.rectangle(img, (x0 + r, y0), (x1 - r, y1), color, -1)
        cv2.rectangle(img, (x0, y0 + r), (x1, y1 - r), color, -1)
        for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r),
                       (x0 + r, y1 - r), (x1 - r, y1 - r)):
            cv2.circle(img, (cx, cy), r, color, -1, cv2.LINE_AA)
    else:
        cv2.line(img, (x0 + r, y0), (x1 - r, y0), color, thick, cv2.LINE_AA)
        cv2.line(img, (x0 + r, y1), (x1 - r, y1), color, thick, cv2.LINE_AA)
        cv2.line(img, (x0, y0 + r), (x0, y1 - r), color, thick, cv2.LINE_AA)
        cv2.line(img, (x1, y0 + r), (x1, y1 - r), color, thick, cv2.LINE_AA)
        for cx, cy, a0 in ((x0 + r, y0 + r, 180), (x1 - r, y0 + r, 270),
                           (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90)):
            cv2.ellipse(img, (cx, cy), (r, r), a0, 0, 90, color, thick,
                        cv2.LINE_AA)


# --------------------------------------------------------------------------- config

DEFAULT_CONFIG = {
    "palm_sign": 0.0,
    "calibrated_hand": "",     # MediaPipe label seen during calibration
    "still_tol": 0.22,
    "size_band": [0.035, 0.30],
    "scroll_flip": False,
    "scroll_gain": SCROLL_PX_PER_HW,
    "cursor_deadzone": POINTER_DEADZONE,
    "swipe_left_key": "forward",   # macOS trackpad convention:
    "swipe_right_key": "back",     # swipe right = go BACK
    "tutorial_done": False,
    "panel_pos": "center",         # fallback panel dock: "center" or "right"
    "widget_xy": None,             # where you last dragged the widget to
    "precision_assist": PRECISION_MAX,   # 0 = pure 1:1, 0.55 = fine aiming
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH) as f:
            cfg.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    # a mapping outside the safe action set silently no-ops in the injector
    # while still counting swipes + playing sounds - reject it here instead
    for k in ("swipe_left_key", "swipe_right_key"):
        if cfg.get(k) not in KEY_ACTIONS:
            cfg[k] = DEFAULT_CONFIG[k]
    # migrate the old arrow-key defaults to real browser back/forward
    if cfg["swipe_left_key"] == "left" and cfg["swipe_right_key"] == "right":
        cfg["swipe_left_key"] = "forward"
        cfg["swipe_right_key"] = "back"
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def calibrate_sign(palm_mean_nz, back_mean_nz):
    if abs(palm_mean_nz - back_mean_nz) < 0.15:
        return 0.0
    return 1.0 if palm_mean_nz > back_mean_nz else -1.0


# --------------------------------------------------------------------------- smooth output

class Glide:
    """Exponential chase toward a target at whatever rate you tick it.
    Vision updates the target at ~30Hz; this runs at 100+Hz, so the cursor
    moves like a native pointer instead of stepping at camera rate."""

    def __init__(self, tau=0.04):
        self.tau = tau
        self.pos = None
        self.t = None

    def reset(self):
        self.pos = None
        self.t = None

    def tick(self, target, now):
        if target is None:
            return None
        if self.pos is None or self.t is None:
            self.pos = [target[0], target[1]]
            self.t = now
            return tuple(self.pos)
        dt = min(max(now - self.t, 0.0), 0.1)
        self.t = now
        a = 1.0 - math.exp(-dt / self.tau)
        self.pos[0] += (target[0] - self.pos[0]) * a
        self.pos[1] += (target[1] - self.pos[1]) * a
        return tuple(self.pos)


class WheelSmoother:
    """Spreads chunky 30Hz scroll bursts into a fine high-rate stream.
    Conserves every pixel - it only changes WHEN they are delivered."""

    def __init__(self, tau=0.035):
        self.tau = tau
        self.buf = 0.0
        self.res = 0.0
        self.t = None

    def add(self, px):
        self.buf += px

    def tick(self, now):
        if self.t is None:
            self.t = now
            return 0
        dt = min(max(now - self.t, 0.0), 0.1)
        self.t = now
        if self.buf == 0.0 and abs(self.res) < 1.0:
            return 0
        a = 1.0 - math.exp(-dt / self.tau)
        out_f = self.buf * a
        self.buf -= out_f
        if abs(self.buf) < 0.5:          # flush the tail instead of trickling
            out_f += self.buf
            self.buf = 0.0
        self.res += out_f
        # int() truncates toward zero, which strands the last pixel of a
        # negative burst forever - settle the account when the burst ends
        out = int(round(self.res)) if self.buf == 0.0 else int(self.res)
        self.res -= out
        return out


class LatestFrameCamera:
    """Capture thread that always exposes the NEWEST frame. cv2.VideoCapture
    keeps an internal buffer - reading it synchronously means acting on a
    hand position from ~100ms ago. This removes that lag entirely."""

    def __init__(self, index, w, h, fps=CAM_FPS):
        self.cap = cv2.VideoCapture(index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        # Ask for the fastest the webcam will give. Even when the tracker
        # cannot keep up, a faster camera means the frame it DOES grab is
        # fresher - the win is latency, not throughput.
        try:
            self.cap.set(cv2.CAP_PROP_FPS, fps)
        except cv2.error:
            pass
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except cv2.error:
            pass
        self.ok = self.cap.isOpened()
        self.lock = threading.Lock()
        self.frame = None
        self.seq = 0
        self._read_seq = 0
        self.cap_fps = 0.0             # what the camera ACTUALLY delivers
        self._fps_t = None
        self.running = self.ok
        if self.ok:
            threading.Thread(target=self._run, daemon=True).start()

    def specs(self):
        return (int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                self.cap.get(cv2.CAP_PROP_FPS))

    def _run(self):
        while self.running:
            ok, f = self.cap.read()
            if ok:
                now = time.time()
                if self._fps_t is not None:
                    dt = now - self._fps_t
                    if 0 < dt < 1:
                        self.cap_fps = (0.9 * self.cap_fps + 0.1 / dt
                                        if self.cap_fps else 1.0 / dt)
                self._fps_t = now
                with self.lock:
                    self.frame = f
                    self.seq += 1
            else:
                time.sleep(0.005)

    def latest(self):
        with self.lock:
            return self.seq, (self.frame.copy() if self.frame is not None else None)

    def read(self, timeout=1.0):
        """Blocking next-new-frame read - drop-in for calibration."""
        start = time.time()
        while time.time() - start < timeout:
            with self.lock:
                if self.seq != self._read_seq and self.frame is not None:
                    self._read_seq = self.seq
                    return True, self.frame.copy()
            time.sleep(0.003)
        return False, None

    def isOpened(self):
        return self.ok

    def release(self):
        self.running = False
        time.sleep(0.05)
        self.cap.release()


# --------------------------------------------------------------------------- filter

class OneEuro:
    def __init__(self, freq=30.0, mincutoff=1.0, beta=0.012, dcutoff=1.0):
        self.freq, self.mincutoff, self.beta, self.dcutoff = freq, mincutoff, beta, dcutoff
        self.x_prev, self.dx_prev, self.t_prev = None, 0.0, None

    @staticmethod
    def _alpha(cutoff, freq):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau * freq)

    def __call__(self, x, t):
        if self.t_prev is not None and t > self.t_prev:
            self.freq = 1.0 / (t - self.t_prev)
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
        self.x_prev = a * x + (1 - a) * self.x_prev
        return self.x_prev

    def reset(self):
        self.x_prev, self.dx_prev, self.t_prev = None, 0.0, None


# --------------------------------------------------------------------------- geometry

def _d(a, b, aspect):
    return math.hypot((a.x - b.x) * aspect, a.y - b.y)


def hand_obs(lm, world, aspect, clf=None):
    """Reduce 21 landmarks to {pose, cx, cy, scale, nz}."""
    scale = _d(lm[WRIST], lm[MIDDLE_MCP], aspect)
    if scale < 1e-6:
        return None
    wrist = lm[WRIST]
    thumb = lm[THUMB_TIP]

    ext, d_wrist_sum = {}, 0.0
    for f in TIPS:
        tip, pip = lm[TIPS[f]], lm[PIPS[f]]
        ext[f] = _d(tip, wrist, aspect) > _d(pip, wrist, aspect) * 1.15
        d_wrist_sum += _d(tip, wrist, aspect)
    n_ext = sum(ext.values())
    d_wrist = d_wrist_sum / 4 / scale

    # click signal: thumb touching ANY part of the index finger (tip, middle
    # joint, or base knuckle-side segment) - much more natural than tip-to-tip
    ti_ratio = min(_d(lm[TIPS["index"]], thumb, aspect),
                   _d(lm[INDEX_DIP], thumb, aspect),
                   _d(lm[PIPS["index"]], thumb, aspect)) / scale
    hold_ratio = min(_d(lm[TIPS["pinky"]], thumb, aspect),
                     _d(lm[PINKY_DIP], thumb, aspect),
                     _d(lm[PIPS["pinky"]], thumb, aspect)) / scale
    index_reach = _d(lm[TIPS["index"]], wrist, aspect) / scale

    # touch signals are only real when the involved landmarks are fully
    # INSIDE the frame - cut-off fingers get hallucinated positions.
    # split per gesture: a cut-off pinky must not block an index click
    def _inside(q):
        return (EDGE_MARGIN < q.x < 1.0 - EDGE_MARGIN
                and EDGE_MARGIN < q.y < 1.0 - EDGE_MARGIN)
    click_lms = (thumb, lm[TIPS["index"]], lm[INDEX_DIP], lm[PIPS["index"]])
    hold_lms = (thumb, lm[TIPS["pinky"]], lm[PINKY_DIP], lm[PIPS["pinky"]])
    click_ok = all(_inside(q) for q in click_lms)
    hold_ok = all(_inside(q) for q in hold_lms)
    all_lms = click_lms + hold_lms
    hand_min_x = min(q.x for q in all_lms)
    hand_max_x = max(q.x for q in all_lms)
    hand_min_y = min(q.y for q in all_lms)
    hand_max_y = max(q.y for q in all_lms)

    if n_ext == 4:
        pose = "palm"
    elif ext["index"] and ext["middle"] and not ext["ring"] and not ext["pinky"]:
        pose = "two"
    elif ext["index"] and not ext["middle"] and not ext["ring"] and not ext["pinky"]:
        pose = "point"
    elif n_ext == 0 and d_wrist < FIST_WRIST_MAX:
        pose = "fist"
    else:
        pose = None

    if clf is not None:
        learned = clf.predict(lm, aspect)      # your hand beats my rules
        if learned is not None:
            pose = learned

    def v(a, b):
        return (world[a].x - world[b].x, world[a].y - world[b].y,
                world[a].z - world[b].z)
    ax, ay, az = v(INDEX_MCP, WRIST)
    bx, by, bz = v(PINKY_MCP, WRIST)
    nx, ny, nz = ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx
    mag = math.sqrt(nx * nx + ny * ny + nz * nz) or 1e-6

    return {"pose": pose,
            "cx": (lm[WRIST].x + lm[MIDDLE_MCP].x) / 2,
            "cy": (lm[WRIST].y + lm[MIDDLE_MCP].y) / 2,
            # cursor anchor = a VIRTUAL fingertip: the index knuckle projected
            # up the hand's own axis by ~a finger length. It sits visually at
            # the top of the extended finger (where you aim), but is computed
            # only from bones that do not move during a pinch - so clicking
            # still cannot displace the cursor (the fix that made tabs work)
            "ix": lm[INDEX_MCP].x + (lm[MIDDLE_MCP].x - lm[WRIST].x) * 0.9,
            "iy": lm[INDEX_MCP].y + (lm[MIDDLE_MCP].y - lm[WRIST].y) * 0.9,
            "tip_x": lm[TIPS["index"]].x,
            "tip_y": lm[TIPS["index"]].y,
            "scale": scale,
            "nz": nz / mag,
            "ti_ratio": ti_ratio,
            "hold_ratio": hold_ratio,
            "click_ok": click_ok,
            "hold_ok": hold_ok,
            "touch_ok": click_ok and hold_ok,
            "hand_min_x": hand_min_x, "hand_max_x": hand_max_x,
            "hand_min_y": hand_min_y, "hand_max_y": hand_max_y,
            "index_reach": index_reach,
            "hand_label": "",      # filled by the caller from multi_handedness
            "hand_score": 1.0}


class PoseStabilizer:
    """A pose CHANGE must persist POSE_STABLE_FRAMES frames before publishing.
    Kills single-frame palm->two flickers that would anchor a phantom scroll."""

    def __init__(self):
        self.current = None
        self.candidate = None
        self.count = 0

    def reset(self):
        self.current, self.candidate, self.count = None, None, 0

    def update(self, raw_pose):
        if raw_pose is None:
            # hand visible but unclassifiable (stretched to a corner, tilted):
            # keep doing what we were doing rather than dropping the gesture
            return self.current
        if raw_pose == self.current:
            self.candidate, self.count = None, 0
            return self.current
        if raw_pose == self.candidate:
            self.count += 1
        else:
            self.candidate, self.count = raw_pose, 1
        if self.count >= POSE_STABLE_FRAMES:
            self.current = raw_pose
            self.candidate, self.count = None, 0
        return self.current


# --------------------------------------------------------------------------- learned poses

GESTURE_MODEL = os.path.join(HERE, "gesture_model.npz")
POSE_LABELS = ["point", "two", "palm", "fist", "other"]
KNN_K = 7
KNN_MAX_DIST = 1.35            # farther than this = "I don't recognise this"
KNN_MIN_VOTES = 4              # of KNN_K, else fall back to the geometry rules


def pose_features(lm, aspect):
    """21 landmarks -> a 40-float signature that is translation, scale AND
    rotation invariant, so a tilted or distant hand looks identical to a
    straight, close one. This is what the geometry rules could never do."""
    wx, wy = lm[WRIST].x, lm[WRIST].y
    ax = (lm[MIDDLE_MCP].x - wx) * aspect
    ay = lm[MIDDLE_MCP].y - wy
    scale = math.hypot(ax, ay)
    if scale < 1e-6:
        return None
    # rotate so wrist->middle-knuckle points "up"
    cos_t, sin_t = -ay / scale, -ax / scale
    out = []
    for i in range(21):
        if i == WRIST:
            continue
        px = (lm[i].x - wx) * aspect / scale
        py = (lm[i].y - wy) / scale
        out.append(px * cos_t - py * sin_t)
        out.append(px * sin_t + py * cos_t)
    return np.asarray(out, dtype=np.float32)


class GestureClassifier:
    """k-nearest-neighbour over pose_features, trained on YOUR OWN hand by
    train_gestures.py. Pure numpy - no TensorFlow, no cloud, no dataset
    licence to worry about. Falls back silently when unsure."""

    def __init__(self, path=GESTURE_MODEL):
        self.ok = False
        self.n = 0
        try:
            d = np.load(path, allow_pickle=True)
            self.X, self.y = d["X"], d["y"]
            self.labels = [str(x) for x in d["labels"]]
            self.n = len(self.X)
            self.ok = self.n >= KNN_K
        except Exception:
            pass

    def predict(self, lm, aspect):
        """Returns a pose label, or None when it is not confident."""
        if not self.ok:
            return None
        f = pose_features(lm, aspect)
        if f is None:
            return None
        d = np.linalg.norm(self.X - f, axis=1)
        idx = np.argpartition(d, KNN_K - 1)[:KNN_K]
        near = [(d[i], self.y[i]) for i in idx if d[i] <= KNN_MAX_DIST]
        if len(near) < KNN_MIN_VOTES:
            return None
        votes = {}
        for dist, lab in near:
            votes[lab] = votes.get(lab, 0.0) + 1.0 / (1e-3 + dist)
        lab, _ = max(votes.items(), key=lambda kv: kv[1])
        label = self.labels[int(lab)]
        return None if label == "other" else label


# --------------------------------------------------------------------------- gate

class Gate:
    """Summon = POSE(palm) + STILL + PALM(calibrated, chirality-aware)
    + CENTER + SIZE."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.history = deque()
        self.last_fail_t = 0.0
        self.conditions = {}
        self.hold_progress = 0.0

    def _palm_ok(self, obs):
        if self.cfg["palm_sign"] == 0.0:
            return False
        nz = obs["nz"]
        cal_hand = self.cfg.get("calibrated_hand", "")
        # Only flip for the mirror hand when the label is TRUSTWORTHY. A weak
        # or missing chirality reading must not veto a real palm: failing
        # closed here locks the user out of their own app with no way to tell
        # why (it did, once).
        if (cal_hand and obs.get("hand_label")
                and obs.get("hand_score", 1.0) >= HANDEDNESS_MIN_SCORE
                and obs["hand_label"] != cal_hand):
            nz = -nz                   # mirror hand flips the normal
        return nz * self.cfg["palm_sign"] > PALM_MIN

    def update(self, obs, now, aspect):
        self.history.append((now, obs["cx"], obs["cy"], obs["scale"]))
        while self.history and now - self.history[0][0] > STILL_MS / 1000:
            self.history.popleft()

        pose_ok = obs["pose"] == "palm"
        size_ok = self.cfg["size_band"][0] <= obs["scale"] <= self.cfg["size_band"][1]
        center_ok = (CENTER_X[0] <= obs["cx"] <= CENTER_X[1]
                     and CENTER_Y[0] <= obs["cy"] <= CENTER_Y[1])
        palm_ok = self._palm_ok(obs)

        drift, window_full = 0.0, False
        if len(self.history) >= 4:
            span = self.history[-1][0] - self.history[0][0]
            window_full = span >= (STILL_MS / 1000) * 0.9
            mx = sum(h[1] for h in self.history) / len(self.history)
            my = sum(h[2] for h in self.history) / len(self.history)
            ms = sum(h[3] for h in self.history) / len(self.history) or 1e-6
            drift = max(math.hypot((h[1] - mx) * aspect, h[2] - my)
                        for h in self.history) / ms
        still_ok = window_full and drift <= self.cfg["still_tol"]

        self.conditions = {"POSE": pose_ok, "STILL": still_ok, "PALM": palm_ok,
                           "CENTER": center_ok, "SIZE": size_ok}

        instant = pose_ok and palm_ok and center_ok and size_ok
        if not instant:
            self.history.clear()
            self.last_fail_t = now
            self.hold_progress = 0.0
            return False
        self.hold_progress = min(1.0, (now - self.history[0][0]) / (STILL_MS / 1000))
        return instant and still_ok and (now - self.last_fail_t) >= REARM_GAP_S

    def hand_lost(self, now):
        self.history.clear()
        self.last_fail_t = now
        self.hold_progress = 0.0
        self.conditions = {}


# --------------------------------------------------------------------------- gestures

class FlickDetector:
    """Directional flick for one pose along one axis. Guards: return-stroke
    suppression (survives dropouts), teleport step cap, diagonal rejection."""

    def __init__(self, pose, axis):
        self.pose, self.axis = pose, axis
        self.history = deque()          # (t, primary, cross, scale)
        self.refractory_until = 0.0
        self.require_rest = False
        self.rest_since = None
        self.last_disp = 0.0            # live progress readout for the HUD

    def reset(self):
        # deliberately KEEPS require_rest and refractory_until: a one-frame
        # tracking dropout must not disarm return-stroke suppression
        self.history.clear()
        self.rest_since = None

    def update(self, obs, now):
        if obs["pose"] != self.pose:
            self.history.clear()
            self.rest_since = None
            self.last_disp = 0.0
            return None
        primary = obs["cx"] if self.axis == "x" else obs["cy"]
        cross = obs["cy"] if self.axis == "x" else obs["cx"]
        self.history.append((now, primary, cross, obs["scale"]))
        while self.history and now - self.history[0][0] > SWIPE_WINDOW_S:
            self.history.popleft()
        if len(self.history) < SWIPE_MIN_SAMPLES:
            return None
        mean_scale = sum(h[3] for h in self.history) / len(self.history) or 1e-6

        xs = [h[1] for h in self.history]
        steps = [b - a for a, b in zip(xs, xs[1:])]
        if max(abs(s) for s in steps) / mean_scale > SWIPE_STEP_JUMP:
            last = self.history[-1]     # tracking re-lock: drop stale samples
            self.history.clear()
            self.history.append(last)
            return None

        disp = (xs[-1] - xs[0]) / mean_scale
        cross_disp = (self.history[-1][2] - self.history[0][2]) / mean_scale
        agree = sum(1 for s in steps if s * disp > 0) / len(steps)
        self.last_disp = disp

        if self.require_rest:
            if abs(disp) < SWIPE_REST_DISP:
                if self.rest_since is None:
                    self.rest_since = now
                elif now - self.rest_since >= SWIPE_REST_S:
                    self.require_rest = False
            else:
                self.rest_since = None
            return None

        if (now < self.refractory_until
                or abs(disp) < SWIPE_DISP
                or agree < SWIPE_CONSISTENCY
                or abs(cross_disp) > SWIPE_CROSS_RATIO * abs(disp)):
            return None
        self.refractory_until = now + SWIPE_REFRACTORY_S
        self.require_rest = True
        self.rest_since = None
        self.history.clear()
        return "pos" if disp > 0 else "neg"


class ScrollController:
    """Position-control scroll with a CLUTCH and momentum.

    While two fingers are up, the page follows the hand 1:1. Curling the
    fingers (any other pose) is the clutch - like lifting off a trackpad -
    so you can bring your hand back to the middle without scrolling backward.
    Exit fast and the page keeps coasting with decaying momentum, iOS-style,
    so one flick covers a long page. Returns whole pixels (0 most frames)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.fy = OneEuro(mincutoff=0.6, beta=1.5)
        self.prev_cy = None
        self.scale_ema = None
        self.pending = deque()         # (t, px) delayed by SCROLL_LIFTOFF_S
        self.residual = 0.0
        self.vel = 0.0                 # smoothed px/frame of DELIVERED scroll
        self.coast = 0.0               # momentum px/frame after release

    def hard_reset(self):
        self.fy.reset()
        self.prev_cy = None
        self.scale_ema = None
        self.pending.clear()
        self.residual = 0.0
        self.vel = 0.0
        self.coast = 0.0

    @property
    def coasting(self):
        return self.coast != 0.0

    def _deliver(self, now):
        out_f = 0.0
        while self.pending and now - self.pending[0][0] >= SCROLL_LIFTOFF_S:
            out_f += self.pending.popleft()[1]
        if out_f:
            self.vel = 0.7 * self.vel + 0.3 * out_f
        self.residual += out_f
        out = int(self.residual)
        self.residual -= out
        return out

    def update(self, obs, now):
        if obs is None or obs["pose"] != "two":
            # CLUTCH. The undelivered tail is the motion of LETTING GO -
            # it is discarded, so releasing never scrolls.
            self.fy.reset()
            self.prev_cy = None
            self.pending.clear()
            self.residual = 0.0
            if abs(self.vel) >= SCROLL_FLICK_MIN and self.coast == 0.0:
                self.coast = self.vel            # deliberate flick -> momentum
            self.vel = 0.0
            if self.coast:
                self.coast *= SCROLL_COAST_DECAY
                if abs(self.coast) < 1.0:
                    self.coast = 0.0
                    return 0
                return int(self.coast)
            return 0

        self.coast = 0.0                          # hand back on the page
        cy = self.fy(obs["cy"], now)
        self.scale_ema = (obs["scale"] if self.scale_ema is None
                          else 0.9 * self.scale_ema + 0.1 * obs["scale"])
        if self.prev_cy is None:
            self.prev_cy = cy
            return self._deliver(now)
        delta_hw = (self.prev_cy - cy) / max(self.scale_ema, 1e-6)
        self.prev_cy = cy
        if abs(delta_hw) >= SCROLL_DEADBAND_HW:
            px = delta_hw * self.cfg.get("scroll_gain", SCROLL_PX_PER_HW)
            px = math.copysign(min(abs(px), SCROLL_FRAME_MAX), px)
            if not self.cfg["scroll_flip"]:
                px = -px
            self.pending.append((now, px))
        return self._deliver(now)


class PointerController:
    """ABSOLUTE pointing with a box that follows the hand.

    The mapping box is a fixed SIZE but not a fixed PLACE:
      - when pointing starts, the box anchors itself so the hand's current
        position maps to wherever the cursor already is - no jump, and
        control is immediate from any hand position
      - pushing past a box edge DRAGS the box along, so the hand can never
        be outside it - no dead zones, no invisible rectangle to hunt for
    Returns (fx, fy) screen fractions, or None."""

    def __init__(self, cfg, aspect):
        self.cfg = cfg
        # calm at rest, fast in motion: moderate mincutoff kills hover jitter,
        # high beta catches up instantly on deliberate movement
        self.fx = OneEuro(mincutoff=0.5, beta=3.0)
        self.fy = OneEuro(mincutoff=0.5, beta=3.0)
        self.bx0, self.by0 = CONTROL_BOX[0], CONTROL_BOX[2]
        self.active = False
        self.last_out = (0.5, 0.5)     # survives reset: re-anchor continuity
        self._assist_t = None
        self.prev_hand = None          # last hand position, for precision gain
        self.prev_f = None             # (fx, fy, t) for velocity lead
        self.vel = (0.0, 0.0)          # smoothed velocity - noise can't lead
        self.anchor = None             # deadzone anchor: where the cursor sits

    def reset(self):
        self.fx.reset()
        self.fy.reset()
        self.active = False
        self.prev_hand = None
        self.prev_f = None
        self.vel = (0.0, 0.0)
        self.anchor = None

    def box(self):
        return (self.bx0, self.bx0 + CONTROL_W, self.by0, self.by0 + CONTROL_H)

    def update(self, obs, now):
        if obs["pose"] != "point":
            self.reset()
            return None
        ix, iy = obs["ix"], obs["iy"]
        if not self.active:
            self.active = True
            cfx, cfy = self.last_out
            self.bx0 = ix - cfx * CONTROL_W
            self.by0 = iy - cfy * CONTROL_H
            self.prev_hand = None

        # precision assist: creep the box along with a SLOW hand so the same
        # wrist movement covers less screen. Fast strokes get the full 1:1
        # mapping back, so big sweeps still feel absolute.
        p_dt = min(max(now - (self._assist_t or now), 0.0), 0.1)
        if self.prev_hand is not None and p_dt > 1e-4:
            dix, diy = ix - self.prev_hand[0], iy - self.prev_hand[1]
            hspeed = math.hypot(dix, diy) / p_dt
            gain = self.cfg.get("precision_assist", PRECISION_MAX)
            f = gain * (1.0 - min(1.0, hspeed / PRECISION_SPEED))
            if f > 0.0:
                self.bx0 += dix * f
                self.by0 += diy * f
        self.prev_hand = (ix, iy)

        # edge-drag: the hand pushes the box with it
        if ix < self.bx0:
            self.bx0 = ix
        elif ix > self.bx0 + CONTROL_W:
            self.bx0 = ix - CONTROL_W
        if iy < self.by0:
            self.by0 = iy
        elif iy > self.by0 + CONTROL_H:
            self.by0 = iy - CONTROL_H

        # edge assist: the hand near a frame border slides the box along, so
        # the cursor finishes the trip while the fingers stay in frame
        now_dt = min(max(now - (self._assist_t or now), 0.0), 0.1)
        self._assist_t = now
        k = min(1.0, EDGE_ASSIST_RATE * now_dt)
        if obs.get("hand_max_y", 0.5) > 1.0 - EDGE_ASSIST_PAD:
            self.by0 += ((iy - CONTROL_H) - self.by0) * k
        elif obs.get("hand_min_y", 0.5) < EDGE_ASSIST_PAD:
            self.by0 += (iy - self.by0) * k
        if obs.get("hand_max_x", 0.5) > 1.0 - EDGE_ASSIST_PAD:
            self.bx0 += ((ix - CONTROL_W) - self.bx0) * k
        elif obs.get("hand_min_x", 0.5) < EDGE_ASSIST_PAD:
            self.bx0 += (ix - self.bx0) * k
        sx = min(max((ix - self.bx0) / CONTROL_W, 0.0), 1.0)
        sy = min(max((iy - self.by0) / CONTROL_H, 0.0), 1.0)
        gx, gy = self.fx(sx, now), self.fy(sy, now)

        # velocity lead: place the cursor where the hand is HEADED, cancelling
        # camera latency - but ONLY during real motion. A hovering hand gets
        # zero lead, so tremor can't wiggle the cursor
        lx = ly = 0.0
        if self.prev_f is not None:
            pfx, pfy, pt_ = self.prev_f
            dt = now - pt_
            if 0.0 < dt < 0.2:
                vx = 0.5 * self.vel[0] + 0.5 * (gx - pfx) / dt
                vy = 0.5 * self.vel[1] + 0.5 * (gy - pfy) / dt
                self.vel = (vx, vy)
                speed = math.hypot(vx, vy)
                ramp = min(max((speed - POINTER_LEAD_MIN_SPEED)
                               / POINTER_LEAD_RAMP, 0.0), 1.0)
                lx = vx * POINTER_LOOKAHEAD_S * ramp
                ly = vy * POINTER_LOOKAHEAD_S * ramp
                lx = max(-POINTER_LEAD_MAX, min(POINTER_LEAD_MAX, lx))
                ly = max(-POINTER_LEAD_MAX, min(POINTER_LEAD_MAX, ly))
        self.prev_f = (gx, gy, now)

        out = (min(max(gx + lx, 0.0), 1.0), min(max(gy + ly, 0.0), 1.0))

        # soft deadzone - the cure for idle drift. Inside it the cursor is
        # perfectly still; outside, motion continues from the edge with no jump
        if self.anchor is None:
            self.anchor = out
        else:
            dx, dy = out[0] - self.anchor[0], out[1] - self.anchor[1]
            dist = math.hypot(dx, dy)
            dz = self.cfg.get("cursor_deadzone", POINTER_DEADZONE)
            if dist <= dz:
                out = self.anchor
            else:
                k = (dist - dz) / dist
                out = (self.anchor[0] + dx * k, self.anchor[1] + dy * k)
                self.anchor = out
        self.last_out = out
        return out


class PinchTracker:
    """Two touches, two meanings - NO timers, and both fire on PRESS:

        thumb + INDEX  touch  -> CLICK the instant they meet (~65ms debounce)
        thumb + PINKY touch   -> mouse HOLD while touched (drag); release drops

    A touch may only START while pointing is latched - that is the fist
    immunity. Once started it survives the hand's own pose collapsing, so a
    naturally curling pinch still lands."""

    OPEN, CLICKED, DRAG = 0, 1, 2

    def __init__(self):
        self.state = self.OPEN
        self.kind = None
        self.streak = 0
        self.refractory_until = 0.0
        self.ti_rest = None            # each finger's own resting distance -
        self.hold_rest = None          # touches are DROPS below it

    def force_release(self):
        evs = ["up"] if self.state == self.DRAG else []
        self.state = self.OPEN
        self.kind = None
        self.streak = 0
        return evs

    def update(self, obs, now, allow_start=True):
        if obs is None:
            return self.force_release()
        ti, hold = obs["ti_ratio"], obs["hold_ratio"]
        click_ok = obs.get("click_ok", obs.get("touch_ok", True))
        hold_ok = obs.get("hold_ok", obs.get("touch_ok", True))

        if self.state == self.CLICKED and not click_ok:
            return []                  # untrusted: hold state, change nothing
        if self.state == self.DRAG and not hold_ok:
            return []

        if self.state == self.OPEN:
            if not click_ok and not hold_ok:
                self.streak = 0
                self.kind = None
                return []
            # learn where each finger RESTS - but only from frames where it
            # is clearly NOT touching, so a touch can't poison its own baseline
            if click_ok and ti > PINCH_ON:
                self.ti_rest = ti if self.ti_rest is None else \
                    0.9 * self.ti_rest + 0.1 * ti
            if hold_ok and hold > PINCH_ON:
                self.hold_rest = hold if self.hold_rest is None else \
                    0.9 * self.hold_rest + 0.1 * hold
            if not allow_start:
                self.streak = 0
                self.kind = None
                return []
            ti_drop = click_ok and ti < PINCH_ON and (
                self.ti_rest is None or ti < self.ti_rest - TOUCH_DROP)
            hold_drop = hold_ok and hold < HOLD_ON and (
                self.hold_rest is None or hold < self.hold_rest - TOUCH_DROP)
            k = None
            if ti_drop and (not hold_drop or ti <= hold + HOLD_MARGIN):
                k = "click"
            elif hold_drop and hold < ti - HOLD_MARGIN:
                k = "hold"             # pinky+thumb - far from the index,
                                       # so the two can never blur together
            if k is None or k != self.kind:
                self.kind = k
                self.streak = 1 if k else 0
                return []
            self.streak += 1
            need = CLICK_PRESS_FRAMES          # hold fires as fast as a click
            # a touch that began during the refractory is NOT thrown away -
            # it fires the instant the gate opens (double-clicks need this)
            if self.streak >= need and now >= self.refractory_until:
                self.streak = 0
                if k == "click":
                    self.state = self.CLICKED
                    return ["tap"]              # fires NOW, on contact
                self.state = self.DRAG
                return ["down"]
            return []

        if self.state == self.CLICKED:
            # already fired - the slightest separation re-arms
            if ti > PINCH_RELEASE:
                self.state = self.OPEN
                self.kind = None
                self.refractory_until = now + CLICK_REFRACTORY_S
            return []

        # DRAG (held by the pinky)
        if hold > HOLD_RELEASE:
            self.state = self.OPEN
            self.kind = None
            self.refractory_until = now + CLICK_REFRACTORY_S
            return ["up"]
        return []


# --------------------------------------------------------------------------- injector

class Injector:
    """Posts real macOS events, or records them in dry-run.

    Uses a PRIVATE event source and posts at the SESSION tap with explicit
    flags, so a physically-held Cmd/Shift/Option can never turn our Right
    arrow into Cmd+Right (history-forward) or our scroll into a zoom.
    """

    def __init__(self, dry_run=False):
        self.posted = []
        self.virtual_pos = [500.0, 500.0]
        self.src = None
        self.target = None             # cursor target (screen fractions)
        self.glide = Glide(tau=GLIDE_TAU)
        self.wheel = WheelSmoother()
        self._last_px = None
        self.button_down = False       # while True, moves post as DRAGGED
        self._click_t = 0.0
        self._click_xy = (0.0, 0.0)
        self._click_count = 1
        self.dry = dry_run or Quartz is None
        self.trusted = None
        if Quartz is not None:
            try:
                self.src = Quartz.CGEventSourceCreate(
                    Quartz.kCGEventSourceStatePrivate)
            except Exception:
                self.src = None
        if not self.dry:
            self.trusted = self._check_trust(prompt=True)
            if not self.trusted:
                print("\n!! Accessibility permission missing - running DRY-RUN.")
                print("   System Settings > Privacy & Security > Accessibility ->")
                print("   enable your terminal app, then restart Sleight.\n")
                self.dry = True

    @staticmethod
    def _check_trust(prompt=False):
        if AXIsProcessTrustedWithOptions is None:
            return None
        return bool(AXIsProcessTrustedWithOptions(
            {kAXTrustedCheckOptionPrompt: prompt}))

    def set_dry(self, want_dry):
        """Toggle target state; going LIVE re-validates every guard.
        Returns the resulting dry state."""
        if want_dry:
            self.dry = True
            return True
        if Quartz is None:
            print("!! Cannot go LIVE: Quartz (pyobjc) unavailable.")
            self.dry = True
            return True
        self.trusted = self._check_trust(prompt=False)
        if not self.trusted:
            print("!! Cannot go LIVE: Accessibility still not granted. Grant it "
                  "in System Settings, then RESTART Sleight.")
            self.dry = True
            return True
        self.dry = False
        return False

    # -- cursor ----------------------------------------------------------

    def _location(self):
        if self.dry:
            return tuple(self.virtual_pos)
        ev = Quartz.CGEventCreate(None)
        loc = Quartz.CGEventGetLocation(ev)
        return loc.x, loc.y

    def move_to(self, fx, fy):
        """Set the cursor TARGET (screen fractions). The actual OS cursor
        chases it smoothly from glide_tick at high rate."""
        self.posted.append(("moveto", round(fx, 3), round(fy, 3)))
        self.target = (fx, fy)
        if self.dry:
            self.virtual_pos = [fx * 1000, fy * 1000]

    def release_cursor(self):
        """Stop chasing - the physical mouse belongs to the user again."""
        self.target = None
        self.glide.reset()
        self._last_px = None

    def glide_tick(self, now):
        """High-rate output stage: called every loop iteration (~100+Hz),
        not just on camera frames. Posts the real cursor and scroll events."""
        if self.dry:
            return
        pos = self.glide.tick(self.target, now)
        if pos is not None:
            bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
            nx = bounds.origin.x + pos[0] * (bounds.size.width - 1)
            ny = bounds.origin.y + pos[1] * (bounds.size.height - 1)
            if (self._last_px is None
                    or abs(nx - self._last_px[0]) >= 0.25
                    or abs(ny - self._last_px[1]) >= 0.25):
                self._last_px = (nx, ny)
                etype = (Quartz.kCGEventLeftMouseDragged if self.button_down
                         else Quartz.kCGEventMouseMoved)
                ev = Quartz.CGEventCreateMouseEvent(
                    self.src, etype, (nx, ny), Quartz.kCGMouseButtonLeft)
                Quartz.CGEventPost(Quartz.kCGSessionEventTap, ev)
        w = self.wheel.tick(now)
        if w:
            ev = Quartz.CGEventCreateScrollWheelEvent(
                self.src, Quartz.kCGScrollEventUnitPixel, 1, w)
            Quartz.CGEventSetFlags(ev, 0)
            Quartz.CGEventPost(Quartz.kCGSessionEventTap, ev)

    def click(self):
        self.posted.append(("click",))
        now = time.time()
        x, y = self._location()
        # rapid same-spot taps stack into a REAL double/triple click - macOS
        # reads the click-count field, it does not infer it from timing
        if (now - self._click_t < DOUBLE_CLICK_S
                and abs(x - self._click_xy[0]) < DOUBLE_CLICK_SLOP_PX
                and abs(y - self._click_xy[1]) < DOUBLE_CLICK_SLOP_PX):
            self._click_count = min(self._click_count + 1, 3)
        else:
            self._click_count = 1
        self._click_t, self._click_xy = now, (x, y)
        if self.dry:
            return
        for etype in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
            ev = Quartz.CGEventCreateMouseEvent(
                self.src, etype, (x, y), Quartz.kCGMouseButtonLeft)
            Quartz.CGEventSetIntegerValueField(
                ev, Quartz.kCGMouseEventClickState, self._click_count)
            Quartz.CGEventPost(Quartz.kCGSessionEventTap, ev)

    def mouse_down(self):
        self.posted.append(("down",))
        self.button_down = True
        if self.dry:
            return
        x, y = self._location()
        ev = Quartz.CGEventCreateMouseEvent(
            self.src, Quartz.kCGEventLeftMouseDown, (x, y),
            Quartz.kCGMouseButtonLeft)
        Quartz.CGEventSetIntegerValueField(
            ev, Quartz.kCGMouseEventClickState, 1)
        Quartz.CGEventPost(Quartz.kCGSessionEventTap, ev)

    def mouse_up(self):
        self.posted.append(("up",))
        self.button_down = False
        if self.dry:
            return
        x, y = self._location()
        ev = Quartz.CGEventCreateMouseEvent(
            self.src, Quartz.kCGEventLeftMouseUp, (x, y),
            Quartz.kCGMouseButtonLeft)
        Quartz.CGEventSetIntegerValueField(
            ev, Quartz.kCGMouseEventClickState, 1)
        Quartz.CGEventPost(Quartz.kCGSessionEventTap, ev)

    # -- scroll / keys ---------------------------------------------------

    def scroll(self, dy):
        dy = int(dy)
        if dy == 0:
            return
        self.posted.append(("scroll", dy))
        if self.dry:
            return
        self.wheel.add(dy)             # delivered smoothly by glide_tick

    def key(self, name):
        entry = KEY_ACTIONS.get(name)
        if entry is None:
            return
        code, mod = entry
        self.posted.append(("key", name))
        if self.dry:
            return
        flags = 0
        if mod == "cmd":
            flags = Quartz.kCGEventFlagMaskCommand
        elif mod == "ctrl":
            flags = Quartz.kCGEventFlagMaskControl
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(self.src, code, down)
            Quartz.CGEventSetFlags(ev, flags)
            Quartz.CGEventPost(Quartz.kCGSessionEventTap, ev)


# --------------------------------------------------------------------------- app

class Sleight:
    IDLE, ARMED = "IDLE", "ARMED"

    def __init__(self, cfg, injector, aspect=CAM_W / CAM_H):
        self.cfg = cfg
        self.injector = injector
        self.gate = Gate(cfg)
        self.pose_stab = PoseStabilizer()
        self.scroll = ScrollController(cfg)
        self.pointer = PointerController(cfg, aspect)
        self.pincher = PinchTracker()
        self.palm_flick = FlickDetector("palm", "x")
        self.state = self.IDLE
        self.armed_until = 0.0
        self.armed_at = 0.0
        self.actions_this_arm = 0
        self.x_this_arm = False
        self.last_click_t = -1e9
        self.last_ptr = None
        self.pointer_on = False
        self.palm_since = None
        self.click_freeze_until = 0.0
        self.hand_lost_since = None
        self.stats = {"arms": 0, "arms_no_action": 0, "false_marks": 0,
                      "swipes": 0, "clicks": 0, "drags": 0,
                      "scroll_frames": 0, "pointer_frames": 0}
        self.session_start = time.time()
        self.log_path = os.path.join(
            HERE, f"sleight_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")

    def _soft_reset(self):
        """Hand momentarily lost. Deliberately does NOT clear the flick
        trajectory: fast flicks blur the image and drop tracking for a frame,
        and wiping the history mid-stroke was killing exactly the good flicks.
        The rolling window ages stale samples out and the step-jump guard
        catches genuine re-lock teleports."""
        self.pointer.reset()
        for pev in self.pincher.force_release():
            if pev == "up":
                self.injector.mouse_up()     # never leave the button stuck down
        self.last_ptr = None
        self.click_freeze_until = 0.0

    def _hard_reset(self):
        self._soft_reset()
        self.pointer_on = False
        self.palm_flick.reset()
        self.scroll.hard_reset()
        self.pose_stab.reset()

    def _activity(self, now, kind):
        self.actions_this_arm += 1
        self.armed_until = now + ARMED_HOLD_S
        self.stats[kind] = self.stats.get(kind, 0) + 1

    def step(self, obs, now):
        events = []
        if obs is None:
            self.gate.hand_lost(now)
            self._soft_reset()
            # a blur-frame dropout keeps its pose; a real disappearance resets
            if self.hand_lost_since is None:
                self.hand_lost_since = now
            elif now - self.hand_lost_since > POSE_LOST_GRACE_S:
                self.pose_stab.reset()
            # momentum keeps coasting even if the hand leaves the frame
            px = self.scroll.update(None, now)
            if px and self.state == self.ARMED:
                self.injector.scroll(px)
                self.stats["scroll_frames"] += 1
                events.append("scroll")
            if self.state == self.ARMED and now >= self.armed_until:
                events.append(self._disarm(now, "timeout"))
            return events

        self.hand_lost_since = None
        obs = dict(obs)
        obs["raw_pose"] = obs["pose"]
        obs["pose"] = self.pose_stab.update(obs["pose"])

        if self.state == self.IDLE:
            if self.gate.update(obs, now, CAM_W / CAM_H):
                self.state = self.ARMED
                self.armed_until = now + ARMED_HOLD_S
                self.armed_at = now
                self.actions_this_arm = 0
                self.x_this_arm = False
                self._soft_reset()
                self.scroll.hard_reset()
                self.gate.last_fail_t = now
                self.stats["arms"] += 1
                events.append("arm")
            return events

        # ---- ARMED ----
        busy = self.pincher.state != PinchTracker.OPEN
        if obs["pose"] == "point":
            self.pointer_on = True                 # latch ON
        elif obs["pose"] in ("palm", "two") and not busy:
            # a pinky-hold hand often LOOKS like a palm (other fingers up) -
            # while touching or dragging, nothing may end pointer mode
            self.pointer_on = False
        if obs["pose"] == "palm":
            if self.palm_since is None:
                self.palm_since = now
        else:
            self.palm_since = None
        for pev in self.pincher.update(obs, now, self.pointer_on):
            if pev == "tap":
                self.injector.click()
                self.last_click_t = now
                self.click_freeze_until = now + CLICK_FREEZE_S
                self.scroll.hard_reset()        # a click kills any coast
                self._activity(now, "clicks")
                events.append("click")
            elif pev == "down":
                self.injector.mouse_down()
                self._activity(now, "drags")
                events.append("drag_start")
            elif pev == "up":
                self.injector.mouse_up()
                self.armed_until = now + ARMED_HOLD_S
                events.append("drag_end")

        # cursor holds still while the touch is undecided (tap aim), and
        # tracks freely during a HOLD - that is what dragging is
        # the cursor moves freely while touching - click lands where you
        # release. Only the touch-onset debounce and post-tap blink freeze it
        frozen = self.pincher.streak > 0 or now < self.click_freeze_until
        if not frozen and self.pointer_on:
            # while latched, steer no matter what the pose looks like -
            # a curled hand steers exactly like a straight one
            p_obs = obs if obs["pose"] == "point" else {**obs, "pose": "point"}
            pos = self.pointer.update(p_obs, now)
            if pos is not None:
                self.injector.move_to(*pos)
                moved = (self.last_ptr is None
                         or abs(pos[0] - self.last_ptr[0]) > POINTER_RENEW_FRAC
                         or abs(pos[1] - self.last_ptr[1]) > POINTER_RENEW_FRAC)
                if moved:
                    self.last_ptr = pos
                    self._activity(now, "pointer_frames")
                    events.append("pointer")
            else:
                self.injector.release_cursor()   # hand off the mouse cleanly
        elif not self.pointer_on:
            self.pointer.reset()
            self.injector.release_cursor()

        # scroll clutches on the RAW pose - releasing the grip must be
        # instant, while pose consumers keep the anti-flicker debounce.
        # a touch/drag in progress suspends scrolling entirely
        raw = obs["raw_pose"]
        busy = self.pincher.state != PinchTracker.OPEN
        wheel = self.scroll.update(
            {**obs, "pose": raw if not busy else "_busy"}, now)
        if wheel:
            self.injector.scroll(wheel)
            events.append("scroll")
            if raw == "two":
                self._activity(now, "scroll_frames")     # coasting doesn't renew
            else:
                self.stats["scroll_frames"] += 1

        # back/next = whole-palm flick: big target, tracks well at speed
        in_grace = (now - self.armed_at) < POST_ARM_GRACE_S
        palm_settled = (self.palm_since is not None
                        and (now - self.palm_since) >= PALM_FLICK_GRACE_S)
        if (not in_grace and not busy
                and (obs["pose"] != "palm" or palm_settled)):
            flick = self.palm_flick.update(obs, now)
            if flick:
                direction = "right" if flick == "pos" else "left"
                self.injector.key(self.cfg[f"swipe_{direction}_key"])
                self._activity(now, "swipes")
                self.scroll.hard_reset()
                events.append(f"swipe_{direction}")

        if now >= self.armed_until:
            events.append(self._disarm(now, "timeout"))
        return events

    def _disarm(self, now, why):
        self.state = self.IDLE
        self.gate.hand_lost(now)
        self._hard_reset()
        self.injector.release_cursor()
        if self.actions_this_arm == 0:
            self.stats["arms_no_action"] += 1
        self.log({"event": "arm_end", "reason": why,
                  "actions": self.actions_this_arm,
                  "duration": round(now - self.armed_at, 2),
                  "x_marked": self.x_this_arm})
        return f"disarm_{why}"

    def mark_false(self):
        self.stats["false_marks"] += 1
        if self.state == self.ARMED:
            self.x_this_arm = True          # attribute to the arm in progress
        self.log({"event": "false_arm_marked"})

    def log(self, payload):
        payload["t"] = round(time.time() - self.session_start, 2)
        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(payload) + "\n")
        except OSError:
            pass

    def report(self):
        mins = (time.time() - self.session_start) / 60
        s = self.stats
        rate = s["arms_no_action"] / mins * 20 if mins > 0.5 else 0.0
        print("\n" + "=" * 62)
        print("  SLEIGHT v7.8 - SESSION REPORT")
        print("=" * 62)
        print(f"  duration            {mins:.1f} min")
        print(f"  arms                {s['arms']}")
        print(f"  arms with actions   {s['arms'] - s['arms_no_action']}")
        print(f"  arms w/o actions    {s['arms_no_action']}   <- false-arm candidates")
        print(f"  explicit false (x)  {s['false_marks']}   <- ground truth")
        print(f"  clicks              {s['clicks']}")
        print(f"  drags               {s['drags']}")
        print(f"  swipes              {s['swipes']}")
        print(f"  scroll frames       {s['scroll_frames']}")
        print(f"  pointer frames      {s['pointer_frames']}")
        print(f"  no-action arm rate  {rate:.2f} per 20 min "
              f"(candidates; x-marks are the real count)")
        print(f"  log                 {os.path.basename(self.log_path)}")
        print("=" * 62 + "\n")
        self.log({"event": "session_end", "stats": s, "minutes": round(mins, 1)})


# --------------------------------------------------------------------------- HUD

GUIDE = [
    ("point", "1 finger", "move cursor"),
    ("pinch", "thumb + index touch", "click (on contact)"),
    ("hold", "thumb + pinky touch", "hold / drag"),
    ("two", "2 fingers  up/down", "scroll (curl to pause)"),
    ("palm", "whole palm  flick L/R", "back / forward"),
]

TOAST_S = 0.8
TOASTS = {"click": "CLICK", "drag_start": "HOLD", "drag_end": "RELEASE",
          "swipe_left": "FORWARD", "swipe_right": "BACK",
          "arm": "ARMED", "disarm_timeout": "IDLE"}


def draw_guide(frame, active_pose, now, w, h):
    gw = 330
    x0 = w - gw
    panel = frame.copy()
    cv2.rectangle(panel, (x0, 0), (w, h), INK, -1)
    cv2.addWeighted(panel, 0.82, frame, 0.18, 0, frame)
    cv2.line(frame, (x0, 0), (x0, h), HAIR, 1, cv2.LINE_AA)

    y = 48
    draw_tracked(frame, "GESTURES", (x0 + 22, y), 0.45, GREY, 1, tracking=10)
    cv2.line(frame, (x0 + 22, y + 14), (w - 22, y + 14), HAIR, 1, cv2.LINE_AA)
    y += 24
    for pose, gesture, action in GUIDE:
        y += 54
        on = pose == active_pose
        if on:
            cv2.rectangle(frame, (x0 + 12, y - 32), (w - 12, y + 16),
                          RAISED, -1)
            cv2.rectangle(frame, (x0 + 12, y - 32), (x0 + 15, y + 16),
                          PAPER, -1)
        cv2.putText(frame, gesture, (x0 + 26, y - 8), FONT, 0.52,
                    PAPER if on else SILVER, 1, cv2.LINE_AA)
        draw_serif(frame, action, (x0 + 26, y + 13), 0.42,
                   SILVER if on else GREY)
        cx_cue = w - 44
        g = PAPER if on else GREY
        if "L/R" in gesture:
            cv2.arrowedLine(frame, (cx_cue - 12, y - 4), (cx_cue + 12, y - 4),
                            g, 1, tipLength=0.4)
        elif "up/down" in gesture:
            cv2.arrowedLine(frame, (cx_cue, y + 6), (cx_cue, y - 14),
                            g, 1, tipLength=0.4)
        elif pose == "pinch":
            cv2.circle(frame, (cx_cue, y - 4), 7, g, 1, cv2.LINE_AA)
            cv2.circle(frame, (cx_cue, y - 4), 2, g, -1, cv2.LINE_AA)
        elif pose == "hold":
            cv2.circle(frame, (cx_cue, y - 4), 7, g, 1, cv2.LINE_AA)
            cv2.circle(frame, (cx_cue, y - 4), 3, g, 1, cv2.LINE_AA)
        elif pose == "point":
            cv2.circle(frame, (cx_cue, y - 4), 3, g, -1, cv2.LINE_AA)


def draw_hud(frame, app, toast, now, w, h):
    # scrim under the top-left readout: light type on a bright wall is
    # unreadable without it
    band = frame.copy()
    cv2.rectangle(band, (0, 0), (w - 330, 160), (0, 0, 0), -1)
    cv2.rectangle(band, (0, h - 110), (w - 330, h), (0, 0, 0), -1)
    cv2.addWeighted(band, 0.72, frame, 0.28, 0, frame)

    if app.state == Sleight.ARMED:
        cv2.rectangle(frame, (1, 1), (w - 2, h - 2), PAPER, 2)
        draw_tracked(frame, "ARMED", (24, 52), 0.8, PAPER, 1, tracking=14,
                     halo=True)
        draw_text(frame, f"{max(0.0, app.armed_until - now):.1f}",
                  (24, 84), 0.55, GREY, 1)
        if app.pincher.state == PinchTracker.CLICKED:
            draw_tracked(frame, "CLICK", (24, 140), 0.55, PAPER, 1, halo=True)
        elif app.pincher.state == PinchTracker.DRAG:
            draw_tracked(frame, "HOLD", (24, 140), 0.55, PAPER, 1, halo=True)
        # flick meter: how close the current stroke is to firing
        if abs(app.palm_flick.last_disp) > 0.05:
            frac = min(1.0, abs(app.palm_flick.last_disp) / SWIPE_DISP)
            cv2.line(frame, (24, 106), (244, 106), HAIR, 2, cv2.LINE_AA)
            cv2.line(frame, (24, 106), (24 + int(220 * frac), 106),
                     PAPER if frac >= 1.0 else SILVER, 2, cv2.LINE_AA)
    else:
        hint = summon_hint(app.gate)
        draw_tracked(frame, hint or "OPEN PALM  HOLD STILL", (24, 52), 0.6,
                     PAPER if hint else SILVER, 1, tracking=9, halo=True)
        if app.gate.hold_progress > 0:
            cv2.line(frame, (24, 72), (w - 360, 72), HAIR, 2, cv2.LINE_AA)
            cv2.line(frame, (24, 72),
                     (24 + int((w - 384) * app.gate.hold_progress), 72),
                     PAPER, 2, cv2.LINE_AA)
        x = 24
        for name, ok in app.gate.conditions.items():
            cv2.circle(frame, (x + 4, 98), 4, PAPER if ok else (70, 70, 70),
                       -1, cv2.LINE_AA)
            cv2.putText(frame, name, (x + 14, 103), FONT, 0.42,
                        PAPER if ok else GREY, 1, cv2.LINE_AA)
            x += 105

    if toast:
        draw_tracked(frame, toast,
                     (w // 2 - track_w(toast, 1.1, 2, 14) // 2, h // 2),
                     1.1, PAPER, 2, tracking=14, halo=True)

    s = app.stats
    cv2.putText(frame, f"arms {s['arms']}   quiet {s['arms_no_action']}   "
                       f"clicks {s['clicks']}   swipes {s['swipes']}",
                (24, h - 40), FONT, 0.45, SILVER, 1, cv2.LINE_AA)
    if app.injector.dry:
        # inverted chip = the one alarm state: gestures are NOT live
        rounded_rect(frame, (24, h - 90), (152, h - 62), 6, PAPER, -1)
        cv2.putText(frame, "DRY RUN", (40, h - 71), FONT, 0.5, (0, 0, 0), 1,
                    cv2.LINE_AA)
    else:
        draw_tracked(frame, "LIVE", (24, h - 70), 0.45, PAPER, 1, halo=True)
    cv2.putText(frame, "q quit   c calibrate   x false   v flip scroll   d dry run",
                (24, h - 14), FONT, 0.42, GREY, 1, cv2.LINE_AA)


# --------------------------------------------------------------------------- pill view

PANEL_W, PANEL_H = 560, 116            # the dock pill WINDOW size, in points
PILL = (10, 8, 550, 108)               # pill capsule inside the window
MAP_W, MAP_H = 152, 84                 # 16:9 hand map (your hand, live)
PILL_GAP_BOTTOM = 78                   # clearance above the Dock
PILL_SS = 2                            # draw at 2x, show at 1x: on a Retina
                                       # screen a 1x canvas gets stretched and
                                       # looks pixelated - this lands on real
                                       # pixels instead


def screen_size():
    if Quartz is not None:
        try:
            b = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
            return int(b.size.width), int(b.size.height)
        except Exception:
            pass
    return 1440, 900


def place_window(view, pos="center"):
    sw, sh = screen_size()
    if view == "hidden":
        # the glass widget is doing the talking - park the plain window where
        # nobody has to look at it
        cv2.moveWindow("Sleight", -4000, -4000)
    elif view == "panel":
        cv2.resizeWindow("Sleight", PANEL_W, PANEL_H)
        y = max(0, sh - PANEL_H - PILL_GAP_BOTTOM)
        if pos == "right":
            cv2.moveWindow("Sleight", max(0, sw - PANEL_W - 24), y)
        else:                                        # bottom-center (default)
            cv2.moveWindow("Sleight", max(0, (sw - PANEL_W) // 2), y)
    else:
        cv2.resizeWindow("Sleight", 960, 540)
        cv2.moveWindow("Sleight", max(0, (sw - 960) // 2), 60)


_PILL = {"xy": None, "t": 0.0, "energy": 0.0}

STATE_WORDS = {"point": "CURSOR", "two": "SCROLL", "palm": "PALM",
               "pinch": "CLICK", "hold": "HOLD"}

# What to DO about each failing summon condition - one instruction, never a
# debug dot. Checked in this order; the first unmet one is what you see.
COACH = [("POSE", "OPEN HAND"), ("PALM", "TURN PALM"), ("SIZE", "DISTANCE"),
         ("CENTER", "CENTER HAND"), ("STILL", "HOLD STILL")]


def summon_hint(gate, obs=None):
    """The single most useful instruction right now, or None if all clear."""
    for key, word in COACH:
        if gate.conditions.get(key) is False:
            if key == "SIZE" and obs is not None and "scale" in obs:
                lo, _hi = gate.cfg["size_band"]
                return "CLOSER" if obs["scale"] < lo else "FURTHER"
            return word
    return None


def _pill_energy(obs, now):
    """EMA of fingertip speed - drives the motion bars in the pill."""
    if obs is None:
        _PILL["xy"] = None
        _PILL["energy"] *= 0.9
        return _PILL["energy"]
    xy = (obs["ix"], obs["iy"])
    if _PILL["xy"] is not None:
        dt = max(1e-3, now - _PILL["t"])
        v = math.hypot(xy[0] - _PILL["xy"][0], xy[1] - _PILL["xy"][1]) / dt
        _PILL["energy"] = 0.75 * _PILL["energy"] + 0.25 * min(1.0, v / 1.2)
    _PILL["xy"], _PILL["t"] = xy, now
    return _PILL["energy"]


# --------------------------------------------------------------------------- glass widget

# The floating widget. It is COLLAPSED (a bare nub) until a hand appears, then
# it grows into the full pill - you should not have to look at Sleight until
# you are actually talking to it.
GLASS_W, GLASS_H = 520, 132      # the invisible canvas, in points
NUB = 38                         # collapsed: a CIRCLE, width == height, so
                                 # the orb is dead-centre by construction
FULL_W = 268                     # expanded capsule width
CAP_H = 48                       # expanded capsule height
HAND_W, HAND_H = 112, 64         # the hand, floating BESIDE the capsule
GAP = 16
EXPAND_TAU = 0.09                # capsule grow/shrink time constant
MORPH_S = 0.20                   # how long one word takes to become the next
ORB_BREATH_S = 1.8               # idle breath period (Claude's cds-dot-pulse)
ORB_A_LO, ORB_A_HI = 118, 214    # ...and it breathes on alpha, never on size
_STILL = [False]                 # honour the system's Reduce Motion setting


def ease(x):
    """Smooth both ends - nothing in a physical object starts at full speed."""
    return x * x * (3.0 - 2.0 * x)


class PillUI:
    """The widget's own animation state: how open it is, and which word it is
    in the middle of becoming."""

    def __init__(self):
        self.open = 0.0
        self.word = ""
        self.prev = ""
        self.morph_t = 0.0
        self._last = None

    def update(self, target_open, word, now):
        dt = 0.033 if self._last is None else max(0.0, min(0.1, now - self._last))
        self._last = now
        self.open += (target_open - self.open) * min(1.0, dt / EXPAND_TAU)
        if word != self.word:
            self.prev, self.word, self.morph_t = self.word, word, now
        return self.open

    def morph(self, now):
        """0 -> 1 across a word change; 1 means settled."""
        return min(1.0, (now - self.morph_t) / MORPH_S) if self.word else 1.0


def _rgba(color, alpha):
    return (color[0], color[1], color[2], int(max(0, min(255, alpha))))


def blit_text(canvas, tb, x, y, alpha=255, tint=PAPER):
    """Composite a rasterised system-font bitmap onto the RGBA canvas with
    straight-alpha OVER. Returns the width drawn (0 if it did not fit)."""
    if tb is None:
        return 0
    th, tw = tb.shape[:2]
    x, y = int(x), int(y)
    sx0, sy0 = max(0, -x), max(0, -y)
    dx0, dy0 = max(0, x), max(0, y)
    w = min(tw - sx0, canvas.shape[1] - dx0)
    h = min(th - sy0, canvas.shape[0] - dy0)
    if w <= 0 or h <= 0:
        return 0
    src = tb[sy0:sy0 + h, sx0:sx0 + w]
    dst = canvas[dy0:dy0 + h, dx0:dx0 + w]
    sa = src[:, :, 3].astype(np.float32) * (alpha / 255.0) / 255.0
    da = dst[:, :, 3].astype(np.float32) / 255.0
    oa = sa + da * (1.0 - sa)
    safe = np.maximum(oa, 1e-6)
    for ch in range(3):
        dst[:, :, ch] = np.clip(
            (tint[ch] * sa + dst[:, :, ch].astype(np.float32) * da * (1 - sa))
            / safe, 0, 255).astype(np.uint8)
    dst[:, :, 3] = np.clip(oa * 255.0, 0, 255).astype(np.uint8)
    return tw


def render_pill_rgba(app, obs, active, toast, now, lms, ui, scale=2):
    """The widget, drawn straight-alpha over a real macOS blur. Returns
    (rgba, capsule_rect_in_points). Everything the user does not need right
    now is transparent - that is the whole point of the glass."""
    S = scale
    W, H = GLASS_W * S, GLASS_H * S
    c = np.zeros((H, W, 4), dtype=np.uint8)

    armed = app.state == Sleight.ARMED
    seen = obs is not None
    # what the widget is trying to say, right now, in one word
    if toast:
        word = toast
    elif armed:
        word = STATE_WORDS.get(active, "ARMED")
    elif seen:
        word = summon_hint(app.gate, obs) or "READY"
    else:
        word = ""
    op = ease(ui.update(1.0 if seen else 0.0, word, now))

    # the capsule is as wide as the WORD needs - "CENTER HAND" must not spill
    # out of a capsule sized for "CLICK"
    tb_w = 0
    for w_ in (ui.word, ui.prev if ui.morph(now) < 1.0 else ""):
        if w_:
            t_ = glass.text_bitmap(w_, 13.0 * S, weight=0.23, tracking=1.9 * S)
            tb_w = max(tb_w, (t_.shape[1] / S) if t_ is not None
                       else track_w(w_, 0.5, 1, 8))
    open_w = max(NUB + 74, min(FULL_W, CAP_H / 2 + 20 + tb_w + 22))

    # width AND height morph, Dynamic-Island style: a circle becomes a capsule
    cap_w = NUB + (open_w - NUB) * op
    cap_h = NUB + (CAP_H - NUB) * op
    hand_a = max(0.0, (op - 0.45) / 0.55)          # the hand arrives last
    content_w = cap_w + (GAP + HAND_W) * hand_a
    x0 = (GLASS_W - content_w) / 2.0               # always visually centred
    cy = GLASS_H / 2.0

    # ---- capsule. The HUD material really does let the desktop through, so
    # a dark tint rides on top of it: without one, white type over a light
    # wallpaper drops to ~2:1 contrast and disappears.
    cx0, cy0 = int(x0 * S), int((cy - cap_h / 2) * S)
    cx1, cy1 = int((x0 + cap_w) * S), int((cy + cap_h / 2) * S)
    rounded_rect(c, (cx0, cy0), (cx1, cy1), (cy1 - cy0) // 2,
                 (18, 18, 18, 128), -1)
    rounded_rect(c, (cx0, cy0), (cx1, cy1), (cy1 - cy0) // 2,
                 _rgba(PAPER, 42), S)
    if cap_w > cap_h + 4:            # a circle has no "top edge" to catch light
        cv2.line(c, (cx0 + int(cap_h / 2 * S), cy0),
                 (cx1 - int(cap_h / 2 * S), cy0), _rgba(PAPER, 90), S,
                 cv2.LINE_AA)

    # ---- the orb. Anchored half a capsule-height in, so while the shape is
    # still a circle it sits exactly in the middle of it.
    bx = int((x0 + cap_h / 2) * S)
    orb_r = cap_h * 0.27
    e = _pill_energy(obs, now)
    if armed:
        g = 228 + int(18 * math.sin(now * 2.4))
        draw_blob(c, (bx, int(cy * S)), orb_r * S, e, now, (g, g, g, 255))
    elif seen:
        draw_blob(c, (bx, int(cy * S)), orb_r * S, min(0.5, e), now,
                  _rgba(SILVER, 255))
    else:
        # Asleep: a flat circle that breathes on ALPHA, not on size. Claude's
        # own idle dot (cds-dot-pulse) is 1.8s, 20%->70%->20%, zero scale -
        # scaling an idle dot is the thing they deliberately don't do, and a
        # radial gradient on a small monochrome disc is the giveaway of a
        # generated one. Presence comes from a single hairline instead.
        ph = 0.5 - 0.5 * math.cos(now * (2 * math.pi / ORB_BREATH_S))
        a = ORB_A_LO + (ORB_A_HI - ORB_A_LO) * (0.5 if _STILL[0] else ph)
        cv2.circle(c, (bx, int(cy * S)), int(orb_r * S), _rgba(SILVER, a),
                   -1, cv2.LINE_AA)
        cv2.circle(c, (bx, int(cy * S)), int(orb_r * S), _rgba(PAPER, a * 0.34),
                   max(1, S), cv2.LINE_AA)

    if not armed and seen and app.gate.hold_progress > 0:
        rr = int((cap_h / 2 - 3) * S)
        cv2.ellipse(c, (bx, int(cy * S)), (rr, rr), -90, 0,
                    int(360 * app.gate.hold_progress), _rgba(PAPER, 255),
                    2 * S, cv2.LINE_AA)

    # ---- the word, becoming the next word: old lifts out, new rises in
    if op > 0.25:
        p = ui.morph(now)
        tx = int((x0 + cap_h / 2 + 20) * S)
        gate_a = min(1.0, (op - 0.25) / 0.4)

        def _word(txt, dy, a):
            tb = glass.text_bitmap(txt, 13.0 * S, weight=0.23,
                                   tracking=1.9 * S)
            if tb is None:                       # no AppKit: stroke font
                draw_tracked(c, txt, (tx, int(cy * S + 6 * S + dy)), 0.5 * S,
                             _rgba(PAPER, a), S, tracking=8)
                return
            blit_text(c, tb, tx, int(cy * S - tb.shape[0] / 2 + dy), a, PAPER)

        if ui.prev and p < 1.0:
            _word(ui.prev, -10 * S * p, 255 * (1 - p) * gate_a)
        if ui.word:
            _word(ui.word, 10 * S * (1 - p), 255 * p * gate_a)

    # ---- the hand, on its own frosted chip beside the capsule
    chip_rect = None
    if hand_a > 0.02:
        hx0 = x0 + cap_w + GAP
        hy0 = cy - HAND_H / 2
        pad = 8
        chip_rect = (hx0 - pad, GLASS_H - (hy0 + HAND_H) - pad,
                     HAND_W + pad * 2, HAND_H + pad * 2)
        # same dark tint over the chip's own glass, so the hand reads on any
        # wallpaper (it vanished over a light one before)
        rounded_rect(c, (int((hx0 - pad) * S), int((hy0 - pad) * S)),
                     (int((hx0 + HAND_W + pad) * S),
                      int((hy0 + HAND_H + pad) * S)), 12 * S,
                     (18, 18, 18, int(128 * hand_a)), -1)

        def _hx(v):
            return int((hx0 + max(0.0, min(1.0, v)) * HAND_W) * S)

        def _hy(v):
            return int((hy0 + max(0.0, min(1.0, v)) * HAND_H) * S)

        a = 255 * hand_a
        bx0, bx1_, by0, by1_ = app.pointer.box()
        cv2.rectangle(c, (_hx(bx0), _hy(by0)), (_hx(bx1_), _hy(by1_)),
                      _rgba(PAPER, a * (0.5 if app.pointer_on else 0.22)), S)
        if lms is not None:
            pts = [(_hx(l.x), _hy(l.y)) for l in lms]
            for i, j in mp.solutions.hands.HAND_CONNECTIONS:
                cv2.line(c, pts[i], pts[j],
                         _rgba(PAPER, a * (0.85 if armed else 0.5)), S,
                         cv2.LINE_AA)
            for tip in (4, 8, 12, 16, 20):
                cv2.circle(c, pts[tip], S + 1, _rgba(PAPER, a), -1, cv2.LINE_AA)
        if seen:
            cv2.circle(c, (_hx(obs["ix"]), _hy(obs["iy"])), 3 * S,
                       _rgba(PAPER, a if app.pointer_on else a * 0.5), -1,
                       cv2.LINE_AA)

    # rects in POINTS, AppKit origin (bottom-left)
    rect = (x0, GLASS_H - (cy + cap_h / 2), cap_w, cap_h)
    return c, rect, chip_rect


def render_panel(app, obs, active, toast, now, thumb=None, lms=None):
    """The dock pill: living blob, state word, and the hand map - your actual
    hand, drawn inside the mapping box, like looking down at a trackpad.
    Brightness is the only signal: armed glows, waiting is silver, no hand is
    hairline-dim. Drawn at PILL_SS x so it stays crisp on a Retina screen."""
    S = PILL_SS
    c = np.full((PANEL_H * S, PANEL_W * S, 3), INK[0], dtype=np.uint8)
    x0, y0, x1, y1 = (v * S for v in PILL)
    mw, mh = MAP_W * S, MAP_H * S
    armed = app.state == Sleight.ARMED
    seen = obs is not None
    cy = (y0 + y1) // 2
    rounded_rect(c, (x0, y0), (x1, y1), (y1 - y0) // 2, SURFACE, -1)
    rounded_rect(c, (x0, y0), (x1, y1), (y1 - y0) // 2,
                 PAPER if (armed or toast) else HAIR, S)

    # -- the living blob: breathes with the hand, glows when armed
    e = _pill_energy(obs, now)
    bx_c = x0 + 46 * S
    if armed:
        glow = 226 + int(20 * math.sin(now * 2.4))
        draw_blob(c, (bx_c, cy), 15 * S, e, now, (glow, glow, glow))
    elif seen:
        draw_blob(c, (bx_c, cy), 12 * S, min(0.5, e), now, SILVER)
    else:
        draw_blob(c, (bx_c, cy), 10 * S, 0.06, now * 0.35, RAISED)
        cv2.circle(c, (bx_c, cy), 10 * S, HAIR, S, cv2.LINE_AA)

    # -- summon progress ring: the arc closes while you hold the palm still
    if not armed and seen and app.gate.hold_progress > 0:
        cv2.ellipse(c, (bx_c, cy), (21 * S, 21 * S), -90, 0,
                    int(360 * app.gate.hold_progress), PAPER, 2 * S,
                    cv2.LINE_AA)

    # -- state word: italic-serif wordmark asleep, tracked caps in action
    wx = x0 + 84 * S
    if toast:
        draw_tracked(c, toast, (wx, cy + 6 * S), 0.55 * S, PAPER, S, tracking=8)
    elif armed:
        draw_tracked(c, STATE_WORDS.get(active, "ARMED"), (wx, cy + 6 * S),
                     0.55 * S, PAPER, S, tracking=8)
    elif seen:
        # never leave the user guessing why it will not start
        hint = summon_hint(app.gate, obs)
        draw_tracked(c, hint or "READY", (wx, cy + 6 * S), 0.55 * S,
                     SILVER if hint is None else PAPER, S, tracking=8)
    else:
        draw_serif(c, "Sleight", (wx, cy + 8 * S), 0.75 * S, GREY, S)

    # -- alarm chip: DRY (inverted = loudest) or EDGE (clicks paused)
    chx1 = x1 - 30 * S - mw - 12 * S
    if app.injector.dry:
        rounded_rect(c, (chx1 - 52 * S, cy - 11 * S), (chx1, cy + 11 * S),
                     6 * S, PAPER, -1)
        cv2.putText(c, "DRY", (chx1 - 42 * S, cy + 5 * S), FONT, 0.45 * S,
                    (0, 0, 0), S, cv2.LINE_AA)
    elif seen and armed and not obs.get("click_ok", True):
        rounded_rect(c, (chx1 - 52 * S, cy - 11 * S), (chx1, cy + 11 * S),
                     6 * S, HAIR, S)
        cv2.putText(c, "EDGE", (chx1 - 45 * S, cy + 5 * S), FONT, 0.4 * S,
                    SILVER, S, cv2.LINE_AA)

    # -- hand map: the camera frame in miniature, with YOUR HAND in it
    mx1 = x1 - 30 * S
    mx0 = mx1 - mw
    my0 = cy - mh // 2

    # the virtual fingertip and a re-anchored box routinely leave [0,1];
    # clamp so strays can't stroke across the chip or the capsule
    def _mx(v):
        return mx0 + int(max(0.0, min(1.0, v)) * mw)

    def _my(v):
        return my0 + int(max(0.0, min(1.0, v)) * mh)

    cv2.rectangle(c, (mx0, my0), (mx1, my0 + mh), HAIR, S)
    bx0, bx1_, by0, by1_ = app.pointer.box()
    cv2.rectangle(c, (_mx(bx0), _my(by0)), (_mx(bx1_), _my(by1_)),
                  SILVER if app.pointer_on else HAIR, S)

    if lms is not None:                      # the hand itself, live
        pts = [(_mx(l.x), _my(l.y)) for l in lms]
        for a, b in mp.solutions.hands.HAND_CONNECTIONS:
            cv2.line(c, pts[a], pts[b], SILVER if armed else GREY, S,
                     cv2.LINE_AA)
        for tip in (4, 8, 12, 16, 20):
            cv2.circle(c, pts[tip], S + 1, PAPER if armed else SILVER, -1,
                       cv2.LINE_AA)
    if seen:                                 # the cursor anchor
        cv2.circle(c, (_mx(obs["ix"]), _my(obs["iy"])), 3 * S,
                   PAPER if app.pointer_on else GREY, -1, cv2.LINE_AA)
        cv2.circle(c, (_mx(obs["ix"]), _my(obs["iy"])), 3 * S, INK, 1,
                   cv2.LINE_AA)
    return c


# --------------------------------------------------------------------------- tutorial

class Tutorial:
    """Interactive lessons, one gesture at a time. Runs in DRY-RUN so nothing
    the learner does can touch the real system. Completion is detection-based:
    the step advances when the gesture actually worked."""

    STEPS = [
        ("Summon", "Open palm toward the camera, hold still ~1s"),
        ("Move the cursor", "Point with 1 finger - move your hand"),
        ("Click", "Touch thumb + index together - it clicks on contact"),
        ("Scroll", "TWO fingers up - move your hand up/down"),
        ("Back / Next", "Whole palm open - flick left or right, fast"),
    ]

    def __init__(self):
        self.idx = 0
        self.count = 0
        self.done = False
        self.flash_until = 0.0

    def skip_step(self, now):
        self._advance(now)

    def _advance(self, now):
        self.idx += 1
        self.count = 0
        self.flash_until = now + 1.0
        if self.idx >= len(self.STEPS):
            self.done = True

    def update(self, events, now):
        if self.done:
            return
        i = self.idx
        if i == 0 and "arm" in events:
            self._advance(now)
        elif i == 1:
            self.count += events.count("pointer")
            if self.count >= 20:
                self._advance(now)
        elif i == 2 and "click" in events:
            self._advance(now)
        elif i == 3:
            self.count += events.count("scroll")
            if self.count >= 12:
                self._advance(now)
        elif i == 4 and any(e.startswith("swipe") for e in events):
            self._advance(now)      # last lesson: lowering the hand = done

    def draw(self, frame, app, now, w, h):
        cv2.rectangle(frame, (0, h - 130), (w, h), INK, -1)
        cv2.line(frame, (0, h - 130), (w, h - 130), HAIR, 1, cv2.LINE_AA)
        chip_w = track_w("PRACTICE MODE", 0.5, 1) + 28
        rounded_rect(frame, (24, 138), (24 + chip_w, 166), 6, PAPER, -1)
        draw_tracked(frame, "PRACTICE MODE", (38, 157), 0.5, (0, 0, 0), 1)
        cv2.putText(frame, "nothing reaches your Mac - press t to exit",
                    (24 + chip_w + 14, 157), FONT, 0.45, SILVER, 1,
                    cv2.LINE_AA)
        if self.done:
            draw_tracked(frame, "TUTORIAL COMPLETE", (24, h - 70), 0.8,
                         PAPER, 1, tracking=10, halo=True)
            return
        title, instr = self.STEPS[self.idx]
        draw_tracked(frame, f"{self.idx + 1} / {len(self.STEPS)}   {title}",
                     (24, h - 86), 0.6, PAPER, 1, tracking=8, halo=True)
        draw_serif(frame, instr, (24, h - 52), 0.62, PAPER, 1, halo=True)
        if self.idx in (1, 3):
            target = 20 if self.idx == 1 else 12
            frac = min(1.0, self.count / target)
            cv2.line(frame, (24, h - 30), (424, h - 30), HAIR, 2, cv2.LINE_AA)
            cv2.line(frame, (24, h - 30), (24 + int(400 * frac), h - 30),
                     PAPER, 2, cv2.LINE_AA)
        cv2.putText(frame, "n skip   t exit", (w - 200, h - 24), FONT, 0.45,
                    GREY, 1, cv2.LINE_AA)
        if app.state != Sleight.ARMED and self.idx > 0:
            cv2.putText(frame, "summon first: open palm + hold still",
                        (24, h - 142), FONT, 0.5, SILVER, 1, cv2.LINE_AA)
        if now < self.flash_until:
            draw_serif(frame, "nice.", (w // 2 - serif_w("nice.", 1.4, 2) // 2,
                                        96), 1.4, PAPER, 2, halo=True)


# --------------------------------------------------------------------------- vision engine

class HandEngine:
    """Google's modern HandLandmarker (Tasks, 2023 models) when the model file
    is present - the same class of tracking tech commercial products build on.
    Falls back to the legacy Solutions API automatically."""

    def __init__(self):
        self.kind = "legacy"
        self._last_ts = 0
        model = os.path.join(HERE, "hand_landmarker.task")
        if os.path.exists(model):
            try:
                from mediapipe.tasks import python as mp_python
                from mediapipe.tasks.python import vision as mp_vision
                base = mp_python.BaseOptions(model_asset_path=model)
                opts = mp_vision.HandLandmarkerOptions(
                    base_options=base,
                    running_mode=mp_vision.RunningMode.VIDEO,
                    num_hands=1,
                    min_hand_detection_confidence=0.6,
                    min_hand_presence_confidence=0.5,
                    min_tracking_confidence=0.5)
                self._lm = mp_vision.HandLandmarker.create_from_options(opts)
                self.kind = "tasks"
            except Exception as e:
                print(f"Modern engine unavailable ({e}) - using legacy tracker.")
        if self.kind == "legacy":
            self._hands = mp.solutions.hands.Hands(
                max_num_hands=1, model_complexity=1,
                min_detection_confidence=0.6, min_tracking_confidence=0.5)

    def process(self, rgb, now):
        """Returns (landmarks, world_landmarks, hand_label, score) or None."""
        if self.kind == "tasks":
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts = max(int(now * 1000), self._last_ts + 1)
            self._last_ts = ts
            r = self._lm.detect_for_video(img, ts)
            if not r.hand_landmarks or not r.hand_world_landmarks:
                return None
            label, score = "", 1.0
            if r.handedness and r.handedness[0]:
                label = r.handedness[0][0].category_name
                score = r.handedness[0][0].score
            return r.hand_landmarks[0], r.hand_world_landmarks[0], label, score
        res = self._hands.process(rgb)
        if not (res.multi_hand_landmarks and res.multi_hand_world_landmarks):
            return None
        label, score = "", 1.0
        try:
            c = res.multi_handedness[0].classification[0]
            label, score = c.label, c.score
        except (AttributeError, IndexError, TypeError):
            pass
        return (res.multi_hand_landmarks[0].landmark,
                res.multi_hand_world_landmarks[0].landmark, label, score)


def draw_hand(frame, lms, drawer, styles, w, h):
    """Monochrome skeleton: grey bones, silver joints, white fingertip rings.
    (drawer/styles args kept for call-site compatibility.)"""
    pts = [(int(l.x * w), int(l.y * h)) for l in lms]
    for a, b in mp.solutions.hands.HAND_CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], (96, 96, 96), 2, cv2.LINE_AA)
    for p in pts:
        cv2.circle(frame, p, 3, SILVER, -1, cv2.LINE_AA)
    for tip in (4, 8, 12, 16, 20):
        cv2.circle(frame, pts[tip], 10, PAPER, 1, cv2.LINE_AA)


# --------------------------------------------------------------------------- camera loop

def _handedness(res):
    try:
        c = res.multi_handedness[0].classification[0]
        return c.label, c.score
    except (AttributeError, IndexError, TypeError):
        return "", 1.0


def run_calibration(cap, engine, cfg, aspect):
    """Guided palm calibration. Returns 'ok', 'retry', or 'quit'.
    Only mutates cfg on success."""
    phases = [("Show your PALM to the camera", 1.4),
              ("Now show the BACK of your hand", 1.4)]
    means, labels = [], []
    for phase_idx, (label_text, seconds) in enumerate(phases):
        samples, t0 = [], None
        while True:
            ok, frame = cap.read()
            if not ok:
                cv2.waitKey(50)
                return "retry"
            frame = cv2.flip(frame, 1)
            r = engine.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                               time.time())
            frac, done = 0.0, False
            if r is not None:
                lms, world, hlabel, _hs = r
                obs = hand_obs(lms, world, aspect)
                if obs:
                    if t0 is None:
                        t0 = time.time()
                    samples.append(obs["nz"])
                    # ONLY the palm phase teaches chirality. MediaPipe reports
                    # a different label for the back of the same hand, so
                    # mixing both phases records a coin flip - and a wrong
                    # label silently inverts the palm test forever.
                    if phase_idx == 0:
                        labels.append(hlabel)
                    frac = min(1.0, (time.time() - t0) / seconds)
                    done = frac >= 1.0
                draw_hand(frame, lms, None, None, frame.shape[1],
                          frame.shape[0])

            # dark scrim FIRST: the camera is usually a bright wall, and light
            # type on a bright wall cannot be read
            band = frame.copy()
            cv2.rectangle(band, (0, 0), (frame.shape[1], 172), (0, 0, 0), -1)
            cv2.addWeighted(band, 0.62, frame, 0.38, 0, frame)
            draw_tracked(frame, f"CALIBRATION  {phase_idx + 1} / 2", (40, 50),
                         0.7, PAPER, 1, tracking=12, halo=True)
            draw_serif(frame, label_text, (40, 94), 0.85, PAPER, 1, halo=True)
            cv2.line(frame, (40, 122), (540, 122), HAIR, 3, cv2.LINE_AA)
            if frac > 0:
                cv2.line(frame, (40, 122), (40 + int(500 * frac), 122),
                         PAPER, 3, cv2.LINE_AA)
            seen_now = r is not None
            cv2.circle(frame, (44, 152), 5, PAPER if seen_now else HAIR, -1,
                       cv2.LINE_AA)
            cv2.putText(frame, "hand detected - hold it steady" if seen_now
                        else "no hand yet - hold it up, well lit",
                        (60, 157), FONT, 0.5, PAPER if seen_now else SILVER, 1,
                        cv2.LINE_AA)
            cv2.putText(frame, "q to cancel", (frame.shape[1] - 160, 157),
                        FONT, 0.45, GREY, 1, cv2.LINE_AA)
            cv2.imshow("Sleight", frame)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                return "quit"
            if done:
                means.append(sum(samples) / len(samples))
                break
    sign = calibrate_sign(means[0], means[1])
    if sign == 0.0:
        print("Calibration inconclusive - hand closer, better light. Retrying...")
        return "retry"
    cfg["palm_sign"] = sign
    # An unsteady label is worse than none: leave the guard off rather than
    # bake in a guess that inverts every future palm test.
    cfg["calibrated_hand"] = ""
    if labels:
        top = max(set(labels), key=labels.count)
        if top and labels.count(top) >= 0.8 * len(labels):
            cfg["calibrated_hand"] = top
    save_config(cfg)
    print(f"Calibrated: palm_sign={sign:+.0f} hand={cfg['calibrated_hand'] or '?'}")
    return "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    injector = Injector(dry_run=args.dry_run)

    cam = LatestFrameCamera(CAM_INDEX, CAM_W, CAM_H)
    if not cam.isOpened():
        sys.exit("Camera would not open - System Settings > Privacy & Security "
                 "> Camera -> enable your terminal.")

    engine = HandEngine()
    clf = GestureClassifier()
    print(f"poses: {'LEARNED from your hand (' + str(clf.n) + ' samples)' if clf.ok else 'built-in rules (run train_gestures.py to personalise)'}")
    print(f"vision engine: {engine.kind}"
          + (" (modern HandLandmarker)" if engine.kind == "tasks" else ""))
    _cw, _ch, _cf = cam.specs()
    print(f"camera: {_cw}x{_ch} negotiated at {_cf:.0f}fps "
          f"(asked for {CAM_FPS})")
    drawer = mp.solutions.drawing_utils
    styles = mp.solutions.drawing_styles

    cv2.namedWindow("Sleight", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Sleight", 960, 540)
    try:
        cv2.setWindowProperty("Sleight", cv2.WND_PROP_TOPMOST, 1)
    except cv2.error:
        pass

    aspect = CAM_W / CAM_H
    if cfg["palm_sign"] != 0.0 and not cfg.get("calibrated_hand"):
        print("Tip: your calibration predates the left/right-hand guard - "
              "press c once to recalibrate.")
    if cfg["palm_sign"] == 0.0:
        print("First run: palm calibration.")
        while True:
            r = run_calibration(cam, engine, cfg, aspect)
            if r == "ok":
                break
            if r == "quit":
                cam.release()
                cv2.destroyAllWindows()
                sys.exit("Calibration cancelled - Sleight needs it to run.")

    app = Sleight(cfg, injector, aspect)
    app.log({"event": "session_start", "config": cfg, "dry_run": injector.dry})
    print(__doc__)
    last_tick = 0.0
    toast, toast_until = None, 0.0

    # the floating glass widget - falls back to the plain window if AppKit
    # will not give us one
    menu_cmds = []
    pill_ui = PillUI()

    def remember_widget(x, y):
        """The user dropped the widget somewhere - that is where it lives."""
        cfg["widget_xy"] = [x, y]
        save_config(cfg)

    _STILL[0] = glass.reduce_motion()
    if _STILL[0]:
        print("Reduce Motion is on - the widget will hold still.")
    saved_xy = cfg.get("widget_xy")
    pill = glass.GlassPill(
        GLASS_W, GLASS_H, PILL_GAP_BOTTOM,
        menu=[("Full view / settings", "f"), ("Reset position", "p"),
              ("Tutorial", "t"), ("Recalibrate", "c"), ("-", ""),
              ("Quit Sleight", "q")],
        on_menu=lambda k: menu_cmds.append(k),
        on_drop=remember_widget,
        origin=tuple(saved_xy) if isinstance(saved_xy, (list, tuple))
        and len(saved_xy) == 2 else None)

    view = "panel"
    tutorial, tut_prev_dry = None, None
    if not cfg.get("tutorial_done"):
        tutorial = Tutorial()
        tut_prev_dry = injector.dry
        injector.dry = True            # learning can't touch the real system
        view = "full"
        cfg["tutorial_done"] = True    # auto-start ONCE, ever - an unfinished
        save_config(cfg)               # tutorial must never hijack next launch

    def show_view(v=None):
        """Keep the two surfaces in sync: the glass widget owns the everyday
        view, the plain window owns settings/tutorial/calibration."""
        vv = view if v is None else v
        pos = cfg.get("panel_pos", "center")
        if vv == "panel" and pill.ok:
            place_window("hidden")
            xy = cfg.get("widget_xy")
            if isinstance(xy, (list, tuple)) and len(xy) == 2:
                pill.set_origin(*xy)      # wherever you last put it
            else:
                pill.move_bottom(pos)
            pill.set_visible(True)
        else:
            pill.set_visible(False)
            place_window(vv, pos)

    show_view()

    def end_tutorial():
        nonlocal tutorial, view, toast, toast_until
        injector.set_dry(bool(tut_prev_dry))
        tutorial = None
        view = "panel"
        show_view()
        # short words only: the pill's word slot fits ~130px
        toast = "LIVE" if not injector.dry else "DRY RUN"
        toast_until = time.time() + 3.0
        if injector.dry:
            print("Still DRY-RUN - grant Accessibility (System Settings > "
                  "Privacy & Security) and press d.")

    last_seq = -1
    fps_ema = 30.0
    last_vision_t = time.time()
    while True:
        now = time.time()
        # high-rate output stage: the cursor and scroll glide toward their
        # targets every iteration (~100+Hz), not just on camera frames
        injector.glide_tick(now)

        seq, raw = cam.latest()
        if seq == last_seq or raw is None:
            time.sleep(0.002)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                break
            continue
        last_seq = seq
        frame = cv2.flip(raw, 1)
        h, w = frame.shape[:2]

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        r = engine.process(rgb, now)

        vis_dt = now - last_vision_t
        last_vision_t = now
        if 0 < vis_dt < 1:
            fps_ema = 0.9 * fps_ema + 0.1 * (1.0 / vis_dt)

        obs = None
        hand_lms = None
        if r is not None:
            lms, world, hlabel, hscore = r
            hand_lms = lms
            if view == "full":
                draw_hand(frame, lms, drawer, styles, w, h)
            obs = hand_obs(lms, world, aspect, clf)
            if obs:
                obs["hand_label"], obs["hand_score"] = hlabel, hscore

        events = app.step(obs, now)
        for event in events:
            app.log({"event": event})
            if event in TOASTS:
                toast, toast_until = TOASTS[event], now + TOAST_S
            if event == "arm":
                play("arm")
            elif event.startswith("disarm"):
                play("disarm")
            elif event == "click":
                play("click")
            elif event.startswith("drag"):
                play("action")
            elif event.startswith("swipe"):
                play("action")
            elif event == "scroll" and now - last_tick > SCROLL_TICK_S:
                play("action")
                last_tick = now

        if tutorial is not None:
            tutorial.update(events, now)
            if tutorial.done and now >= tutorial.flash_until:
                end_tutorial()

        if now >= toast_until:
            toast = None
        active = app.pose_stab.current if (obs and app.state == Sleight.ARMED) else None
        if app.state == Sleight.ARMED and app.pincher.state != PinchTracker.OPEN:
            active = "hold" if app.pincher.state == PinchTracker.DRAG else "pinch"

        if view == "full":
            if app.pointer_on and obs:
                # screen-mapping box: fingertip position inside = cursor position
                x0, x1, y0, y1 = app.pointer.box()
                cv2.rectangle(frame, (int(x0 * w), int(y0 * h)),
                              (int(x1 * w), int(y1 * h)), PAPER, 1)
                cx_, cy_ = int(obs["ix"] * w), int(obs["iy"] * h)
                cv2.circle(frame, (cx_, cy_), 8, PAPER, -1, cv2.LINE_AA)
                cv2.circle(frame, (cx_, cy_), 9, (0, 0, 0), 1, cv2.LINE_AA)
            draw_guide(frame, active, now, w, h)
            draw_hud(frame, app, toast, now, w, h)
            cv2.putText(frame, f"{engine.kind}   cam {cam.cap_fps:.0f}   "
                               f"track {fps_ema:.0f}   {(active or '-')}",
                        (w - 630, 36), FONT, 0.45, GREY, 1, cv2.LINE_AA)
            if tutorial is not None:
                tutorial.draw(frame, app, now, w, h)
            cv2.imshow("Sleight", frame)
        elif pill.ok:
            rgba, rect, chip = render_pill_rgba(app, obs, active, toast, now,
                                                hand_lms, pill_ui,
                                                scale=PILL_SS)
            pill.set_pill(*rect)
            pill.set_chip(chip)
            pill.paint(rgba, scale=PILL_SS)
            # grabbable on the widget itself, click-through everywhere else
            pill.update_hit([rect] + ([chip] if chip else []))
            pill.tick(0.0)
        else:
            cv2.imshow("Sleight", render_panel(app, obs, active, toast, now,
                                               lms=hand_lms))

        k = cv2.waitKey(1) & 0xFF
        if menu_cmds:                      # the menu bar is the widget's
            cmd = menu_cmds.pop(0)         # control surface: a borderless
            if cmd:                        # window must never take focus
                k = ord(cmd)
        if k == ord("q"):
            break
        elif k == ord("f"):
            if tutorial is None:      # the tutorial owns the full view -
                view = "full" if view == "panel" else "panel"   # else its UI
                show_view()           # vanishes while it keeps running (and
                # keeps the injector forced dry)
        elif k == ord("p"):               # put it back where it started
            cfg["widget_xy"] = None
            cfg["panel_pos"] = "center"
            save_config(cfg)
            if view == "panel":
                show_view()
        elif k == ord("t"):
            if tutorial is None:
                tutorial = Tutorial()
                tut_prev_dry = injector.dry
                injector.dry = True
                view = "full"
                show_view()
            else:
                end_tutorial()
        elif k == ord("n") and tutorial is not None:
            tutorial.skip_step(now)
        elif k == ord("x"):
            app.mark_false()
        elif k == ord("v"):
            cfg["scroll_flip"] = not cfg["scroll_flip"]
            save_config(cfg)
        elif k == ord("d"):
            was_dry = injector.dry
            injector.set_dry(not injector.dry)
            if injector.dry != was_dry:
                app.log({"event": "injector_mode",
                         "dry": injector.dry})
        elif k == ord("r"):
            for key in app.stats:
                app.stats[key] = 0
        elif k == ord("["):
            cfg["still_tol"] = max(0.05, cfg["still_tol"] - 0.03)
            save_config(cfg)
        elif k == ord("]"):
            cfg["still_tol"] = min(1.0, cfg["still_tol"] + 0.03)
            save_config(cfg)
        elif k == ord("c"):
            show_view("full")         # calibration needs the camera view
            while True:
                r = run_calibration(cam, engine, cfg, aspect)
                if r == "ok":
                    app.gate = Gate(cfg)
                    break
                if r == "quit":       # keep the previous calibration
                    break
            show_view()

    pill.close()
    cam.release()
    cv2.destroyAllWindows()
    app.report()


if __name__ == "__main__":
    main()
