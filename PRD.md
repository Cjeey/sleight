# PRD — Sleight *(working title)*

**For the moments your hands aren't available.**

| | |
|---|---|
| Author | Mohamed Ayoub (with Claude) |
| Date | 2026-08-11 |
| Status | Draft v2 |
| Platform | macOS first, then iPad/iPhone |

---

## 1. One-liner

A background utility that gives you a few seconds of control over your screen when your hands are wet, greasy, gloved, covered in dough, or holding something. Say the word, gesture in the air, done. Invisible the rest of the time — like Wispr Flow, but for hands instead of voice.

## 2. Problem

Everyone has the same recurring moment, several times a day:

> *You need the screen. Your hands can't touch it.*

- Cooking — raw chicken on your hands, recipe on a propped-up iPad, three more steps to scroll
- Under a car — grease to the wrist, torque spec on a tablet on the fender
- Mid-haircut — scissors in one hand, comb in the other, reference photo on the mirror screen
- At the bench — gloved, mid-protocol, next SOP step is two scrolls away
- Holding a baby, carrying groceries, hands covered in paint, clay, flour, soil

The workarounds are all bad: **wipe your hands, use a knuckle or elbow, de-glove and re-glove, smear the screen, or ask another person to click for you.**

That last one is the tell. In dental offices, the dentist — hands inside a patient's mouth — **asks the assistant to click.** A trained human being, used as a mouse. When people are willing to spend a *second person's time* on a problem, the problem is real.

**Scope discipline — what this is NOT:** this is not "my gloves don't register on the touchscreen." A $5 pair of conductive gloves solves that. We only serve moments where at least one of these is true:

| Condition | Meaning |
|---|---|
| **Contamination** | touching would ruin something — the food, the sample, the sterile field, or the screen |
| **Occupancy** | both hands are physically holding something |
| **Reach** | the screen is propped, mounted, or across the bench |

## 3. Why existing products fail

| Product | What it is | Why it doesn't own this |
|---|---|---|
| AirTouch (Neural Lab) | $30/mo webcam gesture control, 15 gestures | Aims to replace the mouse → cursor control → gorilla arm. Enterprise/kiosk sales, not a background utility |
| Touchless | Windows gesture + voice app | Cursor-centric, foreground app |
| GestSure / TedCas | Touchless OR imaging control | Kinect-era hardware, surgical-only, regulated, expensive |
| Recipeats / GestureCook | Gesture recipe apps | Fire on a hand *pose* — a closed fist advances the step. Cooking hands make fists constantly. Toy reliability |
| Gameface / Apple Eye Tracking | Free OS accessibility features | Built for permanent disability and continuous use, not the 3-second hands-busy moment |

**The shared failure:** they watch for a pose and fire. Working hands make poses constantly. Without intent detection, false activations make the tool worse than useless — you lose your place *and* your hands are still dirty.

**False-positive rejection is the product.** Hand tracking is free (MediaPipe, Apple Vision) and is not a moat.

### 3b. The real incumbent: voice

The competitors above are the wrong ones to fear. The dangerous substitute is **voice**, because this product already ships an always-on microphone for its wake word — which makes `"Hey Sleight, scroll down"` nearly free, and deletes the camera, the lighting sensitivity, the 1.5 m framing, the intent gate, gorilla arm, and the privacy objection **all at once**.

| Substitute | Status | Why we might still win — *hypotheses, not findings* |
|---|---|---|
| **macOS Voice Control** | **Free, built in, ships "scroll down" / "click Next" today** | Discrete and paged, not analog — "down… more… stop" vs one continuous two-finger scroll |
| Siri | Free, built in | Not designed for rapid repeated micro-commands |
| Wispr Flow | The author uses it daily | Solves *text*, not *navigation* |
| Dragon Medical | Entrenched in clinical settings | Same discrete-vs-analog limitation; expensive |

Three reasons gestures might beat voice, **all currently untested**:

1. **Analog vs discrete** — scrolling is continuous; voice is paged
2. **Social cost** — talking to a computer with a client, patient, or family in the room isn't free
3. **Noise floor** — blender, drill, extractor fan, shop radio

> **Pre-committed falsifier (agreed 2026-08-11):** if macOS Voice Control alone clears **≥ 90% first-try success** and **≤ 1 false activation per 20 min** in all three M1 environments, **gestures become the fallback modality and this becomes a voice product.** This sentence is written before the test so the result cannot be rationalised afterwards.

## 4. What we've already validated (evidence)

**Air-keyboard viability test, 2026-08-11** — built and self-run. 3 sessions, MacBook webcam, pinch method, MediaPipe 0.10.21. Code and raw data in `keyboard-test/`.

**All three runs, not the best one:**

