# Phase 3: Dynamic Fishing Bot Navigation ⏸️ ЗАМОРОЖЕНА

> **Статус:** Реализована и протестирована, но заморожена в пользу Phase 4 (YOLO AI).
> Код сохранён и может быть использован как fallback если Phase 4 не оправдает ожиданий.

## Why
Fishing holes in ESO spawn randomly from ~496 known positions per zone.
Fixed routes don't work — holes despawn/respawn unpredictably.
Bot should visit all known spawn points from HarvestMap data dynamically.

## Status: IMPLEMENTED ✅, FROZEN ⏸️

### What was done:
- [✅] `fishing/navigation.py` — rewritten: SavedVariables reader, `force_reloadui_and_read()`, `move_blind_segment()`
- [✅] `fishing/dynamic_navigator.py` — `DynamicNavigator` class, visits all ~496 spawn points per zone
- [✅] `fishing/fishing_bot.py` — added `--dynamic ZONE` CLI flag
- [✅] `fishing/calibrate.py` — sprint speed + mouse sensitivity calibration tool
- [✅] Calibration done: `SPRINT_SPEED=968.6`, `MOUSE_SENSITIVITY=685.5`
- [✅] HarvestMap community data parser working (binary format decoded)

### Why frozen:
- `/reloadui` takes 5-8 seconds per call — major bottleneck for navigation
- Phase 4 (YOLO AI) uses visual navigation via map + compass — no `/reloadui` needed
- Phase 4 is more flexible and "intelligent" (sees the game world)

## Core Problem: Player Position
ESO writes SavedVariables to disk only on `/reloadui` (not real-time).

**Solution — "blind navigation":**
1. `/reloadui` → read coordinates from disk (~5 sec)
2. Calculate bearing + distance to target hole
3. Rotate camera → sprint blind for `distance / speed` seconds
4. `/reloadui` → verify arrival
5. If not arrived — correct and repeat

## Files

### 1. `fishing/navigation.py` — ✅ DONE
- `read_player_position()`: reads from FishingNav SavedVariables
- `force_reloadui_and_read()`: sends `/reloadui`, waits for file update, returns position
- `move_blind_segment()`: rotates to target, sprints blind for calculated duration
- `_send_mouse_move()`: Win32 SendInput for mouse (pydirectinput.moveRel doesn't work with ESO)

### 2. `fishing/dynamic_navigator.py` — ✅ DONE
Class `DynamicNavigator`:
- Loads all 496 spawn points from HarvestMap data
- `find_nearest_unvisited(x, y)` — nearest unvisited hole
- `navigate_to_hole()` — loop: `/reloadui` → rotate → sprint → verify
- `detect_water_type()` — OCR screen for "река/озеро/море" text
- `run_circuit()` — main loop: find nearest → navigate → check water type → fish/skip
- Tracks `visited`, `fished`, `empty` sets per circuit

### 3. `fishing/fishing_bot.py` — ✅ DONE
- CLI: `python fishing_bot.py --dynamic glenumbra`

### 4. `fishing/calibrate.py` — ✅ DONE
- Calibrated values: `SPRINT_SPEED=968.6`, `MOUSE_SENSITIVITY=685.5`

## Calibrated Constants
```python
SPRINT_SPEED = 968.6        # World units/sec (calibrated 02.03.26)
MOUSE_SENSITIVITY = 685.5   # Pixels/radian (calibrated 02.03.26)
ARRIVAL_THRESHOLD = 15.0    # Distance to "arrive"
MAX_BLIND_MOVE_SEC = 10.0   # Max sprint per segment
PROBE_CASTS = 2             # Failed casts before skipping
```

## Algorithm (one circuit)
```
1. /reloadui → get position
2. Find nearest unvisited hole from 496 spawns
3. Navigate: /reloadui → rotate → sprint blind → /reloadui → check distance
4. Arrived (dist < 15)?
   a. OCR screen for water type text
   b. "на реке" (river) → fish_one_hole() until depleted
   c. Other water type (lake/sea/swamp) → skip
   d. No text (hole not spawned) → skip
5. Mark hole as visited
6. Repeat from step 2
7. All holes visited → new circuit (reset visited set)
```

## Water Type Detection (OCR)
ESO shows text at screen center when near a fishing hole:
- "Место для рыбалки на реке" — river → FISH (bait: insect parts)
- "Место для рыбалки на озере" — lake → SKIP
- "Место для рыбалки на море" — sea → SKIP
- No text → no hole → SKIP

Implementation: screenshot center screen → threshold white text → Tesseract OCR (fallback: white pixel ratio).

---

## Phase 4: YOLO AI Replacement (ACTIVE) 🟢

Phase 4 replaces Phase 3's blind navigation with visual AI:
- See `fishing/AI fishing gibrid/` for code
- Uses YOLOv8s trained on ESO screenshots (4 classes)
- Navigates via in-game map + compass instead of /reloadui coordinates
- See plan details in the session where Phase 4 was developed
