# Pixel Bridge — Approach #1 for Navigation Rewrite

> **Status**: PLANNED (not implemented yet)
> **Replaces**: Phase 4 YOLO-based navigation (`fishing/main.py`)
> **Date**: 2026-03-06

---

## Problem

YOLO-based navigation (Phase 4) has fundamental issues after 5-6 tests:

| Issue | Root Cause |
|-------|-----------|
| Picks wrong "nearest" hook | Pixel distance on zoomed map != real distance; player_icon bbox center != exact position |
| Runs past fishing holes | EasyOCR takes 200-300ms to read prompt; prompt visible for only 0.2-0.3s while sprinting |
| Circles around waypoint | Compass marker is always ~35px wide regardless of distance; no reliable "arrived" signal |

These are **architectural** problems, not bugs. Patching individual symptoms doesn't help.

---

## Solution: Pixel Bridge

ESO Lua addons can render UI elements on screen. We encode game data (coordinates, heading, interaction state) as RGB pixel colors. Python reads these pixels from screen capture — instant, 100% accurate.

### Architecture

```
ESO Client                              Python Bot
+-------------------------+   screen   +---------------------------+
| FishingNav addon v2     |  capture   | pixel_bridge.py           |
| - worldX, worldY        |---------->| - read 40x8 pixel region  |
| - heading (radians)     |   mss     | - decode RGB -> coords    |
| - inCombat flag         |           | - return PlayerState      |
| - hasInteraction flag   |           |                           |
| - isFishing flag        |           | main_v5.py                |
|                         |           | - HarvestMap: 496 holes   |
| Renders 5 colored       |           | - find nearest unvisited  |
| 8x8px blocks at (0,0)   |           | - calc bearing + distance |
+-------------------------+           | - rotate + sprint         |
                                      | - stop when dist < 20     |
                                      | - fish when addon signals |
                                      +---------------------------+
```

### Why This Works

| Aspect | Phase 4 (YOLO) | Pixel Bridge |
|--------|----------------|-------------|
| Player position | Screen center guess | Exact world coordinates (every frame) |
| Nearest hole | YOLO on map (flickering, misses) | HarvestMap DB: 496 known coordinates |
| Navigation | Compass marker tracking (35px, drifts) | Exact bearing from coordinates |
| Arrival detection | Marker jump / OCR / circling heuristics | `distance < 20 units` (exact) |
| Fishing prompt | OCR 200-300ms (misses while running) | Addon EVENT, encoded in pixels (~16ms) |
| Combat detection | YOLO enemy class (weak) | `IsUnitInCombat()` from game API |

### What YOLO Still Does