| Run | Drift (key-widths) | Key accuracy | Typing speed |
|---|---|---|---|
| 1 | 0.59 | 33% | 1.6 WPM |
| 2 | 0.51 | 80% | 5.8 WPM |
| 3 | **0.09** | 80% | 5.6 WPM |

| Finding | Confidence | Implication |
|---|---|---|
| **Air QWERTY is dead** — 5.6 WPM ceiling vs phone ≈ 35, voice ≈ 150 | **High.** Consistent across all runs; a 6× gap is not a tuning problem | No air keyboard, ever |
| Big-target selection is plausible — every miss was an **adjacent** key, so 2× targets ≈ ~100% | **Medium.** Directionally clear, but n=3, one user | Radial menus / large buttons are the v1.1 direction, not a locked guarantee |
| Fast learning curve — 33% → 80% in ~4 min | **Medium.** Single user | Day-two users likely fine |
| Fingertip steadiness | **Low as stated.** 0.09 is the best of three (spread 0.09–0.59) and **all runs were at desk distance (~40–60 cm), not the 1.0–1.5 m this PRD specifies** | Must be re-measured at spec distance in M1.0. Do not cite 0.09 as typical |

> ⚠️ **Artifact note:** the saved `results_*.json` files record `accuracy_pct: 0.0` for all runs — a scoring bug (identity comparison instead of label comparison) found and fixed after the runs. The accuracies above were recomputed from the per-trial `detail` arrays in the same files. The raw files have not been re-generated.

**Locked design consequence (high confidence only):** no air keyboard. No cursor. Voice for text, gestures for navigation, big targets only.

## 5. Who this is for

**Not a vertical — a moment.** The same product, unchanged, serves everyone below. There is no cook-specific or mechanic-specific code; there's one intent gate and three gestures.

| Segment | Why they're in | Notes |
|---|---|---|
| **Home cooks** | Highest frequency, most universal, most demo-able | Weak willingness to pay alone, but the best top-of-funnel |
| **DIY / auto / workshop** | Grease + propped tablet + mounted screens | Reachable via YouTube and forums |
| **Makers — pottery, baking, painting, gardening** | Hands permanently coated mid-task | Strong hobby spend |
| **Salon / barber** | Both hands occupied continuously; voice is socially awkward | Hard to reach, low software budget |
| **Lab / clinical / dental** | Contamination is a *compliance* rule, not a preference; real budgets | Highest value per seat, needs vertical access we don't currently have |
| **Surgical** | Real, proven demand (GestSure exists) | Regulated, long sales cycles — **explicitly out of scope until v2+** |

**The distribution insight:** we cannot run ads at "people whose hands are busy." But this product is **extremely demo-able** — a 15-second video of someone scrolling a recipe with raw-chicken hands is instantly legible with zero explanation. That's the GTM: **one product, many short videos, each showing a different hands-busy moment.** Each video reaches a different segment without changing the product.

**We let the vertical name itself.** Ship horizontal, watch which segment retains, then double down. We do not pick a beachhead on a guess — especially one we have no access to.

## 6. Product principles (non-negotiable)

1. **Invisible until summoned.** Menu-bar only. No window. The user never "opens the app."
2. **Camera off until the wake word.** Local mic listens for one phrase; camera activates only after. Nothing ever leaves the device — this is the privacy story *and* the battery story.
3. **Intent gate before any action.** Arming requires a compound signal no working hand produces by accident: stillness (~800 ms — the real discriminator) AND palm-to-camera AND center-of-frame AND deliberate-presentation size.
4. **Discrete commands, never a cursor.** The moment we ask someone to *position* something in the air, we've rebuilt the product that already lost.
5. **One hand.** The other hand is busy — that's the whole premise. Any two-handed gesture is a bug.
6. **No irreversible actions from gestures.** No send, submit, delete, close-unsaved. A false positive costs one second, never work.
7. **Loud feedback.** Chime + unmistakable HUD change on arm / action / disarm. Users who can't tell if they were seen will gesture twice, double-fire, and churn.
8. **Built for 1.5 m, side-lit, one partially-occluded hand.** Demo conditions (40 cm, front-lit, two hands) are banned from acceptance tests.

## 7. How it works

```
IDLE (menu-bar icon, local mic listening, camera OFF)
  │  "Hey Sleight"
  ▼
LISTENING (camera ON, HUD: "hold up a still hand")
  │  intent gate passes (~1 s)                 │ 5 s no hand
  ▼                                            ▼
ARMED (chime + HUD glows, gestures live)      back to IDLE, camera OFF
  │  gesture → action (HUD flashes action name)
  │  stays ARMED 5 s after last gesture
  ▼
IDLE (camera OFF)
```

**MVP gesture set** — chosen for silhouette distinctness, not finger counting (3 vs 4 fingers is unreliable at range; fist vs palm vs two-finger is not):

