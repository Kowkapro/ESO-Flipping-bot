# Auto Fishing Bot — Implementation Plan

> **Goal:** Automate the fishing loop in ESO (cast → detect hook → reel in → loot → repeat)
> **Approach:** Pixel brightness detection (simplest, ~100 lines of Python)
> **Server:** NA PC/Mac megaserver

---

## How ESO Fishing Works

1. Player stands near a fishing hole and presses **E** to cast
2. Wait 5-20 seconds — the bobber floats on water
3. A **white hook icon** appears on screen center — fish is on the line
4. Player presses **E** to reel in the fish
5. A loot window appears — player presses **R** to take the fish
6. Repeat from step 1 until the fishing hole is depleted (15-20 catches)

---

## Tech Stack

| Library | Purpose |
|---------|---------|
| `mss` | Fast screen capture (~60 FPS capable) |
| `numpy` | Pixel array analysis (brightness detection) |
| `pynput` | Keyboard input simulation (press E, R) |
| `time` + `random` | Human-like random delays |

**No OpenCV needed** for the simplest version — we just check pixel brightness in a small region.

---

## Implementation Steps

### Step 1: Capture the Detection Area
- Define a small rectangle in the center of the screen where the hook icon appears
- The hook icon is a **bright white symbol** — easy to detect by brightness threshold
- User needs to provide: screen resolution, UI scale, and a screenshot of the hook icon for reference

### Step 2: Brightness Detection Logic
```
1. Capture the detection region (e.g., 100x100 pixels at screen center)
2. Convert to grayscale
3. Count pixels above brightness threshold (e.g., > 240 out of 255)
4. If bright pixel count > threshold → hook detected
```

### Step 3: Fishing Loop
```
LOOP:
  1. Press E (cast the rod)
  2. Wait 2-3 sec (casting animation)
  3. Start scanning screen for hook icon:
     - Capture region every 200ms
     - Check brightness
     - Timeout after 45 sec (in case of missed fish or empty hole)
  4. Hook detected → random delay 0.3-0.8 sec (human-like)
  5. Press E (reel in)
  6. Wait 1-2 sec (reeling animation)
  7. Press R (loot the fish)
  8. Wait 1-2 sec (loot animation)
  9. GOTO 1
```

### Step 4: Safety Features
- **Hotkey to start/stop** (e.g., F9 to toggle, F10 to quit)
- **Random delays** between all actions (gaussian distribution, not fixed)
- **Max iterations limit** — stop after N catches (configurable)
- **Timeout protection** — if no hook detected for 45 sec, stop or re-cast
- **Logging** — local log file with timestamps for debugging

### Step 5: Calibration Mode
- A helper mode where the user can:
  - See what the bot "sees" (show captured region)
  - Adjust detection region position/size
  - Adjust brightness threshold
  - Test detection without pressing keys

---

## File Structure

```
fishing/
  auto_fishing_plan.md    ← this file
  auto_fishing.py         ← main bot script
  config.py               ← detection region, thresholds, delays
  calibrate.py            ← calibration helper tool
  README.md               ← usage instructions (if needed)
```

---

## Configuration (config.py)

```python
# Screen region where hook icon appears (x, y, width, height)
DETECTION_REGION = (900, 500, 120, 120)  # adjust per resolution

# Brightness threshold (0-255, white hook is ~240+)
BRIGHTNESS_THRESHOLD = 240

# Minimum bright pixels to trigger detection
MIN_BRIGHT_PIXELS = 50

# Delays (seconds) — randomized within range
CAST_DELAY = (2.0, 3.0)         # after pressing E to cast
REEL_DELAY = (0.3, 0.8)         # after detecting hook, before pressing E
LOOT_DELAY = (1.0, 2.0)         # after reeling, before pressing R
RECAST_DELAY = (1.5, 2.5)       # after looting, before next cast

# Safety
MAX_CATCHES = 100                # stop after N catches
HOOK_TIMEOUT = 45                # seconds to wait for hook before timeout
SCAN_INTERVAL = 0.2              # seconds between screen captures

# Controls
HOTKEY_TOGGLE = "f9"             # start/stop fishing
HOTKEY_QUIT = "f10"              # quit the bot
```

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Ban for botting | Random human-like delays, don't run 24/7, take breaks |
| Hook not detected | Calibration mode, adjustable threshold |
| UI overlays blocking detection | Hide all UI except crosshair (ESO setting) |
| Fish hole depleted | Timeout detection → stop or alert |
| Screen resolution changes | Config-based region, recalibrate if needed |

---

## Next Steps (Future Scripts)

- `auto_fishing_v2.py` — OpenCV template matching for more reliable detection
- `fish_hole_finder.py` — detect and walk to nearby fishing holes
- `bait_manager.py` — auto-select correct bait for water type
- `fishing_route.py` — automated route between fishing holes in a zone
