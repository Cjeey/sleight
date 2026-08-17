# Sleyth — trackpad in the air

Move your Mac's cursor with your hand, in the air, using only the webcam.
No hardware. Nothing is recorded, nothing leaves your machine.

**This is an early build.** It is unsigned, so macOS will complain the first
time — that is expected, and the steps below get past it.

---

## Install (2 minutes, once)

**0. Drag Sleyth.app into your Applications folder first.**
Do not run it from Downloads or straight out of the zip — macOS runs
unmoved apps from a temporary location and forgets their permissions
every time. (Sleyth will warn you if you skip this.)

**1. The first open takes three clicks — macOS blocks unsigned apps.**

1. Double-click Sleyth. macOS says it "could not verify" it — click **Done**
   (not "Move to Trash"!)
2. Open **System Settings → Privacy & Security**, scroll to the bottom —
   there is a line saying Sleyth was blocked. Click **Open Anyway**.
3. Confirm **Open Anyway** in the dialog (your Mac may ask for your
   password).

This is Apple's standard flow for apps from outside the App Store — on
older Macs (macOS 14 and earlier), right-clicking the app → **Open** works
instead. Either way it only happens once; after this, Sleyth opens
normally.

**2. Allow the camera** when macOS asks. Sleyth needs it to see your hand.

**3. Allow Accessibility** — this is the one people miss.

- Menu bar → **◎ → Grant Accessibility...** takes you straight to the right
  place (or System Settings → Privacy & Security → Accessibility)
- Turn **Sleyth** ON (use `+` and pick Sleyth.app if it isn't listed)
- No restart needed — Sleyth notices within a couple of seconds and says
  **LIVE**

Without this, everything looks like it is working but the cursor never moves.
The widget shows a white **DRY** chip when this is the problem.

---

## First launch (5 minutes, guided)

Sleyth walks you through everything itself:

1. **Calibration** — show it your palm, then the back of your hand,
   5 seconds each. This happens once.
2. **A guided tour** — six gestures, one at a time, at your own pace.
   You press Next; nothing moves on without you. Nothing you do during
   the tour touches your real cursor.

Nothing is uploaded; everything it learns stays on your Mac.

---

## Using it

Sleyth lives as a small circle at the bottom of your screen. **Drag it
anywhere you like.** Everything is controlled from the **◎ icon in your menu
bar**.

**To start:** hold an **open palm** toward the camera and keep it still for
about a second. The circle opens up and says **ARMED**.

| Your hand | What happens |
|---|---|
| **1 finger** (index) | moves the cursor |
| **thumb + index touch** | click, the instant they meet |
| **thumb + pinky touch** | hold / drag — release to drop |
| **2 fingers, move up/down** | scroll |
| **whole palm, flick left/right** | back / forward in the browser |

**To stop:** just lower your hand. It disarms itself after 6 seconds.

If it will not start, the widget tells you why in one word — `OPEN HAND`,
`TURN PALM`, `CLOSER`, `CENTER HAND`, `HOLD STILL`. Do that thing.

---

## What I need from you

Honest reactions, especially the bad ones:

1. **Did it arm at all?** If not, what word did the widget show?
2. **Could you click something small** — a link, a menu, a tab?
3. **What made you give up?** That is the most useful thing you can tell me.
4. Roughly how long before it felt natural — or did it never?

Rough edges are expected. Tell me about them.

---

## Removing it

Drag Sleyth.app to the Trash. Its settings live in one folder you can also
delete: `~/Library/Application Support/Sleyth`. Nothing else is touched.