| Gesture | Action |
|---|---|
| Two fingers up, move vertically | Scroll (analog, rate-controlled) |
| Open-palm swipe left / right | Back / Next (configurable key mapping) |
| Fist held 1 s | Dismiss / disarm now |

Three reliable gestures beat eight flaky ones. Zoom, radial menu, voice commands, and per-app profiles are v1.1+.

## 8. MVP specification

**Goal:** one hero flow, flawless — *hands full, say the word, scroll or flip pages on a screen 1.5 m away, walk away.* And produce a real false-positive number from real environments.

### In scope

- macOS menu-bar app (Apple Silicon), no dock icon
- On-device wake word (openWakeWord default; Porcupine only if quality demands it)
- Camera activates post-wake only; hard indicator (macOS green LED + HUD)
- Intent gate (stillness + palm + center + size) with a sensitivity slider
- Three gestures: two-finger scroll, palm swipe L/R, fist disarm
- Floating HUD: current state + last action
- Audio feedback: arm / action / disarm
- Timeouts: LISTENING 5 s → idle; ARMED 5 s after last gesture → idle
- Settings: wake word on/off, camera picker, sensitivity, swipe key mapping
- **Local-only counters:** false activations, failed arms, sessions/day, session length. Stored on device; beta users opt in to share a summary manually
- Under ~1% CPU while IDLE (mic-only)
- First-run flow: permissions explainer (camera + mic + accessibility), 30-second guided practice

### Out of scope (explicitly)

- ❌ Air keyboard (killed by our own data) and cursor mode (killed by a decade of prior art)
- ❌ Voice *commands* — wake word only; "zoom in" is v1.1
- ❌ Radial menu, per-app profiles, custom gestures (v1.1)
- ❌ Windows (v1.2 — only if data shows a Windows-bound segment retaining)
- ❌ Surgical / regulated environments
- ❌ Any cloud anything — permanently

### Acceptance criteria

1. **≤ 1 false activation per 20 minutes** of continuous normal hand-work in frame, measured by the built-in counter across **≥ 3 different environments** (kitchen, workshop/desk, one other)
2. **≥ 90% first-try arm success** at 1.0–1.5 m, side-lit, one hand
3. Wake word → ARMED in **≤ 1.5 s**; gesture → action **≤ 150 ms** perceived
4. Scroll a 20-step recipe end-to-end from 1.5 m without touching anything
5. 8-hour IDLE run: no fan spin-up, camera verifiably off (LED)
6. A first-time user succeeds within 2 minutes with no help beyond the HUD

### Build sequence

| Milestone | What | Exit test |
|---|---|---|
| **M0 — done** | Air-keyboard viability test | Killed QWERTY. Steadiness **not admissible at spec distance** — see §4 |
| **M1a — cheapest signal first** | Run the built intent gate (`intent-gate/`) in the **kitchen**, 20+ min, working normally. Same session: **macOS Voice Control as the second arm** (Settings → Accessibility → Voice Control; zero build) | A first false-activation number. If it's catastrophic, nothing downstream matters and we stop here |
| **M1.0 — backend bake-off** *(only if M1a is promising)* | Record a reusable corpus (positive + negative, 1.0–1.5 m, side-lit). Bake off **Apple Vision `VNDetectHumanHandPoseRequest`** vs **MediaPipe Tasks HandLandmarker** on identical frames | Backend locked into §8 with measured numbers. **Hard gate: can it tell palm-toward-camera from back-of-hand at 1.5 m?** (Vision is 2D-only — this is the specific risk) |
| **M1 (wk 1–3)** | Gate tuning on the recorded corpus: replay harness, parameter sweep, a single locked operating point. Extend to environments 2 and 3 | ≥ 3 h negative corpus swept; **zero false arms over ≥ 60 min live per environment**; ≥ 90% first-try arm success **at the same parameter set**; **voice falsifier resolved in writing** |
| **M2 (wk 4–5)** | Swift menu-bar app: wake word, gate, **event-target resolution** (see §9), scroll + swipe on real OS events, HUD, timeouts | Daily self-dogfood; criteria 3–5, and criterion 4 tested with **the pointer parked off-target** |
| **M3 (wk 6–7)** | 10–20 beta users from a public launch video. Opt-in counters + interviews. **Signing/notarization tail lands here** | Criteria 1, 2, 6 hold for people who aren't us |
| **M4** | Read the data: **which segment retained? Did the voice arm beat us?** | Written go/no-go with numbers |

**Stack — default, not a coin flip:** MediaPipe Tasks HandLandmarker in a local Python helper is the ship-path default (it's a day of work and it's the only backend with evidence behind it). **Apple Vision is the challenger** and must win or tie on the false-activation and arm-success criteria to be adopted — if it does, take it, because it collapses the packaging and notarization tail to zero. **Building MediaPipe from source with Bazel is explicitly ruled out.**