- **Fishing bite detection** (white hook icon from Votan's Fisherman) — this works well
- Everything else is replaced by pixel bridge + HarvestMap

---

## Pixel Protocol

**Position**: top-left corner of screen, `(0,0)` to `(40,8)`

5 blocks, each 8x8 pixels:

| Block | R | G | B | Description |
|-------|---|---|---|-------------|
| 0 | `0xAA` | `0x55` | `0xCC` | Sync marker (validates bar is visible and readable) |
| 1 | X_high | X_mid | X_low | worldX encoded as 3 bytes (0 — 16,777,215) |
| 2 | Y_high | Y_mid | Y_low | worldY encoded as 3 bytes |
| 3 | H_high | H_low | flags | heading (0-65535 mapped to 0-2pi), flags byte |
| 4 | checksum | `0x00` | `0x00` | XOR of all 9 data bytes (blocks 1-3) |

**Flags** (block 3, blue channel):
- bit 0: `inCombat` — player is in combat
- bit 1: `hasInteraction` — interaction prompt is visible
- bit 2: `isFishing` — interaction type is fishing
- bit 3: `isReticleHidden` — ESO hides reticle during cast animation

**Reading**: Python samples the center pixel of each 8x8 block (offset +4,+4) to avoid anti-aliasing edges. Tolerance: +/-2 per channel for sync marker validation.

---

## Implementation Plan

### File Changes

| File | Action | Description |
|------|--------|-------------|
| `AddOns/FishingNav/FishingNav.lua` | MODIFY | Add pixel rendering + interaction event listeners |
| `AddOns/FishingNav/FishingNav.txt` | MODIFY | Bump version to 2.0 |
| `fishing/pixel_bridge.py` | CREATE | Pixel reader + decoder module |
| `fishing/main_v5.py` | CREATE | New navigation loop (replaces main.py for testing) |
| `fishing/main.py` | KEEP | Don't delete — fallback to YOLO approach |

### Step 1: FishingNav Addon v2

Modify the custom Lua addon to:
- Create 5 `CT_TEXTURE` controls (8x8px each) anchored to top-left
- Update colors every frame via `OnUpdate` handler
- Listen for interaction events:
  - `EVENT_RETICLE_TARGET_CHANGED`
  - `EVENT_PLAYER_COMBAT_STATE`
  - Check `GetInteractionType()` for `INTERACTION_FISH`

Key Lua API:
```lua
-- Create pixel block
local px = WINDOW_MANAGER:CreateControl("FN_Px"..i, GuiRoot, CT_TEXTURE)
px:SetDimensions(8, 8)
px:SetAnchor(TOPLEFT, GuiRoot, TOPLEFT, i * 8, 0)
px:SetColor(r/255, g/255, b/255, 1)  -- ESO uses 0.0-1.0 floats
px:SetDrawLevel(DL_OVERLAY)
```

### Step 2: Python Pixel Reader

```python
# fishing/pixel_bridge.py
class PlayerState:
    x: float        # world X coordinate
    y: float        # world Y coordinate
    heading: float  # radians, 0=North, CW
    in_combat: bool
    has_interaction: bool
    is_fishing: bool

def read_player_state(sct, monitor) -> PlayerState | None:
    """Read pixel bar, decode, validate checksum. Returns None if bar not visible."""
    region = {"left": monitor["left"], "top": monitor["top"], "width": 40, "height": 8}
    # ... grab, sample centers, decode, validate sync + checksum
```

### Step 3: New Main Loop

```
1. Load HarvestMap fishing holes for zone
2. Read pixel bridge -> player position
3. Find nearest unvisited hole (Euclidean distance)
4. bearing = atan2(hole.y - player.y, hole.x - player.x)
5. turn_angle = normalize(bearing - heading)
6. Rotate camera: turn_angle -> mouse pixels via PIXELS_PER_360
7. Sprint (W + Shift), take step first to sync heading
8. Every 100ms: read pixel bridge -> correct heading + check distance
9. distance < 20 -> stop sprinting
10. flags.is_fishing -> press E, start fishing cycle
11. Fish: cast -> Votan's hook bite detection -> reel -> loot
12. Mark hole visited, go to step 2
```

### Step 4: Testing

1. Run `harvestmap_parser.py` -> verify ~496 Glenumbra holes load
2. Launch ESO with addon v2 -> verify pixel bar visible in top-left
3. Run `pixel_bridge.py` standalone -> decode + print coords, compare with in-game
4. Navigate to 1 hole -> verify arrival
5. Full loop: 3-5 holes -> fish -> verify no circling, no missed holes

---

## Reusable Code from Current Bot

| Module | Function | Reuse |
|--------|----------|-------|
| `harvestmap_parser.py` | `get_fishing_holes()` | As-is, already works |
| `navigation.py` | `_send_mouse_move()` | Win32 SendInput for camera rotation |
| `main.py` | `send_mouse_move()`, `human_mouse_arc()` | Smooth mouse movement |
| `main.py` | `press_key()` | Key input with random delays |
| `main.py` | `detect_hook_bite()` | Votan's hook detection (brightness-based) |
| `main.py` | `phase_d_fish()` | Full fishing cycle (cast/reel/loot) |
| `config.py` | `PIXELS_PER_360`, `SPRINT_SPEED` | Calibrated constants |

---

## Known Risks

| Risk | Mitigation |
|------|-----------|
| ESO post-processing alters pixel colors | 8x8 blocks, sample center pixel, sync marker with tolerance +/-2 |
| Addon UI hidden (loading screen, menus) | Sync marker validation; bot pauses if invalid |
| Heading = character direction, NOT camera | Take one step (W) after each rotation (known fix from Phase 3) |
| HarvestMap holes may not be active | Holes are fixed spawn points; only active/depleted changes; addon detects fishing prompt |
| `GetInteractionType()` timing | Addon checks every frame in OnUpdate, sets flag immediately |

---

## Comparison with Other Approaches

This is **Approach #1** in the navigation rewrite. Other approaches being researched:
- *(to be added as they are discovered)*
