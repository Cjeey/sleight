# Air keyboard test

One question: **can you type on a virtual keyboard using only a webcam?**

This runs three tests and prints hard numbers, so you get a yes or no instead of a feeling.

## Run it

```bash
cd "/Users/mohamwedayoub/app Idea/keyboard-test" && ./run.sh
```

First run installs dependencies into a local `.venv` (takes a minute or two). After that it starts instantly.

macOS will ask for **camera permission** the first time. If it never asks and the camera fails to open, grant it manually in **System Settings → Privacy & Security → Camera** for whichever app you launched this from.

## The three phases

**1. Steadiness** — hold your fingertip on a red cross for 10 seconds. Measures how much your hand drifts with nothing to rest on.

This is the most important number. It gets reported in **key widths**. If your hand drifts more than about half a key, per-key typing is impossible no matter how good the software is.

**2. Targets** — a key lights up, you press it. 15 times. Measures whether you can hit a specific key on demand, and how long each one takes.

**3. Phrase** — type `the quick brown fox`. Measures real words per minute and error rate.

## Press methods

Switch live with number keys. **Test all three** — they behave very differently.

| Key | Method | What you do |
|-----|--------|-------------|
| `1` | **pinch** | Touch thumb and index together. Vision Pro style. Usually the most reliable. |
| `2` | **dwell** | Hover over a key for 600ms. Forgiving but slow. |
| `3` | **push** | Poke forward toward the camera. Feels most like a real key — and is the least reliable, because a webcam can barely see depth. |

## Controls

```
n     next phase (skip)
r     restart current phase
1/2/3 switch press method
q     quit and print the report
```

## How to read the result

The script prints PASS/FAIL per phase against these thresholds:

- **Drift** under 0.40 key widths
- **Target accuracy** at or above 90%
- **Speed** at or above 20 wpm with under 10% errors

For reference: a **phone keyboard is ~35 wpm**. **Voice dictation is ~150 wpm.**

If air typing lands at 12 wpm with 20% errors, that's your answer — and you found it out in an afternoon.

## Test it properly

Do not just test at your desk in good light. The thing you're actually trying to learn is whether this works **in the real environment**.

- Sit at **realistic distance** — 1–1.5m, not 40cm. Precision falls off fast with distance.
- Try it **side-lit**, not front-lit.
- Try it with **one hand only** (the whole premise is your other hand is busy).
- Note **when your arm starts to ache**. Write the number down. That's the real ceiling.

Run the same phase two or three times before believing a number. First attempts are always worse.

Results are saved to `results_<timestamp>.json` so you can compare methods and sessions.
