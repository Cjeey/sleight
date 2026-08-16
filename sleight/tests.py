"""Headless logic tests for sleight.py - no camera, no Quartz posting."""
import importlib.util
import math
import time

spec = importlib.util.spec_from_file_location("sl", __file__.replace("tests.py", "sleight.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

BASE = time.time()
ASPECT = m.CAM_W / m.CAM_H
DT = 1 / 30


class P:
    def __init__(s, x, y, z=0.0):
        s.x, s.y, s.z = x, y, z


def mk_hand(pose="palm", cx=0.5, cy=0.45, scale=0.10, palm_out=True):
    lm = [P(cx, cy) for _ in range(21)]
    lm[m.WRIST] = P(cx, cy + scale / 2)
    lm[m.MIDDLE_MCP] = P(cx, cy - scale / 2)
    lm[m.INDEX_MCP] = P(cx - 0.03, cy - scale / 2)
    lm[m.PINKY_MCP] = P(cx + 0.03, cy - scale / 2)
    wrist_y = cy + scale / 2

    if pose == "tipinch":
        # thumb+index tips touching, index REACHING out (~1.2 hand-widths),
        # middle/ring/pinky curled - the click gesture
        tx, ty = cx, wrist_y - scale * 1.2
        lm[m.THUMB_TIP] = P(tx, ty)
        lm[m.TIPS["index"]] = P(tx + 0.002, ty)
        lm[m.PIPS["index"]] = P(tx, wrist_y - scale * 0.8)
        for f in ["middle", "ring", "pinky"]:
            lm[m.PIPS[f]] = P(cx, wrist_y - scale * 0.7)
            lm[m.TIPS[f]] = P(cx, wrist_y - scale * 0.5)
    else:
        lm[m.THUMB_TIP] = P(cx - scale * 1.2, cy)   # thumb far out of the way
        ext = {"palm": ["index", "middle", "ring", "pinky"],
               "two": ["index", "middle"],
               "point": ["index"],
               "sidepinch": ["index"],
               "holdpinch": ["index"],
               "steer": ["middle", "ring", "pinky"],
               "steerpinch": ["middle", "ring", "pinky"],
               "fist": []}[pose]
        for i, f in enumerate(["index", "middle", "ring", "pinky"]):
            fx = cx - 0.03 + i * 0.02
            if f in ext:
                lm[m.PIPS[f]] = P(fx, wrist_y - scale * 0.9)
                lm[m.TIPS[f]] = P(fx, wrist_y - scale * 1.6)
            else:
                lm[m.PIPS[f]] = P(fx, wrist_y - scale * 0.7)
                lm[m.TIPS[f]] = P(fx, wrist_y - scale * 0.5)
        if pose == "fist":
            # thumb wraps over the curled fingers - tips end up NEAR the thumb
            # (this is exactly the geometry that fooled the all-tips click)
            lm[m.THUMB_TIP] = P(cx, wrist_y - scale * 0.55)
        elif pose == "sidepinch":
            # thumb resting on the MIDDLE of the index finger, not the tip
            lm[m.THUMB_TIP] = P(lm[m.PIPS["index"]].x + 0.001,
                                lm[m.PIPS["index"]].y)
        elif pose == "holdpinch":
            # thumb pressed to the curled PINKY fingertip; index stays up
            lm[m.THUMB_TIP] = P(lm[m.TIPS["pinky"]].x + 0.012,
                                lm[m.TIPS["pinky"]].y)
        elif pose == "steerpinch":
            # index curled down onto the thumb while middle+ring steer
            lm[m.THUMB_TIP] = P(lm[m.TIPS["index"]].x + 0.001,
                                lm[m.TIPS["index"]].y)

    for f, tip_i in m.TIPS.items():                 # fill DIP joints (tip-1)
        pip_i = m.PIPS[f]
        lm[tip_i - 1] = P((lm[pip_i].x + lm[tip_i].x) / 2,
                          (lm[pip_i].y + lm[tip_i].y) / 2)

    w = [P(0, 0, 0) for _ in range(21)]
    w[m.WRIST] = P(0, 0, 0)
    if palm_out:
        w[m.INDEX_MCP] = P(0.05, -0.08, 0)
        w[m.PINKY_MCP] = P(-0.05, -0.08, 0)
    else:
        w[m.INDEX_MCP] = P(-0.05, -0.08, 0)
        w[m.PINKY_MCP] = P(0.05, -0.08, 0)
    return lm, w


_raw = m.hand_obs(*mk_hand("palm"), ASPECT)
PSIGN = 1.0 if _raw["nz"] > 0 else -1.0


def obs(pose="palm", cx=0.5, cy=0.45, scale=0.10, palm_out=True,
        label="Right", score=0.95):
    o = m.hand_obs(*mk_hand(pose, cx, cy, scale, palm_out), ASPECT)
    assert o is not None
    o["hand_label"], o["hand_score"] = label, score
    return o


def cfg_ok(**kw):
    c = dict(m.DEFAULT_CONFIG)
    c["palm_sign"] = PSIGN
    c["calibrated_hand"] = "Right"
    c.update(kw)
    return c


def drive(app, o, frames, t):
    evs = []
    for _ in range(frames):
        evs += app.step(o, t)
        t += DT
    return evs, t


# ---- 1. pose classification + click signals
assert obs("palm")["pose"] == "palm"
assert obs("two")["pose"] == "two"
assert obs("point")["pose"] == "point"
assert obs("fist")["pose"] == "fist"
o = obs("tipinch")
assert o["pose"] == "point", o["pose"]
assert o["ti_ratio"] < m.PINCH_ON
om = obs("holdpinch")
assert om["pose"] == "point" and om["hold_ratio"] < m.PINCH_ON
assert om["ti_ratio"] > m.PINCH_OFF, "holdpinch must not read as a click"
of = obs("fist")
assert of["ti_ratio"] < m.PINCH_OFF, "fist LOOKS like a pinch by distance"
assert of["pose"] == "fist", "but the fist pose keeps it inert"
print("1. pose classification + pinch/fist separation OK")

# ---- 2. pose stabilizer: change needs 3 frames
st = m.PoseStabilizer()
for _ in range(5):
    assert st.update("palm") in (None, "palm")
assert st.current == "palm"
assert st.update("two") == "palm"      # 1 frame - not yet
assert st.update("two") == "palm"      # 2 frames - not yet
assert st.update("two") == "two"       # 3 frames - now
assert st.update("palm") == "two"      # single flicker back ignored
assert st.update("two") == "two"
assert st.update(None) == "two"        # unclassifiable pose keeps the gesture
assert st.update(None) == "two"
assert st.update("two") == "two"
print("2. pose stabilizer OK")

# ---- 3. gate: chirality
g = m.Gate(cfg_ok())
g.last_fail_t = BASE - 10
t = BASE
armed = 0
for _ in range(50):        # 1.67s: one arm at ~0.8s, re-arm gap not yet elapsed
    t += DT
    if g.update(obs("palm"), t, ASPECT):
        armed += 1
        g.last_fail_t = t
assert armed == 1, armed
# other hand, same palm_out geometry -> normal flips -> must NOT arm
g2 = m.Gate(cfg_ok())
g2.last_fail_t = BASE - 10
t = BASE
a = 0
for _ in range(80):
    t += DT
    if g2.update(obs("palm", label="Left"), t, ASPECT):
        a += 1
assert a == 0, "other hand armed - chirality guard failed"
# other hand with palm flipped -> normal matches again -> arms
g3 = m.Gate(cfg_ok())
g3.last_fail_t = BASE - 10
t = BASE
a = 0
for _ in range(50):
    t += DT
    if g3.update(obs("palm", palm_out=False, label="Left"), t, ASPECT):
        a += 1
        g3.last_fail_t = t
assert a == 1, "flipped other hand should arm"
# low handedness score -> FAIL OPEN. This used to block, which meant a shaky
# chirality reading on the user's OWN hand locked them out of the app with no
# way to see why. The pose classifier still has to agree it is a palm, and a
# CONFIDENT mirror hand still flips (g2/g3 above), so the guard is intact.
g4 = m.Gate(cfg_ok())
g4.last_fail_t = BASE - 10
t = BASE
a = 0
for _ in range(50):        # same 1.67s window as the baseline arm above
    t += DT
    if g4.update(obs("palm", score=0.4), t, ASPECT):
        a += 1
        g4.last_fail_t = t
assert a == 1, "an unsure handedness score must not veto the user's own palm"
print("3. gate chirality + score guard OK")

# ---- 4. flick: fire, return-stroke, dropout survives, teleport, diagonal
fl = m.FlickDetector("two", "x")
t = BASE
fired = []
for i in range(11):
    d = fl.update(obs("two", cx=0.35 + i * 0.02), t)
    t += DT
    if d:
        fired.append(d)
assert fired == ["pos"], fired
fl.reset()                              # simulate one-frame dropout
assert fl.require_rest, "dropout cleared return-stroke suppression!"
for i in range(11):                     # return stroke after dropout
    assert fl.update(obs("two", cx=0.55 - i * 0.02), t) is None
    t += DT
for i in range(20):
    fl.update(obs("two", cx=0.35), t)
    t += DT
t += 0.8
for i in range(20):
    fl.update(obs("two", cx=0.35), t)
    t += DT
fired2 = []
for i in range(11):
    d = fl.update(obs("two", cx=0.35 - i * 0.02), t)
    t += DT
    if d:
        fired2.append(d)
assert fired2 == ["neg"], fired2
print("4. flick fire + dropout-proof suppression OK")

# 4b. teleport: single big jump truncates history, never fires
fl2 = m.FlickDetector("two", "x")
t = BASE + 100
for i in range(10):
    fl2.update(obs("two", cx=0.35), t)
    t += DT
assert fl2.update(obs("two", cx=0.60), t) is None
t += DT
for i in range(10):
    assert fl2.update(obs("two", cx=0.60), t) is None
    t += DT
print("4b. teleport rejection OK")

# 4c. diagonal motion rejected (palm withdrawal)
fl3 = m.FlickDetector("palm", "y")
t = BASE + 200
for i in range(11):
    d = fl3.update(obs("palm", cx=0.5 + i * 0.02, cy=0.45 + i * 0.02), t)
    assert d is None, "diagonal fired a flick"
    t += DT
print("4c. diagonal rejection OK")

# 4d. a REALISTIC fast flick: non-uniform velocity peaking at 0.8 hw/frame
# (the old 0.6 step cap rejected exactly this stroke)
fl4 = m.FlickDetector("two", "x")
t = BASE + 300
xpos = 0.30
fired4 = []
for step in (0.005, 0.02, 0.05, 0.08, 0.08, 0.05, 0.02):
    xpos += step
    d = fl4.update(obs("two", cx=xpos), t)
    t += DT
    if d:
        fired4.append(d)
assert fired4 == ["pos"], f"fast peaked flick: {fired4}"
print("4d. fast peaked flick fires OK")

# 4e. one-frame tracking dropout mid-flick must NOT kill the stroke (app level)
appd = m.Sleight(cfg_ok(), m.Injector(dry_run=True))
appd.gate.last_fail_t = BASE - 10
t = BASE
evs, t = drive(appd, obs("palm"), 60, t)
assert appd.state == appd.ARMED
t += 0.6
evs, t = drive(appd, obs("palm", cx=0.32), 10, t)
evs = []
xpos = 0.32
for i, step in enumerate((0.02, 0.03, 0.04, 0.0, 0.04, 0.03, 0.02, 0.02)):
    if i == 3:
        evs += appd.step(None, t)                         # blur frame: hand lost
    else:
        xpos += step
        evs += appd.step(obs("palm", cx=xpos), t)
    t += DT
assert any(e.startswith("swipe") for e in evs), \
    f"dropout mid-flick killed the stroke: {evs}"
print("4e. mid-flick dropout survives OK")

# ---- 5. scroll: position control - the page follows the hand
c5 = cfg_ok()
sc = m.ScrollController(c5)
t = BASE
sc.update(obs("two", cy=0.50), t)                        # seed
total = 0
for i in range(1, 21):                                   # up 0.1 = 1 hand-width
    t += DT
    total += sc.update(obs("two", cy=0.50 - i * 0.005), t)
for _ in range(8):                                       # flush liftoff buffer
    t += DT
    total += sc.update(obs("two", cy=0.40), t)
assert -1000 < total < -630, f"position-control travel off: {total}"
# moving back down returns roughly the same distance the other way
back = 0
for i in range(1, 21):
    t += DT
    back += sc.update(obs("two", cy=0.40 + i * 0.005), t)
for _ in range(8):
    t += DT
    back += sc.update(obs("two", cy=0.50), t)
assert 500 < back < 980, f"return travel off: {back}"   # filter lag at reversal
# stationary hand emits ~nothing once the filter settles (deadband kills tremor)
for _ in range(10):                                       # let the filter settle
    t += DT
    sc.update(obs("two", cy=0.50), t)
still = 0
for _ in range(20):
    t += DT
    still += sc.update(obs("two", cy=0.50), t)
assert still == 0, f"stationary hand scrolled: {still}"

# LIFTOFF: the release motion never scrolls - exit mid-motion drops the tail
scl = m.ScrollController(c5)
t = BASE + 40
scl.update(obs("two", cy=0.50), t)
out_moving = 0
for i in range(1, 5):                                     # 4 fast frames of lift
    t += DT
    out_moving += scl.update(obs("two", cy=0.50 - i * 0.02), t)
t += DT
out_exit = scl.update(obs("point"), t)                    # fingers released
# frames younger than 0.1s were pending and must be discarded at release
assert len(scl.pending) == 0
full_travel = 0.08 / 0.1 * m.SCROLL_PX_PER_HW             # px if all delivered
delivered = abs(out_moving) + abs(out_exit if abs(out_exit) < 100 else 0)
assert delivered < full_travel * 0.6, \
    f"release tail was delivered: {delivered:.0f}px of {full_travel:.0f}px"
print("5b. liftoff cancellation OK")
# pose flicker: first frame back contributes ZERO delta (no jump)
sc3 = m.ScrollController(c5)
t = BASE + 60
sc3.update(obs("two", cy=0.50), t)
t += DT
sc3.update(obs("two", cy=0.49), t)
t += DT
sc3.update(None, t)                                      # lost frame
t += DT
jump = sc3.update(obs("two", cy=0.30), t)              # reappears far away
assert jump == 0, f"flicker reappearance jumped: {jump}"
# flip inverts
sc5 = m.ScrollController(cfg_ok(scroll_flip=True))
t = BASE + 80
sc5.update(obs("two", cy=0.50), t)
tot = 0
for i in range(1, 11):
    t += DT
    tot += sc5.update(obs("two", cy=0.50 - i * 0.005), t)
assert tot > 0
print("5. scroll position-control + deadband + flicker-proof + flip OK")

# ---- 6. pointer: follow-box - anchored to the hand, dead zones impossible
pt = m.PointerController(cfg_ok(), ASPECT)
t = BASE
pos = pt.update(obs("point", cx=0.5), t)
# starting to point continues from where the cursor already was (0.5, 0.5)
assert abs(pos[0] - 0.5) < 1e-6 and abs(pos[1] - 0.5) < 1e-6, pos
# fingertip right by 0.10 = a quarter of the box -> cursor +0.25
for _ in range(15):
    t += DT
    pos = pt.update(obs("point", cx=0.60), t)
assert abs(pos[0] - 0.75) < 0.05, f"proportional mapping off: {pos[0]}"
# push far past the right edge: cursor pins at 1.0 and the box DRAGS along
for _ in range(15):
    t += DT
    pos = pt.update(obs("point", cx=0.95), t)
assert pos[0] > 0.97, f"edge pin failed: {pos[0]}"
box_after_push = pt.box()
assert box_after_push[1] >= 0.90, f"box did not drag: {box_after_push}"
# now move LEFT slightly - control responds IMMEDIATELY, no dead zone
for _ in range(10):
    t += DT
    pos = pt.update(obs("point", cx=0.89), t)
assert pos[0] < 0.93, f"dead zone after edge push: {pos[0]}"
# release, re-point somewhere completely different: cursor does NOT jump
last = pt.last_out
assert pt.update(obs("palm"), t) is None
t += 0.5
pos = pt.update(obs("point", cx=0.25), t)
assert abs(pos[0] - last[0]) < 0.02 and abs(pos[1] - last[1]) < 0.02, \
    f"re-anchor jumped: {last} -> {pos}"
# velocity lead: while the hand moves at constant speed, the cursor runs
# AHEAD of the plain filtered position - and settles exactly when it stops
pt2 = m.PointerController(cfg_ok(), ASPECT)
t2 = BASE + 50
pt2.update(obs("point", cx=0.40), t2)
led = None
for i in range(1, 9):
    t2 += DT
    led = pt2.update(obs("point", cx=0.40 + i * 0.01), t2)
raw_sx = (obs("point", cx=0.48)["ix"] - pt2.bx0) / m.CONTROL_W
assert led[0] > raw_sx, f"no lead during motion: {led[0]:.3f} <= {raw_sx:.3f}"
for _ in range(20):                                       # hand stops
    t2 += DT
    led = pt2.update(obs("point", cx=0.48), t2)
assert abs(led[0] - raw_sx) < 0.02, f"did not settle on target: {led[0]:.3f}"
# pinch invariance: pointing and pinching at the same hand position give the
# SAME cursor anchor - clicking cannot displace the cursor off a small target
o_pt = obs("point", cx=0.5)
o_pn = obs("tipinch", cx=0.5)
assert abs(o_pt["ix"] - o_pn["ix"]) < 1e-9 and abs(o_pt["iy"] - o_pn["iy"]) < 1e-9, \
    "pinch moved the cursor anchor!"
print("6. pointer absolute mapping + clamping + pinch-invariant anchor OK")

# ---- 6b. click fires ON CONTACT; middle touch = hold; fist immune
ptk = m.PinchTracker()
t = BASE
o_click = obs("tipinch")
o_hold = obs("holdpinch")
o_open = obs("point")
evs = []
for _ in range(m.CLICK_PRESS_FRAMES):
    evs += ptk.update(o_click, t)
    t += DT
assert evs == ["tap"], f"click did not fire on contact: {evs}"
assert ptk.state == ptk.CLICKED
# holding the touch fires nothing more, and releasing fires nothing more
for _ in range(40):
    assert ptk.update(o_click, t) == [], "repeat fire while held"
    t += DT
assert ptk.update(o_open, t) == [], "release produced an extra event"
t += DT
t += m.CLICK_REFRACTORY_S
# second click also fires on contact
evs = []
for _ in range(m.CLICK_PRESS_FRAMES):
    evs += ptk.update(o_click, t)
    t += DT
assert evs == ["tap"]
assert ptk.update(o_open, t) == []
t += DT
t += m.CLICK_REFRACTORY_S
# MIDDLE touch = hold: down on contact, up on release
evs = []
for _ in range(m.CLICK_STABLE_FRAMES):
    evs += ptk.update(o_hold, t)
    t += DT
assert "down" in evs and ptk.state == ptk.DRAG
assert ptk.update(o_open, t) == ["up"]
t += DT
t += m.CLICK_REFRACTORY_S
# pose collapse mid-touch cannot cancel an in-flight click
evs = []
for _ in range(m.CLICK_PRESS_FRAMES):
    evs += ptk.update(o_click, t)
    t += DT
assert evs == ["tap"]
fist_like = dict(obs("fist"))
fist_like["ti_ratio"] = 0.2
fist_like["hold_ratio"] = 1.0
for _ in range(10):
    assert ptk.update(fist_like, t) == []
    t += DT
assert ptk.state == ptk.CLICKED
# a cold fist can never click: allow_start=False blocks entry
ptk2 = m.PinchTracker()
tf = BASE + 80
for _ in range(30):
    assert ptk2.update(obs("fist"), tf, allow_start=False) == []
    tf += DT
assert ptk2.state == ptk2.OPEN
# hand lost mid-hold releases the button
ptk3 = m.PinchTracker()
t3 = BASE + 90
for _ in range(m.CLICK_STABLE_FRAMES):
    ptk3.update(o_hold, t3)
    t3 += DT
assert ptk3.state == ptk3.DRAG
assert ptk3.update(None, t3) == ["up"]
print("6b. click-on-contact / middle-hold / collapse-tolerant OK")

# ---- 6c. a fist does NOTHING while armed (no disarm gesture exists)
appf = m.Sleight(cfg_ok(), m.Injector(dry_run=True))
appf.gate.last_fail_t = BASE - 10
t = BASE
evs, t = drive(appf, obs("palm"), 60, t)
assert appf.state == appf.ARMED
evs, t = drive(appf, obs("fist"), 60, t)                  # 2s of held fist
assert appf.state == appf.ARMED, "fist disarmed - it should be inert"
assert not any(e.startswith("disarm") for e in evs), evs
print("6c. fist is inert (timeout is the only stop) OK")

# ---- 7. injector: set_dry guards, pruned keycodes, config validation
inj = m.Injector(dry_run=True)
inj.scroll(-42)
inj.key("left")
inj.move_to(0.5, 0.5)
inj.click()
assert ("scroll", -42) in inj.posted and ("key", "left") in inj.posted
assert ("moveto", 0.5, 0.5) in inj.posted
assert ("click",) in inj.posted
assert "space" not in m.KEY_ACTIONS and "home" not in m.KEY_ACTIONS
if m.Quartz is None:
    assert inj.set_dry(False) is True, "went LIVE without Quartz!"
bad = dict(m.DEFAULT_CONFIG)
bad["swipe_left_key"] = "space"
import json as _json
import os as _os
_p = m.CONFIG_PATH
_bak = open(_p).read() if _os.path.exists(_p) else None
with open(_p, "w") as f:
    _json.dump(bad, f)
loaded = m.load_config()
assert loaded["swipe_left_key"] == "forward", "invalid key mapping not rejected"
if _bak is not None:
    open(_p, "w").write(_bak)
else:
    _os.remove(_p)
print("7. injector guards + config validation OK")

# ---- 8. full pipeline: arm -> point -> click -> scroll -> flick -> fist
app = m.Sleight(cfg_ok(), m.Injector(dry_run=True))
app.gate.last_fail_t = BASE - 10
t = BASE
evs, t = drive(app, obs("palm"), 60, t)
assert "arm" in evs and app.state == app.ARMED, evs
t += m.POST_ARM_GRACE_S                                   # clear the grace
evs, t = drive(app, obs("point", cx=0.50), 4, t)            # stabilize pose
evs = []
for i in range(6):
    evs += app.step(obs("point", cx=0.50 + i * 0.01), t)
    t += DT
assert "pointer" in evs and any(p[0] == "moveto" for p in app.injector.posted)
evs, t = drive(app, obs("tipinch"), 4, t)                 # contact -> CLICK now
assert "click" in evs and ("click",) in app.injector.posted
moves_before = sum(1 for p in app.injector.posted if p[0] == "moveto")
t += m.CLICK_FREEZE_S + 0.05
evs = []
for i in range(1, 9):                                     # slide WHILE touching
    evs += app.step(obs("tipinch", cx=0.52 + i * 0.02), t)
    t += DT
moves_mid = sum(1 for p in app.injector.posted if p[0] == "moveto")
assert moves_mid > moves_before, "cursor must keep moving during the touch"
assert not any(e.startswith("drag") for e in evs), "slide started a drag"
evs, t = drive(app, obs("point", cx=0.68), 3, t)          # part the fingers
t += m.CLICK_FREEZE_S + 0.05
evs = []
for i in range(8):                                        # click and go
    evs += app.step(obs("point", cx=0.56 + i * 0.015), t)
    t += DT
moves_after = sum(1 for p in app.injector.posted if p[0] == "moveto")
assert moves_after > moves_mid, "cursor stayed dead after the click!"
# thumb + MIDDLE = hold -> drag: grab, move, release
t += m.CLICK_REFRACTORY_S
evs2, t = drive(app, obs("holdpinch", cx=0.60), 5, t)      # middle touch
assert "drag_start" in evs2 and ("down",) in app.injector.posted
moves_d0 = sum(1 for p in app.injector.posted if p[0] == "moveto")
evs3 = []
for i in range(6):                                        # move while held = drag
    evs3 += app.step(obs("holdpinch", cx=0.60 + i * 0.02), t)
    t += DT
assert sum(1 for p in app.injector.posted if p[0] == "moveto") > moves_d0, \
    "cursor frozen during drag"
evs4, t = drive(app, obs("point", cx=0.72), 3, t)           # release = drop
assert "drag_end" in evs4 and ("up",) in app.injector.posted
t += 1.0                                                  # clear click lockout
evs, t = drive(app, obs("two", cy=0.45), 5, t)          # stabilize + seed
evs = []
for i in range(1, 16):
    evs += app.step(obs("two", cy=0.45 - i * 0.006), t)
    t += DT
assert "scroll" in evs and any(p[0] == "scroll" for p in app.injector.posted)
t += 0.8                                                  # refractory + rest
evs, t = drive(app, obs("palm", cx=0.35), 10, t)          # settle in palm
evs = []
for i in range(11):                                       # whole-palm flick
    evs += app.step(obs("palm", cx=0.35 + i * 0.02), t)
    t += DT
assert "swipe_right" in evs, evs
assert ("key", "back") in app.injector.posted
evs, t = drive(app, None, 220, t)                         # lower the hand
assert "disarm_timeout" in evs and app.state == app.IDLE
assert app.stats["arms"] == 1 and app.stats["arms_no_action"] == 0
print("8. pipeline arm->point->click->scroll->flick->timeout OK")

# ---- 9. the CLUTCH: returning to the middle in a non-scroll pose = no scroll
app2 = m.Sleight(cfg_ok(), m.Injector(dry_run=True))
app2.gate.last_fail_t = BASE - 10
t = BASE
evs, t = drive(app2, obs("palm"), 60, t)
assert app2.state == app2.ARMED
t += 0.5
evs, t = drive(app2, obs("two", cy=0.55), 5, t)         # grip + seed
for i in range(1, 11):                                    # slow scroll up
    app2.step(obs("two", cy=0.55 - i * 0.004), t)
    t += DT
before = sum(1 for p in app2.injector.posted if p[0] == "scroll")
evs = []                                                  # clutch: point pose,
for i in range(15):                                       # hand returns down
    evs += app2.step(obs("point", cy=0.51 + i * 0.01), t)
    t += DT
after_posts = [p for p in app2.injector.posted if p[0] == "scroll"][before:]
# the 3-frame pose debounce may leak a frame or two of ~1px tail; what must
# NOT happen is the return trip scrolling meaningfully in either direction
assert len(after_posts) <= 3 and sum(abs(p[1]) for p in after_posts) < 10, \
    f"clutched return still scrolled: {after_posts}"
print("9. clutch: return trip scrolls ~nothing OK")

# ---- 10. flick -> momentum coast, cancelled by re-grip
app3 = m.Sleight(cfg_ok(), m.Injector(dry_run=True))
app3.gate.last_fail_t = BASE - 10
t = BASE
evs, t = drive(app3, obs("palm"), 60, t)
t += 0.5
evs, t = drive(app3, obs("two", cy=0.60), 5, t)
for i in range(1, 9):                                     # FAST sweep up
    app3.step(obs("two", cy=0.60 - i * 0.03), t)
    t += DT
before = sum(1 for p in app3.injector.posted if p[0] == "scroll")
coast_evs = []
for i in range(60):                                       # release into point;
    coast_evs += app3.step(obs("point"), t)               # 0.93^60 -> ~1% left
    t += DT
after = sum(1 for p in app3.injector.posted if p[0] == "scroll")
assert after > before, "no momentum after fast flick"
assert app3.scroll.coast == 0.0 or abs(app3.scroll.coast) < 6, \
    "coast never decays"
evs, t = drive(app3, obs("two", cy=0.40), 4, t)           # re-grip cancels
assert not app3.scroll.coasting
print("10. flick momentum + re-grip cancel OK")

# ---- 11. x-mark attribution + arm_end logging fields
app4 = m.Sleight(cfg_ok(), m.Injector(dry_run=True))
app4.gate.last_fail_t = BASE - 10
app4.log = lambda payload: logged.append(payload)
logged = []
t = BASE
evs, t = drive(app4, obs("palm"), 60, t)
app4.mark_false()
assert app4.x_this_arm is True
evs, t = drive(app4, None, 400, t)
ends = [p for p in logged if p.get("event") == "arm_end"]
assert ends and ends[0]["x_marked"] is True and ends[0]["actions"] == 0
print("11. x-mark attribution + arm_end log OK")

# ---- 12. separation: cursor pose never scrolls, scroll pose never flicks
app5 = m.Sleight(cfg_ok(), m.Injector(dry_run=True))
app5.gate.last_fail_t = BASE - 10
t = BASE
evs, t = drive(app5, obs("palm"), 60, t)
assert app5.state == app5.ARMED
t += 0.6
evs, t = drive(app5, obs("two", cy=0.5), 8, t)
keys_before = sum(1 for p in app5.injector.posted if p[0] == "key")
for i in range(11):                                       # two-finger horizontal yank
    app5.step(obs("two", cx=0.35 + i * 0.02, cy=0.5), t)
    t += DT
assert sum(1 for p in app5.injector.posted if p[0] == "key") == keys_before, \
    "scroll pose fired back/next!"
t += 0.8
evs, t = drive(app5, obs("point", cx=0.5, cy=0.6), 8, t)  # cursor pose
sb = sum(1 for p in app5.injector.posted if p[0] == "scroll")
for i in range(1, 12):                                    # cursor moves vertically
    app5.step(obs("point", cy=0.6 - i * 0.02), t)
    t += DT
assert sum(1 for p in app5.injector.posted if p[0] == "scroll") == sb, \
    "cursor motion scrolled!"
t += 0.8
evs, t = drive(app5, obs("palm", cy=0.60), 10, t)         # palm vertical
sb2 = sum(1 for p in app5.injector.posted if p[0] == "scroll")
for i in range(1, 12):
    app5.step(obs("palm", cy=0.60 - i * 0.02), t)
    t += DT
assert sum(1 for p in app5.injector.posted if p[0] == "scroll") == sb2, \
    "palm motion scrolled!"
print("12. point=cursor, two=scroll, palm=flick separation OK")

# ---- 13. tutorial progression + panel render
tut = m.Tutorial()
t = BASE
tut.update(["arm"], t)
assert tut.idx == 1
for _ in range(20):
    tut.update(["pointer"], t)
assert tut.idx == 2, tut.idx
tut.update(["click"], t)
assert tut.idx == 3
for _ in range(12):
    tut.update(["scroll"], t)
assert tut.idx == 4
tut.update(["swipe_left"], t)
assert tut.done
tut2 = m.Tutorial()                                       # manual skip path
for _ in range(5):
    tut2.skip_step(t)
assert tut2.done
import numpy as _np
app6 = m.Sleight(cfg_ok(), m.Injector(dry_run=True))
canvas = m.render_panel(app6, None, None, None, BASE)          # no camera
assert canvas.shape == (m.PANEL_H * m.PILL_SS, m.PANEL_W * m.PILL_SS, 3)
fake_cam = _np.full((720, 1280, 3), 90, dtype=_np.uint8)
canvas = m.render_panel(app6, None, None, None, BASE, thumb=fake_cam)
assert canvas.shape == (m.PANEL_H * m.PILL_SS, m.PANEL_W * m.PILL_SS, 3)
app6.state = app6.ARMED
app6.armed_until = BASE + 5
canvas = m.render_panel(app6, obs("point"), "point", "CLICK", BASE,
                        thumb=fake_cam)
assert canvas.shape == (m.PANEL_H * m.PILL_SS, m.PANEL_W * m.PILL_SS, 3) and canvas.max() > 100
print("13. tutorial progression + panel render OK")

# ---- 14. glide + wheel smoother (the high-rate output stage)
gl = m.Glide(tau=0.04)
t = BASE
p = gl.tick((0.5, 0.5), t)
assert p == (0.5, 0.5)                                    # first tick snaps
for i in range(60):                                       # chase a new target
    t += 1 / 120
    p = gl.tick((0.9, 0.2), t)
assert abs(p[0] - 0.9) < 0.01 and abs(p[1] - 0.2) < 0.01, p
# no overshoot ever: position stays between start and target
gl2 = m.Glide(tau=0.04)
t = BASE + 10
gl2.tick((0.0, 0.0), t)
mx = 0.0
for i in range(120):
    t += 1 / 120
    px = gl2.tick((1.0, 0.0), t)[0]
    assert px <= 1.0 + 1e-9 and px >= mx - 1e-9, "glide overshot/reversed"
    mx = px
assert gl.tick(None, t) is None                           # released = no chase
ws = m.WheelSmoother(tau=0.035)
t = BASE + 20
ws.tick(t)
ws.add(300)
delivered = 0
for i in range(80):
    t += 1 / 120
    delivered += ws.tick(t)
assert delivered == 300, f"wheel smoother lost pixels: {delivered}/300"
ws.add(-120)
back = 0
for i in range(80):
    t += 1 / 120
    back += ws.tick(t)
assert back == -120, back
# release_cursor: pointer stopping clears the chase target
inj2 = m.Injector(dry_run=True)
inj2.move_to(0.4, 0.4)
assert inj2.target == (0.4, 0.4)
inj2.release_cursor()
assert inj2.target is None
print("14. glide + wheel smoother + cursor release OK")

# ---- 15. pointing is latched: a curled hand keeps steering
appc = m.Sleight(cfg_ok(), m.Injector(dry_run=True))
appc.gate.last_fail_t = BASE - 10
t = BASE
evs, t = drive(appc, obs("palm"), 60, t)
assert appc.state == appc.ARMED
t += 0.6
evs, t = drive(appc, obs("point", cx=0.45), 6, t)         # latch ON
assert appc.pointer_on
m0 = sum(1 for p_ in appc.injector.posted if p_[0] == "moveto")
for i in range(1, 9):                                     # hand CURLS (fist pose)
    appc.step(obs("fist", cx=0.45 + i * 0.01), t)         # ...but keeps moving
    t += DT
m1 = sum(1 for p_ in appc.injector.posted if p_[0] == "moveto")
assert m1 > m0, "curled hand stopped steering!"
evs, t = drive(appc, obs("palm", cx=0.6), 6, t)           # deliberate switch
assert not appc.pointer_on, "palm did not end pointing"
m2 = sum(1 for p_ in appc.injector.posted if p_[0] == "moveto")
for i in range(6):
    appc.step(obs("fist", cx=0.6 + i * 0.01), t)
    t += DT
assert sum(1 for p_ in appc.injector.posted if p_[0] == "moveto") == m2, \
    "steering continued after palm ended the latch"
print("15. latched pointing: curls steer, palm releases OK")

# ---- 16. idle deadzone: a resting/tremoring hand does not move the cursor
ptd = m.PointerController(cfg_ok(), ASPECT)
t = BASE + 120
for _ in range(25):                                       # settle
    ptd.update(obs("point", cx=0.50, cy=0.45), t)
    t += DT
base_out = ptd.last_out
maxdev = 0.0
for i in range(40):                                       # hand tremor
    jx = 0.50 + 0.0025 * math.sin(i * 1.7)
    jy = 0.45 + 0.0025 * math.cos(i * 2.3)
    o = ptd.update(obs("point", cx=jx, cy=jy), t)
    t += DT
    maxdev = max(maxdev, math.hypot(o[0] - base_out[0], o[1] - base_out[1]))
assert maxdev < 0.002, f"idle hand drifted the cursor by {maxdev:.4f}"
# deliberate movement still passes through, smoothly and without a jump
outs = []
for i in range(1, 16):
    outs.append(ptd.update(obs("point", cx=0.50 + i * 0.008, cy=0.45), t)[0])
    t += DT
assert outs[-1] > base_out[0] + 0.10, f"deliberate move blocked: {outs[-1]}"
steps = [b - a for a, b in zip(outs, outs[1:])]
assert max(steps) < 0.09, f"deadzone exit jumped: {max(steps):.3f}"
print("16. idle deadzone: still hand frozen, real motion smooth OK")

# ---- 17. learned poses: rotation-invariant features + k-NN classifier
import numpy as _np2
f_up = m.pose_features(mk_hand("point")[0], ASPECT)
assert f_up is not None and len(f_up) == 40

def _rot(lm, deg):                       # rotate a synthetic hand about its wrist
    th = math.radians(deg)
    wx, wy = lm[m.WRIST].x, lm[m.WRIST].y
    out = []
    for p_ in lm:
        dx, dy = (p_.x - wx) * ASPECT, p_.y - wy
        rx = dx * math.cos(th) - dy * math.sin(th)
        ry = dx * math.sin(th) + dy * math.cos(th)
        out.append(P(wx + rx / ASPECT, wy + ry, p_.z))
    return out

f_rot = m.pose_features(_rot(mk_hand("point")[0], 35), ASPECT)
assert _np2.linalg.norm(f_up - f_rot) < 0.25, "features are not rotation-invariant"
def _shrink(lm, k):                      # true uniform scale about the wrist
    wx, wy = lm[m.WRIST].x, lm[m.WRIST].y
    return [P(wx + (p_.x - wx) * k, wy + (p_.y - wy) * k, p_.z) for p_ in lm]

f_far = m.pose_features(_shrink(mk_hand("point")[0], 0.45), ASPECT)
assert _np2.linalg.norm(f_up - f_far) < 0.25, "features are not scale-invariant"
f_two = m.pose_features(mk_hand("two")[0], ASPECT)
assert _np2.linalg.norm(f_up - f_two) > 0.4, "different poses look identical"

# a tiny trained model classifies a rotated hand the geometry rules could miss
import tempfile as _tf, os as _os2
Xs, ys = [], []
for li, pose_name in enumerate(["point", "two", "palm", "fist", "other"]):
    src = "point" if pose_name == "other" else pose_name
    for d in range(-40, 41, 8):
        lm_r = _rot(mk_hand(src, cx=0.5 + d * 0.0004)[0], d if src != "other" else 0)
        fv = m.pose_features(lm_r, ASPECT)
        if fv is not None:
            Xs.append(fv); ys.append(li)
mp_ = _os2.path.join(_tf.mkdtemp(), "gm.npz")
_np2.savez(mp_, X=_np2.asarray(Xs, dtype=_np2.float32),
           y=_np2.asarray(ys, dtype=_np2.int32),
           labels=_np2.array(["point", "two", "palm", "fist", "other"]))
clf = m.GestureClassifier(mp_)
assert clf.ok and clf.n == len(Xs)
assert clf.predict(_rot(mk_hand("two")[0], 24), ASPECT) == "two"
assert clf.predict(mk_hand("palm")[0], ASPECT) == "palm"
# an unrecognisable input must return None, never a wrong guess
weird = [P(0.5 + 0.02 * i, 0.5 - 0.015 * i) for i in range(21)]
assert clf.predict(weird, ASPECT) in (None, "point", "two", "palm", "fist")
# no model file -> silently disabled, geometry rules keep working
assert not m.GestureClassifier("/nonexistent/model.npz").ok
o_geo = m.hand_obs(*mk_hand("point"), ASPECT, None)
assert o_geo["pose"] == "point"
print("17. learned poses: rotation/scale-invariant features + kNN OK")

# ---- 18. neighbor-finger truth: clicks win ties, resting curl can't hold
ptn = m.PinchTracker()
t = BASE + 200
o_rest = dict(obs("point"))
o_rest["ti_ratio"], o_rest["hold_ratio"] = 1.1, 0.45      # pinky RESTS curled
for _ in range(15):                                       # learn the baselines
    assert ptn.update(o_rest, t) == []
    t += DT
# the resting curl drifts near the thumb - must NOT become a hold
o_drift = dict(o_rest); o_drift["hold_ratio"] = 0.33
for _ in range(10):
    assert ptn.update(o_drift, t) == [], "resting pinky curl fired a hold!"
    t += DT
assert ptn.state == ptn.OPEN
# index touch where the middle is ALSO near (neighbors!) -> CLICK, not hold
o_both = dict(o_rest); o_both["ti_ratio"] = 0.20; o_both["hold_ratio"] = 0.24
evs = []
for _ in range(m.CLICK_PRESS_FRAMES + 1):
    evs += ptn.update(o_both, t)
    t += DT
assert evs == ["tap"], f"neighbor-touch became: {evs}"
o_off = dict(o_rest)
ptn.update(o_off, t); t += DT
t += m.CLICK_REFRACTORY_S
for _ in range(10):                                       # re-learn rest
    ptn.update(o_rest, t); t += DT
# a CLEAR middle-only touch still holds
o_mid = dict(o_rest); o_mid["hold_ratio"] = 0.15; o_mid["ti_ratio"] = 1.0
evs = []
for _ in range(m.CLICK_STABLE_FRAMES + 1):
    evs += ptn.update(o_mid, t)
    t += DT
assert "down" in evs, f"clear pinky touch did not hold: {evs}"
print("18. ties -> click, resting curl inert, pinky hold works OK")

# ---- 19. showing the palm to stop pointing cannot hit Back
appp = m.Sleight(cfg_ok(), m.Injector(dry_run=True))
appp.gate.last_fail_t = BASE - 10
t = BASE
evs, t = drive(appp, obs("palm"), 60, t)
assert appp.state == appp.ARMED
t += 0.6
evs, t = drive(appp, obs("point", cx=0.4), 8, t)          # pointing...
keys0 = sum(1 for p_ in appp.injector.posted if p_[0] == "key")
evs = []
for i in range(10):                                       # palm + IMMEDIATE yank
    evs += appp.step(obs("palm", cx=0.4 + i * 0.03), t)
    t += DT
assert sum(1 for p_ in appp.injector.posted if p_[0] == "key") == keys0, \
    "stop-pointing palm movement hit Back/Forward!"
t += 0.8
evs, t = drive(appp, obs("palm", cx=0.5), 12, t)          # settled palm...
evs = []
for i in range(11):                                       # ...then a real flick
    evs += appp.step(obs("palm", cx=0.5 + i * 0.02), t)
    t += DT
assert any(e.startswith("swipe") for e in evs), "deliberate flick blocked"
print("19. palm-entry grace: stopping is inert, deliberate flicks work OK")

# ---- 20. the bare-touch contract: slight separation = released, ready again
ptr_ = m.PinchTracker()
t = BASE + 300
o_far = dict(obs("point")); o_far["ti_ratio"], o_far["hold_ratio"] = 1.1, 1.2
for _ in range(10):                                       # learn rest
    ptr_.update(o_far, t); t += DT
o_touch2 = dict(o_far); o_touch2["ti_ratio"] = 0.12
evs = []
for _ in range(m.CLICK_PRESS_FRAMES + 1):
    evs += ptr_.update(o_touch2, t); t += DT
assert evs == ["tap"]
# separate JUST A BIT - between old and new thresholds - must re-arm
o_slight = dict(o_far); o_slight["ti_ratio"] = 0.46
ptr_.update(o_slight, t); t += DT
assert ptr_.state == ptr_.OPEN, "slight separation still read as touching!"
# and after the refractory, the next bare touch clicks again
t += m.CLICK_REFRACTORY_S
for _ in range(6):
    ptr_.update(o_slight, t); t += DT
evs = []
for _ in range(m.CLICK_PRESS_FRAMES + 1):
    evs += ptr_.update(o_touch2, t); t += DT
assert evs == ["tap"], f"re-click after slight release failed: {evs}"
print("20. bare touch clicks, slight separation re-arms OK")

# ---- 21. the hold matches the click's responsiveness, and can't jitter-drop
ph = m.PinchTracker()
t = BASE + 400
o_far2 = dict(obs("point")); o_far2["ti_ratio"], o_far2["hold_ratio"] = 1.1, 0.60
for _ in range(10):
    ph.update(o_far2, t); t += DT
o_grab = dict(o_far2); o_grab["hold_ratio"] = 0.40         # looser pinky contact
evs = []
for _ in range(m.CLICK_PRESS_FRAMES + 1):                  # fires as fast as click
    evs += ph.update(o_grab, t); t += DT
assert "down" in evs, f"loose pinky contact did not hold: {evs}"
# tracking jitter up to the noise band must NOT drop the drag
o_jit = dict(o_far2); o_jit["hold_ratio"] = 0.49
for _ in range(15):
    assert ph.update(o_jit, t) == [], "jitter dropped the drag!"
    t += DT
assert ph.state == ph.DRAG
o_rel = dict(o_far2); o_rel["hold_ratio"] = 0.56           # deliberate release
assert ph.update(o_rel, t) == ["up"]
print("21. hold: fast as click, jitter-proof drag, clean release OK")

# ---- 22. a hold OWNS the hand: palm-looking grabs keep the dot, block others
apg = m.Sleight(cfg_ok(), m.Injector(dry_run=True))
apg.gate.last_fail_t = BASE - 10
t = BASE
evs, t = drive(apg, obs("palm"), 60, t)
assert apg.state == apg.ARMED
t += 0.6
evs, t = drive(apg, obs("point", cx=0.4), 8, t)           # latch pointing
o_grab2 = dict(obs("point", cx=0.4))
o_grab2["hold_ratio"] = 0.20                              # pinky grabs
evs = []
for _ in range(m.CLICK_PRESS_FRAMES + 1):
    evs += apg.step(o_grab2, t); t += DT
assert "drag_start" in evs
# mid-drag the hand LOOKS like a palm and moves - dot/steer must survive,
# and neither Back/Forward nor scroll may fire
keys0 = sum(1 for p_ in apg.injector.posted if p_[0] == "key")
scr0 = sum(1 for p_ in apg.injector.posted if p_[0] == "scroll")
m0 = sum(1 for p_ in apg.injector.posted if p_[0] == "moveto")
t += 0.5                                                  # past palm grace
for i in range(14):
    o_p = dict(obs("palm", cx=0.40 + i * 0.02))
    o_p["hold_ratio"] = 0.20
    apg.step(o_p, t); t += DT
assert apg.pointer_on, "palm-looking drag killed pointer mode!"
assert sum(1 for p_ in apg.injector.posted if p_[0] == "moveto") > m0, \
    "cursor stopped during palm-looking drag"
assert sum(1 for p_ in apg.injector.posted if p_[0] == "key") == keys0, \
    "flick fired mid-drag!"
assert sum(1 for p_ in apg.injector.posted if p_[0] == "scroll") == scr0, \
    "scroll fired mid-drag!"
o_done = dict(obs("palm", cx=0.7)); o_done["hold_ratio"] = 0.60
evs, t = drive(apg, o_done, 3, t)
assert "drag_end" in evs and ("up",) in apg.injector.posted
evs, t = drive(apg, obs("palm", cx=0.7), 4, t)            # palm AFTER release
assert not apg.pointer_on, "palm after release should end pointing"
print("22. hold owns the hand: dot survives, others blocked, clean exit OK")

# ---- 23. double click: fast re-taps allowed, click-count stacks
pdc = m.PinchTracker()
t = BASE + 500
o_far3 = dict(obs("point")); o_far3["ti_ratio"], o_far3["hold_ratio"] = 1.1, 1.2
for _ in range(10):
    pdc.update(o_far3, t); t += DT
o_tap = dict(o_far3); o_tap["ti_ratio"] = 0.12
o_gap = dict(o_far3); o_gap["ti_ratio"] = 0.46            # slight separation
taps = 0
start = t
for cycle in range(2):                                    # tap, ease, tap
    evs = []
    for _ in range(m.CLICK_PRESS_FRAMES + 1):
        evs += pdc.update(o_tap, t); t += DT
    taps += evs.count("tap")
    for _ in range(7):                                    # ~0.23s of ease-off
        pdc.update(o_gap, t); t += DT
assert taps == 2, f"could not tap twice: {taps}"
assert (t - start) < 0.75, "second tap took too long to be a double-click"
# injector stacks the count for rapid same-spot clicks
inj3 = m.Injector(dry_run=True)
inj3.click()
inj3.click()
assert inj3._click_count == 2, inj3._click_count
inj3.click()
assert inj3._click_count == 3
inj3._click_t -= 10                                       # long pause resets
inj3.click()
assert inj3._click_count == 1
print("23. double-click: fast re-tap + stacked click count OK")

# ---- 24. border hallucinations cannot click: the edge guard
o_center = obs("tipinch")
assert o_center["touch_ok"] is True
o_edge = obs("tipinch", cx=0.02)                          # hand cut off at edge
assert o_edge["touch_ok"] is False, "edge landmarks passed as trustworthy"
peg = m.PinchTracker()
t = BASE + 600
o_far4 = dict(obs("point")); o_far4["ti_ratio"], o_far4["hold_ratio"] = 1.1, 1.2
for _ in range(10):
    peg.update(o_far4, t); t += DT
o_ghost = dict(o_far4); o_ghost["ti_ratio"] = 0.05        # hallucinated touch...
o_ghost["click_ok"] = False                               # ...at the border
for _ in range(30):
    assert peg.update(o_ghost, t) == [], "phantom border click fired!"
    t += DT
assert peg.state == peg.OPEN
# a real centered touch right after still clicks
evs = []
o_real = dict(o_far4); o_real["ti_ratio"] = 0.12
for _ in range(m.CLICK_PRESS_FRAMES + 1):
    evs += peg.update(o_real, t); t += DT
assert evs == ["tap"]
# mid-drag border wobble freezes the drag instead of dropping it
peg2 = m.PinchTracker()
t += m.CLICK_REFRACTORY_S
for _ in range(10):
    peg2.update(o_far4, t); t += DT
o_grab3 = dict(o_far4); o_grab3["hold_ratio"] = 0.20
evs = []
for _ in range(m.CLICK_PRESS_FRAMES + 1):
    evs += peg2.update(o_grab3, t); t += DT
assert "down" in evs
o_gwob = dict(o_far4); o_gwob["hold_ratio"] = 1.2         # looks released...
o_gwob["hold_ok"] = False                                 # ...but untrusted
for _ in range(10):
    assert peg2.update(o_gwob, t) == [], "border wobble dropped the drag"
    t += DT
assert peg2.state == peg2.DRAG
o_rel2 = dict(o_far4); o_rel2["hold_ratio"] = 0.60        # real release
assert peg2.update(o_rel2, t) == ["up"]
print("24. edge guard: phantom border clicks dead, drags survive wobble OK")

# ---- 25. a second touch that starts EARLY still fires at gate-open
pq = m.PinchTracker()
t = BASE + 700
o_f5 = dict(obs("point")); o_f5["ti_ratio"], o_f5["hold_ratio"] = 1.1, 1.2
for _ in range(10):
    pq.update(o_f5, t); t += DT
o_t5 = dict(o_f5); o_t5["ti_ratio"] = 0.12
o_g5 = dict(o_f5); o_g5["ti_ratio"] = 0.46
evs = []
for _ in range(m.CLICK_PRESS_FRAMES + 1):
    evs += pq.update(o_t5, t); t += DT
assert evs == ["tap"]
pq.update(o_g5, t); t += DT                               # slight release
evs = []
fired_at = None
for i in range(12):                                       # re-touch IMMEDIATELY
    got = pq.update(o_t5, t)
    if got:
        fired_at = t
        evs += got
        break
    t += DT
assert evs == ["tap"], "early second touch was thrown away"
print("25. early second touch fires at gate-open (double-click rhythm) OK")

# ---- 26. dock reach: a cut-off pinky can't block clicks; edge assist slides
o_lowhand = obs("tipinch")
o_lowhand = dict(o_lowhand)
o_lowhand["hold_ok"] = False                              # pinky out of frame
o_lowhand["click_ok"] = True                              # index+thumb fine
pk = m.PinchTracker()
t = BASE + 800
o_f6 = dict(obs("point")); o_f6["ti_ratio"], o_f6["hold_ratio"] = 1.1, 1.2
for _ in range(10):
    pk.update(o_f6, t); t += DT
o_lowhand["ti_ratio"] = 0.12
evs = []
for _ in range(m.CLICK_PRESS_FRAMES + 1):
    evs += pk.update(o_lowhand, t); t += DT
assert evs == ["tap"], f"cut-off pinky blocked an index click: {evs}"
# edge assist: hand hovering near the frame bottom keeps the cursor moving
pa = m.PointerController(cfg_ok(), ASPECT)
t = BASE + 900
o_low = dict(obs("point", cy=0.72))
o_low["hand_max_y"] = 0.95                                # fingers near border
first = None
out = None
for i in range(60):                                       # hold position 2s
    out = pa.update(o_low, t)
    if first is None:
        first = out
    t += 1 / 30
assert out[1] > first[1] + 0.15, \
    f"edge assist did not slide the cursor down: {first[1]:.2f} -> {out[1]:.2f}"
assert out[1] > 0.9, f"cursor never reached the bottom: {out[1]:.2f}"
print("26. dock reach: pinky-out clicks fine, edge assist completes trips OK")

# ---- 27. the chirality guard must never lock a real palm out
# Regression: a wrong calibrated_hand (or a shaky handedness score) inverted
# the palm test forever, so the app could see the hand but never arm.
cfg_ch = cfg_ok()
cfg_ch["palm_sign"] = 1.0
cfg_ch["calibrated_hand"] = "Left"
g_ch = m.Gate(cfg_ch)
palm_obs = {"nz": 0.6, "hand_label": "Left", "hand_score": 0.95}
assert g_ch._palm_ok(palm_obs), "same hand, confident: palm must pass"

# low-confidence chirality must NOT veto a good palm (was: return False)
assert g_ch._palm_ok({"nz": 0.6, "hand_label": "Right", "hand_score": 0.4}), \
    "a shaky handedness reading vetoed a real palm - the lockout bug"
assert g_ch._palm_ok({"nz": 0.6, "hand_label": "", "hand_score": 1.0}), \
    "missing handedness label vetoed a real palm"

# a CONFIDENT mirror hand still flips (the guard keeps working)
assert not g_ch._palm_ok({"nz": 0.6, "hand_label": "Right",
                          "hand_score": 0.95}), "mirror hand must flip"
assert g_ch._palm_ok({"nz": -0.6, "hand_label": "Right", "hand_score": 0.95})

# back of the hand still rejected
assert not g_ch._palm_ok({"nz": -0.6, "hand_label": "Left",
                          "hand_score": 0.95}), "back of hand must not arm"

# coaching: the pill names the first unmet condition, in priority order
g_ch.conditions = {"POSE": True, "STILL": False, "PALM": True,
                   "CENTER": True, "SIZE": True}
assert m.summon_hint(g_ch) == "HOLD STILL", m.summon_hint(g_ch)
g_ch.conditions = {"POSE": False, "STILL": False, "PALM": False,
                   "CENTER": True, "SIZE": True}
assert m.summon_hint(g_ch) == "OPEN HAND", m.summon_hint(g_ch)
g_ch.conditions = {"POSE": True, "STILL": True, "PALM": True,
                   "CENTER": True, "SIZE": True}
assert m.summon_hint(g_ch) is None
g_ch.conditions = {}
assert m.summon_hint(g_ch) is None, "no reading = no scolding"
# SIZE coaching names the direction when the hand scale is known
g_ch.conditions = {"POSE": True, "STILL": True, "PALM": True,
                   "CENTER": True, "SIZE": False}
lo, hi = cfg_ch["size_band"]
assert m.summon_hint(g_ch, {"scale": lo * 0.5}) == "CLOSER"
assert m.summon_hint(g_ch, {"scale": hi * 1.5}) == "FURTHER"
assert m.summon_hint(g_ch) == "DISTANCE", "no scale -> generic wording"
print("27. chirality guard cannot lock out a real palm + summon coaching OK")

# ---- 28. the glass widget: collapsed until a hand shows up
app_g = m.Sleight(cfg_ok(), m.Injector(dry_run=True))
ui = m.PillUI()
t = BASE
lm_g, _w = mk_hand("point", 0.5, 0.45)
o_g = obs("point", 0.5, 0.45)

for _ in range(40):                       # no hand -> settles to the nub
    rgba, cap, chip = m.render_pill_rgba(app_g, None, None, None, t, None, ui)
    t += DT
assert abs(cap[2] - m.NUB) < 2, f"idle widget should be a nub: {cap[2]}"
# idle must be a CIRCLE, so the orb is centred by construction (it used to be
# a fat rounded rect with the orb sitting off to the left)
assert abs(cap[2] - cap[3]) < 0.5, f"idle widget must be a circle: {cap}"
_cap_cx = (cap[0] + cap[2] / 2)
assert abs(_cap_cx - m.GLASS_W / 2) < 0.5, "widget must sit dead centre"
# isolate the ORB by brightness: the capsule tint is near-black (18) at a
# high alpha, the orb is silver - alpha alone cannot tell them apart
_bright = (rgba[:, :, 0] > 100) & (rgba[:, :, 3] > 60)
_oy, _ox = _np.nonzero(_bright)
assert abs(_ox.mean() / 2 - _cap_cx) < 1.0, "the orb must be centred in it"
assert chip is None, "no hand -> no hand chip"
assert rgba[0, 0, 3] == 0, "the widget background must be transparent"

# the idle orb breathes on ALPHA, never on SIZE. Claude's own idle dot
# (cds-dot-pulse, read out of the app bundle) is 1.8s / 20%->70% / zero
# scale - a throbbing dot is the tell of a generated one.
_ui_b = m.PillUI()
_w, _a = set(), []
for _i in range(19):
    _t = BASE + _i * (m.ORB_BREATH_S / 18)
    for _ in range(3):
        _rg, _cp, _ch = m.render_pill_rgba(app_g, None, None, None, _t, None,
                                           _ui_b)
    _orb = (_rg[:, :, 0] > 100) & (_rg[:, :, 3] > 40)
    _oy2, _ox2 = _np.nonzero(_orb)
    _w.add(_ox2.max() - _ox2.min())
    _a.append(int(_rg[:, :, 3][_orb].max()))
assert len(_w) == 1, f"the idle orb changed SIZE while breathing: {_w}"
assert max(_a) - min(_a) > 50, f"the idle orb is not breathing: {min(_a)}..{max(_a)}"
painted = (rgba[:, :, 3] > 0).mean()
assert painted < 0.10, f"idle widget paints too much of the screen: {painted:.2f}"

app_g.state = app_g.ARMED                 # hand + armed -> opens up
app_g.armed_until = t + 9
app_g.pointer_on = True
for _ in range(40):
    rgba, cap, chip = m.render_pill_rgba(app_g, o_g, "point", None, t, lm_g, ui)
    t += DT
assert cap[2] > m.NUB + 60, f"active widget should be open: {cap[2]}"
assert cap[2] <= m.FULL_W + 1, f"widget must never exceed FULL_W: {cap[2]}"
assert chip is not None and chip[2] > 90, "the hand needs its own glass chip"
assert rgba[0, 0, 3] == 0, "still transparent when open"
_short_w = cap[2]

# the word morphs instead of snapping
m.render_pill_rgba(app_g, o_g, "two", None, t, lm_g, ui)
assert ui.prev == "CURSOR" and ui.word == "SCROLL", (ui.prev, ui.word)
assert ui.morph(t) == 0.0 and ui.morph(t + m.MORPH_S) == 1.0
assert 0.4 < ui.morph(t + m.MORPH_S / 2) < 0.6, "morph should be mid-flight"

# and it closes again when the hand leaves
for _ in range(40):
    rgba, cap, chip = m.render_pill_rgba(app_g, None, None, None, t, None, ui)
    t += DT
assert abs(cap[2] - m.NUB) < 2, "widget must collapse when the hand leaves"

# the capsule sizes itself to the WORD - a long instruction must not spill out
# (a capsule cut for "CLICK" would clip "CENTER HAND")
app_w = m.Sleight(cfg_ok(), m.Injector(dry_run=True))
app_w.gate.conditions = {"POSE": True, "STILL": True, "PALM": True,
                         "CENTER": False, "SIZE": True}
ui2 = m.PillUI()
for _ in range(40):
    rgba2, cap2, _c2 = m.render_pill_rgba(app_w, o_g, None, None, t, lm_g, ui2)
    t += DT
assert ui2.word == "CENTER HAND", ui2.word
assert cap2[2] > _short_w, (
    f"a longer word must widen the capsule: {cap2[2]:.0f} vs {_short_w:.0f}")
_tb = m.glass.text_bitmap("CENTER HAND", 13.0 * m.PILL_SS, weight=0.23,
                          tracking=1.9 * m.PILL_SS)
if _tb is not None:                      # measure the WORD: the hand chip
    _text_w = _tb.shape[1] / m.PILL_SS   # legitimately sits outside the pill
    _text_x = cap2[3] / 2 + 20           # same offset the renderer uses
    assert _text_x + _text_w + 6 <= cap2[2], (
        f"word {_text_w:.0f}pt does not fit a {cap2[2]:.0f}pt capsule")
print("28. glass widget: collapsed until summoned, transparent, word morph OK")

# ---- 29. precision assist: a trackpad's acceleration curve, without giving
# up absolute pointing. Slow hand -> less screen covered; fast hand -> 1:1.
def _travel(step, gain, frames=30):
    c = cfg_ok()
    c["precision_assist"] = gain
    p = m.PointerController(c, ASPECT)
    tt = BASE
    x = 0.45
    first = None
    for i in range(frames):
        oo = obs("point", cx=x, cy=0.45)
        oo["ix"], oo["iy"] = x, 0.45
        r = p.update(oo, tt)
        if i == 0:
            first = r
        x += step
        tt += DT
    return abs(r[0] - first[0])

_slow_off = _travel(0.10 * DT, 0.0)
_slow_on = _travel(0.10 * DT, m.PRECISION_MAX)
assert _slow_on < _slow_off * 0.75, (
    f"slow aiming should cover less screen: {_slow_on:.3f} vs {_slow_off:.3f}")
_fast_off = _travel(1.20 * DT, 0.0)
_fast_on = _travel(1.20 * DT, m.PRECISION_MAX)
assert abs(_fast_on - _fast_off) < 0.01, (
    f"a fast sweep must stay 1:1: {_fast_on:.3f} vs {_fast_off:.3f}")
assert _travel(0.10 * DT, 0.0) == _slow_off, "assist=0 must be pure absolute"

# and the screen edge must still be reachable with the assist engaged
p_edge = m.PointerController(cfg_ok(), ASPECT)
t = BASE
x = 0.5
for _ in range(120):
    x = min(0.98, x + 0.02)
    oe = obs("point", cx=x, cy=0.45)
    oe["ix"], oe["iy"] = x, 0.45
    oe["hand_max_x"], oe["hand_min_x"] = min(1.0, x + 0.05), x - 0.05
    r = p_edge.update(oe, t)
    t += DT
assert r[0] > 0.98, f"precision assist blocked the screen edge: {r[0]:.3f}"
print("29. precision assist: fine when slow, 1:1 when fast, edges reachable OK")

print()
print("ALL SLEIGHT v7.8 TESTS PASSED")
