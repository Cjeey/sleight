# Sleyth v7.4 — trackpad in the air

**Tracking engine:** Google's modern HandLandmarker (the 2023 Tasks models — the same class of tech commercial gesture products build on). Downloads once on first run; falls back to the built-in tracker if offline. The camera view shows engine, FPS, and the current gesture, with fingertip rings and a hand box.

## Teach it your hand (optional, ~3 min, one time)

```bash
cd "/Users/mohamwedayoub/app Idea/sleyth" && ./run.sh --train
```

Records your own hand doing each pose from many angles and trains a small classifier on it. Rotation- and distance-invariant, so a tilted or far hand reads the same as a straight, close one — something the built-in geometry rules can never do. Everything stays on your machine. Delete `gesture_model.npz` to go back to the built-in rules.

## Run it

```bash
cd "/Users/mohamwedayoub/app Idea/sleyth" && ./run.sh
```

## First run: it teaches you

After the 10-second palm calibration, an **interactive tutorial** walks you through every gesture, one at a time — summon, cursor, click, scroll, flick. Each step advances only when the gesture *actually worked*, so finishing the tutorial means you can do all of them. The tutorial runs in **dry-run**: nothing you do while learning touches your real system.

`n` skips a step, `t` exits. Re-run it anytime with `t`.

## Day-to-day: the glass widget

Sleyth lives as a **frosted glass widget floating at the bottom of your screen** — no window, no title bar, transparent background, black/white/grey only. It never takes focus and never eats a click, so it can't get in the way of the app you're controlling.

**It stays out of your way until you talk to it.** With no hand in view it's just a small nub — a slowly breathing blob. Raise your hand and it opens:

- **The blob** — a liquid shape that breathes with your hand and glows white when armed. A ring closes around it as you hold your palm to summon
- **The word** — `CURSOR`, `SCROLL`, `CLICK`, `HOLD`, `BACK`, `FORWARD`. Words don't snap, they morph: the old one lifts out as the new one rises in
- **Coaching** — if it won't start, the word tells you why: `OPEN HAND`, `TURN PALM`, `CLOSER`, `FURTHER`, `CENTER HAND`, `HOLD STILL`
- **Your hand**, on its own glass chip beside the capsule — the box is the mapping area, so you can see where you are before you move

Control it from the **menu-bar icon** (◎): full view, move widget, tutorial, recalibrate, quit. The widget can sit **bottom-center or bottom-right** (remembered across launches). The full view (`f`) is the settings/diagnostics surface — camera, gate conditions, tuning keys.

If macOS won't provide the floating window, Sleyth falls back to a plain dark panel automatically rather than failing to start.

## The gestures

| Hand | Does |
|---|---|
| **1 finger** (index) | move the cursor. The mapping box follows YOU: start anywhere, control begins from where the cursor already is |
| **thumb + index touch** | **click the instant they meet** — no release needed, no latency. Your hand can curl naturally; once contact registers it can't be cancelled |
| **thumb + pinky touch** | **mouse hold / drag** — the pinky is the farthest finger from the index, so click and hold can never blur. Grabs immediately, follows your hand, release to drop. No timers anywhere |
| **2 fingers up/down** | scroll — page follows your hand; curl to pause; fast flick coasts. The letting-go motion is discarded |
| **whole palm, flick L/R** | Back / Next — big target, works at full speed |

**Clean separation:** two fingers only ever scroll; the open palm only ever flicks. They cannot mix.

Summon: open palm, hold still ~1s. **Stopping: just lower your hand** — 6s idle and it disarms itself. There is no stop gesture to misfire. Works on **whatever app is focused / under the cursor** — it's real mouse and keyboard input, system-wide.

## Permissions (one-time)

**System Settings → Privacy & Security → Accessibility → enable your terminal app**, then restart Sleyth. Until then everything runs but no events land (DRY-RUN badge shows).

## Keys

Menu-bar icon (◎): full view · move widget · tutorial · recalibrate · quit. In the full view:

```
q quit          f widget/full view     p move widget     t tutorial
n skip step     c recalibrate          x mark false arm  v flip scroll
d dry-run       [ / ] stillness        r reset counters
```

## Tuning

`sleyth_config.json`: `cursor_deadzone` (idle-drift immunity, default 0.009 — raise if the cursor still creeps, lower for finer aiming), `scroll_gain` (px per hand-width, default 900), `scroll_flip`, `swipe_left_key`/`swipe_right_key` (`back`, `forward`, arrow or page keys — defaults are real browser Back/Forward; dangerous keys are rejected), `panel_pos` (`center` or `right`, also the `p` key).

## Safety rails

Clean modifier state on all synthetic events (a held Cmd can't corrupt them) · no irreversible actions mappable · click needs a reaching index (a fist can never click) · guarded dry-run toggle that can't lie about being LIVE · every session logs per-arm records to `sleyth_log_*.jsonl`.