> ⚠️ The gate as currently built (`intent-gate/intent_gate.py`) derives its PALM condition from MediaPipe's 3D world landmarks. **Apple Vision does not provide these.** If Vision wins the bake-off, the palm condition must be re-derived from 2D geometry or dropped — and dropping it weakens principle 3.

## 9. Risks & mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| **False positives in the wild exceed lab numbers** | **Existential** | It is acceptance criterion #1, measured in real environments before any launch. If M1 fails this, the project stops |
| **Voice-only turns out to be sufficient** | **Existential** | Tested in M1a at zero build cost against the pre-committed falsifier in §3b. If voice wins, we build the voice product — that is a better outcome than discovering it at week 7 |
| **macOS routes scroll events by cursor position** — colliding head-on with principle 4 ("never a cursor") | **High** | A `CGEvent` scroll goes to whatever window is under the pointer. Must be decided **before** the M2 event layer is written. Options: (a) target the focused window via the Accessibility API (`AXUIElement`) instead of HID events, (b) park the pointer invisibly over the target window before scrolling, (c) frontmost-app-only scope. Criterion 4 must be tested **with the pointer parked off-target**, or it false-passes |
| Wake→ARMED in ≤ 1.5 s may be arithmetically impossible | Medium | Wake-word detection + camera warm-up (AVFoundation start is not free) + 800 ms stillness likely exceeds 1.5 s. Re-measure and set an honest number in M2 — **do not "fix" it by leaving the camera on**, which would delete principle 2 |
| **Horizontal product → no obvious first 100 users** | **High** | Video-native GTM: the product demos itself in 15 seconds. Launch on the channels where demo-able Mac utilities spread. Let retention name the vertical |
| Wake word misfires while talking / fails in noise (blender, drill, shop) | High | Test against real kitchen/shop audio in M2. Fallback: user-chosen "camera-always-on, gesture-wake" mode. Last resort: Bluetooth foot pedal |
| Camera-always-on privacy objection | Medium | Camera-off-by-default *is* the answer. All local, green LED, never record, never upload |
| Gorilla arm | Medium | Designed for ≤ 5-second interactions; ARMED auto-expires; no cursor. If metrics show sessions trending > 30 s, that's a design smell to fix |
| "$5 glove" substitute | Medium | Only market to contamination / occupancy / reach moments (§2). Never pitch as a glove fix |
| Consumer segments won't pay | Medium | Free tier for cooking; paid tier for pro/multi-device. Real revenue likely comes from the pro segments that surface in M4 |
| AirTouch ships macOS and copies the wedge | Medium | Their DNA is enterprise kiosk mouse-replacement. Our moat is the reliability number and the invisible-utility UX, not tracking tech |
| macOS permission friction (camera + mic + Accessibility) | Medium | First-run flow is in scope; measure drop-off at each grant |

## 10. Business model (validate at M4)

- **Anchor:** AirTouch charges $30/mo individual — willingness to pay exists at the pro end
- Beta: free, in exchange for opt-in counters + interviews
- Free tier: one wake word, three gestures — enough for home cooking
- Pro: ~$8–12/mo or ~$79/yr — multi-device, custom mappings, per-app profiles
- Never: ads, data sale, cloud tiers

## 11. Success metrics

- **Reliability:** false activations / 20 min (< 1), arm success (> 90%)
- **Habit:** sessions per user per day — target ≥ 3. This is the real proof it entered someone's workflow
- **Retention:** % of beta users still triggering ≥ 1 session/day at day 14
- **The learning metric:** *which segment retains best.* This decides v1's direction — we are explicitly buying this information with the MVP
- **Qualitative bar:** a video of a real user, hands genuinely unusable, completing a real task without touching anything

## 12. Open questions

1. **openWakeWord licensing** — §8 assumes Apache-2.0, but the *pre-trained models* may be **CC BY-NC-SA (non-commercial)**, which would block a paid product. 10-minute check, do it before relying on it
2. **AirTouch facts need re-verifying** — §3 and §10 cite $30/mo, but the review indicates **no macOS build exists at all** and the pricing may be wrong. Both feed our pricing anchor
3. Name + trademark + domain check ("Sleight" is a working title)
4. Wake-word quality in kitchen noise (extractor fan, blender) — M2 spike
5. Arm-fatigue data point — still uncaptured; record during M1a
6. Free vs paid line — where exactly does "cooking" end and "pro" begin?

## 13. Beyond MVP (directional)

- **v1.1:** radial command menu (8 big wedges — validated by M0 steadiness data), voice commands, per-app profiles, custom mappings
- **v1.2:** iPad/iPhone (the propped-up-tablet case is arguably the *primary* cooking scenario); Windows only if data demands it
- **v2:** segment packs (kitchen-display mode, shop-manual mode), multi-camera for mounted screens
