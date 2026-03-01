# Phase 3: Dynamic Fishing Bot Navigation

## Why
Fishing holes in ESO spawn randomly from ~496 known positions per zone.
Fixed routes don't work — holes despawn/respawn unpredictably.
Bot should visit all known spawn points from HarvestMap data dynamically.

## Core Problem: Player Position
ESO writes SavedVariables to disk only on `/reloadui` (not real-time).

**Solution — "blind navigation":**
1. `/reloadui` → read coordinates from disk (~5 sec)
2. Calculate bearing + distance to target hole
3. Rotate camera → sprint blind for `distance / speed` seconds
4. `/reloadui` → verify arrival
5. If not arrived — correct and repeat

## Files

### 1. `fishing/navigation.py` — Fix + add utilities
- Fix `read_player_position()`: read from SavedVariables (currently broken ChatLog reader)
- Add `force_reloadui_and_read()`: send `/reloadui`, wait for file update, return position
- Add `move_blind_segment()`: rotate to target, sprint blind for calculated duration

### 2. `fishing/dynamic_navigator.py` — NEW, core logic
Class `DynamicNavigator`:
- Loads all 496 spawn points from HarvestMap data
- `find_nearest_unvisited(x, y)` — nearest unvisited hole
- `navigate_to_hole()` — loop: `/reloadui` → rotate → sprint → verify
- `detect_water_type()` — OCR screen for "река/озеро/море" text
- `run_circuit()` — main loop: find nearest → navigate → check water type → fish/skip
- Tracks `visited`, `fished`, `empty` sets per circuit

Constants (need calibration):
- `ARRIVAL_THRESHOLD = 15.0`
- `SPRINT_SPEED = 550.0` units/sec
- `MAX_BLIND_MOVE_SEC = 10.0`
- `PROBE_CASTS = 2`

### 3. `fishing/fishing_bot.py` — Add dynamic mode
- CLI: `python fishing_bot.py --dynamic glenumbra`
- New `fishing_dynamic_loop(zone_name)` function

### 4. `fishing/route_recorder.py` — Deduplicate
- Import `force_reloadui_and_read` from `navigation.py`

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

Implementation: screenshot center screen → Tesseract OCR or template matching.

## Calibration (in-game)
1. **Sprint speed** — sprint between 2 known points, measure time
2. **Mouse sensitivity** — rotate 360° in game, count pixels
3. **Arrival threshold** — start at 15, adjust based on accuracy
