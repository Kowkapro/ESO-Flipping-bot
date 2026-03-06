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

### Files Overview

| File | Action | Description |
|------|--------|-------------|
| `AddOns/FishingNav/FishingNav.lua` | MODIFY | Add pixel rendering + interaction event listeners |
| `AddOns/FishingNav/FishingNav.txt` | MODIFY | Bump version to 2.0 |
| `fishing/pixel_bridge.py` | CREATE | Pixel reader + decoder module |
| `fishing/main_v5.py` | CREATE | New navigation loop (replaces main.py for testing) |
| `fishing/main.py` | KEEP | Don't delete — fallback to YOLO approach |

---

### Step 1: FishingNav Addon v2 — Pixel Rendering

**Goal**: Addon draws 5 colored 8x8px blocks in top-left corner, updated every frame.

**Current state** of `FishingNav.lua`:
- Exports `worldX`, `worldY`, `worldZ`, `heading`, `zoneId`, `inCombat` to `FishingNav_Data` (SavedVariables)
- Updates every 500ms via `RegisterForUpdate`
- Uses `RequestAddOnSavedVariablesPrioritySave` (unreliable for real-time)

**What to change**:

1. **Keep** the existing SavedVariables export (backward-compatible, useful for debugging)
2. **Add** 5 `CT_TEXTURE` controls created on `EVENT_PLAYER_ACTIVATED`
3. **Add** `OnUpdate` handler that encodes data into pixel colors every frame
4. **Add** event listeners for interaction and combat state
5. **Bump** version in `.txt` to 2.0

**Lua implementation details**:

```lua
-- 1. Create 5 pixel blocks (8x8 each), anchored to top-left
local pixels = {}
for i = 0, 4 do
    local px = WINDOW_MANAGER:CreateControl("FN_Px"..i, GuiRoot, CT_TEXTURE)
    px:SetDimensions(8, 8)
    px:SetAnchor(TOPLEFT, GuiRoot, TOPLEFT, i * 8, 0)
    px:SetColor(0, 0, 0, 1)
    px:SetDrawLevel(DL_OVERLAY)
    px:SetDrawTier(DT_HIGH)
    pixels[i] = px
end

-- 2. State flags (updated by events + OnUpdate polling)
local flags = { inCombat = false, hasInteraction = false, isFishing = false, reticleHidden = false }

-- 3. Event listeners
EVENT_MANAGER:RegisterForEvent(ADDON_NAME, EVENT_PLAYER_COMBAT_STATE, function(_, inCombat)
    flags.inCombat = inCombat
end)

-- 4. OnUpdate: encode data into pixel colors
local function PixelUpdate()
    local _, worldX, _, worldY = GetUnitRawWorldPosition("player")
    local _, _, heading = GetMapPlayerPosition("player")

    -- Check interaction (polled every frame since no reliable event)
    flags.hasInteraction = DoesUnitExist("reticleover")
    flags.isFishing = (GetInteractionType() == INTERACTION_FISH)
    flags.reticleHidden = IsReticleHidden()

    -- Encode worldX (3 bytes), worldY (3 bytes), heading (2 bytes), flags (1 byte)
    -- Block 0: sync marker 0xAA, 0x55, 0xCC
    pixels[0]:SetColor(0xAA/255, 0x55/255, 0xCC/255, 1)

    -- Block 1: worldX as 3 bytes (values 0 — 16,777,215)
    local xInt = math.floor(worldX) -- worldX is integer-scale in ESO
    pixels[1]:SetColor(
        math.floor(xInt / 65536) % 256 / 255,
        math.floor(xInt / 256) % 256 / 255,
        xInt % 256 / 255, 1)

    -- Block 2: worldY as 3 bytes
    local yInt = math.floor(worldY)
    pixels[2]:SetColor(
        math.floor(yInt / 65536) % 256 / 255,
        math.floor(yInt / 256) % 256 / 255,
        yInt % 256 / 255, 1)

    -- Block 3: heading (2 bytes) + flags (1 byte)
    local hInt = math.floor(heading / (2 * math.pi) * 65535)
    local flagByte = (flags.inCombat and 1 or 0)
                   + (flags.hasInteraction and 2 or 0)
                   + (flags.isFishing and 4 or 0)
                   + (flags.reticleHidden and 8 or 0)
    pixels[3]:SetColor(
        math.floor(hInt / 256) / 255,
        hInt % 256 / 255,
        flagByte / 255, 1)

    -- Block 4: checksum (XOR of 9 data bytes from blocks 1-3)
    local bytes = { ... } -- all 9 bytes
    local checksum = 0
    for _, b in ipairs(bytes) do checksum = BitXor(checksum, b) end
    pixels[4]:SetColor(checksum / 255, 0, 0, 1)
end

-- 5. Register OnUpdate at max frequency (0ms = every frame)
EVENT_MANAGER:RegisterForUpdate(ADDON_NAME.."_Pixels", 0, PixelUpdate)
```

**Key API notes**:
- `GetUnitRawWorldPosition("player")` returns `_, worldX, worldZ, worldY` (Z/Y swapped!)
- `GetMapPlayerPosition("player")` returns `mapX, mapY, heading` — heading is **character** direction, NOT camera
- `SetColor(r, g, b, a)` uses floats 0.0–1.0, NOT 0–255
- `DoesUnitExist("reticleover")` — checks if player is looking at interactable object
- `GetInteractionType()` returns `INTERACTION_FISH` when near fishing hole
- `IsReticleHidden()` — true during fishing cast animation
- `BitXor` — ESO has `BitAnd`, `BitOr`, `BitXor` built-in (zo_ prefix not needed)

**Testing step 1**:
1. Copy modified addon to `AddOns/FishingNav/`
2. Launch ESO, check chat for "FishingNav: tracking started"
3. Visually confirm 5 tiny colored blocks in top-left corner
4. Move character — block colors should change
5. Approach fishing hole — verify flag changes (block 3 blue channel)

---

### Step 2: Python Pixel Reader (`pixel_bridge.py`)

**Goal**: Read 5 pixel blocks from screen, decode into `PlayerState`, validate with sync marker + checksum.

**Dependencies**: `mss` (already installed), `dataclasses`

```python
# fishing/pixel_bridge.py
from dataclasses import dataclass
import math
import mss

@dataclass
class PlayerState:
    x: float           # world X coordinate (integer-scale)
    y: float           # world Y coordinate (integer-scale)
    heading: float     # radians, 0=North, CW
    in_combat: bool
    has_interaction: bool
    is_fishing: bool
    reticle_hidden: bool

# Pixel block positions: center of each 8x8 block
BLOCK_CENTERS = [(i * 8 + 4, 4) for i in range(5)]  # (x, y) offsets
SYNC_MARKER = (0xAA, 0x55, 0xCC)
SYNC_TOLERANCE = 2  # +/- per channel

def read_player_state(sct: mss.mss, monitor: dict) -> PlayerState | None:
    """Read pixel bar from top-left corner, decode, validate."""
    region = {"left": monitor["left"], "top": monitor["top"], "width": 40, "height": 8}
    img = sct.grab(region)

    # Sample center pixel of each 8x8 block
    blocks = []
    for bx, by in BLOCK_CENTERS:
        pixel = img.pixel(bx, by)  # returns (R, G, B)
        blocks.append(pixel)

    # Validate sync marker (block 0) with tolerance
    for i in range(3):
        if abs(blocks[0][i] - SYNC_MARKER[i]) > SYNC_TOLERANCE:
            return None  # bar not visible or corrupted

    # Decode blocks 1-3
    r1, g1, b1 = blocks[1]  # worldX
    r2, g2, b2 = blocks[2]  # worldY
    r3, g3, b3 = blocks[3]  # heading + flags

    # Validate checksum (block 4)
    data_bytes = [r1, g1, b1, r2, g2, b2, r3, g3, b3]
    checksum = 0
    for b in data_bytes:
        checksum ^= b
    if checksum != blocks[4][0]:
        return None  # checksum mismatch

    # Decode values
    world_x = r1 * 65536 + g1 * 256 + b1
    world_y = r2 * 65536 + g2 * 256 + b2
    heading_int = r3 * 256 + g3
    heading = heading_int / 65535.0 * 2 * math.pi
    flags = b3

    return PlayerState(
        x=float(world_x), y=float(world_y), heading=heading,
        in_combat=bool(flags & 1),
        has_interaction=bool(flags & 2),
        is_fishing=bool(flags & 4),
        reticle_hidden=bool(flags & 8),
    )
```

**Standalone test mode** (run `python pixel_bridge.py`):
```python
if __name__ == "__main__":
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        while True:
            state = read_player_state(sct, monitor)
            if state:
                print(f"X={state.x:.0f} Y={state.y:.0f} H={math.degrees(state.heading):.1f}° "
                      f"combat={state.in_combat} interact={state.has_interaction} fish={state.is_fishing}")
            else:
                print("-- pixel bar not detected --")
            time.sleep(0.1)
```

**Testing step 2**:
1. ESO running with addon v2 visible
2. Run `python pixel_bridge.py` — should print coordinates every 100ms
3. Compare printed `X, Y` with `/script d(GetUnitRawWorldPosition("player"))` in ESO chat
4. Walk around — coordinates update in real-time
5. Approach fishing hole — `fish=True` should appear
6. Enter combat — `combat=True` should appear

---

### Step 3: Navigation Module (`main_v5.py`)

**Goal**: Navigate to nearest fishing hole using exact coordinates, fish, repeat.

**Reuse from existing code** (import, don't copy):

| Source | What | How |
|--------|------|-----|
| `harvestmap_parser.py` | `get_fishing_holes(zone)` | Returns list of `(x, y)` hole coordinates |
| `config.py` | `PIXELS_PER_360`, `SPRINT_SPEED` | Calibrated constants |
| `main.py` | `press_key()`, `send_mouse_move()` | Input functions |
| `main.py` | `detect_hook_bite()`, `phase_d_fish()` | Fishing cycle |

**Main loop pseudocode**:

```
INIT:
    holes = get_fishing_holes("Glenumbra")   # ~496 holes from HarvestMap
    visited = set()
    sct = mss.mss()
    monitor = sct.monitors[1]

LOOP:
    1. state = read_player_state(sct, monitor)
       if state is None: wait 1s, retry (loading screen / menu)

    2. if state.in_combat:
       handle_combat()  # run away or wait
       continue

    3. target = find_nearest_unvisited(state.x, state.y, holes, visited)
       if target is None: log("all holes visited"), stop

    4. distance = euclidean(state, target)
       bearing = atan2(target.x - state.x, target.y - state.y)  # ESO coordinate system
       turn_angle = normalize(bearing - state.heading)

    5. # Rotate camera
       mouse_delta = turn_angle / (2 * pi) * PIXELS_PER_360
       send_mouse_move(mouse_delta)
       sleep(0.05)

    6. # Take one step to sync character heading with camera
       press_key('w', duration=0.15)

    7. # Sprint toward target
       hold_key('w')
       hold_key('shift')  # sprint

    8. # Course correction loop (every 100ms)
       prev_pos = (state.x, state.y)
       stuck_timer = 0
       while distance > ARRIVAL_THRESHOLD:  # ~20-30 world units
           state = read_player_state(sct, monitor)
           if state is None: continue

           distance = euclidean(state, target)
           # Correct heading
           bearing = atan2(target.x - state.x, target.y - state.y)
           error = normalize(bearing - state.heading)
           if abs(error) > 0.05:  # ~3 degrees deadzone
               send_mouse_move(error / (2*pi) * PIXELS_PER_360)

           # Stuck detection
           moved = euclidean((state.x, state.y), prev_pos)
           if moved < 5:
               stuck_timer += 0.1
               if stuck_timer > 3.0:
                   execute_recovery(...)
                   stuck_timer = 0
           else:
               stuck_timer = 0
           prev_pos = (state.x, state.y)

           # Check for fishing interaction
           if state.is_fishing:
               break

           sleep(0.1)

    9. release_key('w')
       release_key('shift')

   10. # Fish if we have interaction
       if state.is_fishing:
           press_key('e')  # start fishing
           # ... fishing cycle (cast -> bite detection -> reel -> loot)
           phase_d_fish()

   11. visited.add(target)
       goto LOOP
```

**Key decisions**:
- `ARRIVAL_THRESHOLD = 20-30` world units — needs calibration in-game
- Course correction deadzone `0.05 rad (~3°)` — prevents oscillation
- Heading sync: one W step after rotation (known fix from Phase 3)
- `atan2(dx, dy)` not `atan2(dy, dx)` — ESO uses X=East, Y=North coordinate system (verify!)

**Testing step 3**:
1. Stand near a known fishing hole in Glenumbra
2. Run bot — verify it rotates toward nearest hole
3. Verify it walks to the hole and stops
4. Verify it starts fishing when `is_fishing` flag activates
5. Verify one complete fishing cycle (cast → bite → reel → loot)
6. Verify it moves to the next hole after fishing

---

### Step 4: Stuck Detection & Recovery

**Goal**: Detect when bot is stuck and recover automatically.

**Already integrated into step 3** (coords-based detection), but needs escalating recovery:

```python
RECOVERY_LEVELS = [
    ("jump",      lambda: [press_key('space') for _ in range(3)]),
    ("backtrack", lambda: hold_key('s', duration=1.5)),
    ("sidestep",  lambda: hold_key(random.choice(['a','d']), duration=1.5)),
    ("random",    lambda: random_walk(duration=3.0)),
    ("skip",      lambda: None),  # mark hole as visited, move to next
]

def execute_recovery(level: int, target, visited):
    if level >= len(RECOVERY_LEVELS):
        visited.add(target)  # give up on this hole
        return
    name, action = RECOVERY_LEVELS[level]
    log(f"Stuck recovery: {name} (level {level})")
    action()
```

**Testing step 4**:
1. Manually position bot facing a wall
2. Run navigation — verify stuck detection triggers after 3s
3. Verify escalating recovery (jump → backtrack → sidestep → skip)
4. Verify bot resumes navigation after recovery

---

### Step 5: Full Integration & Polish

**Goal**: Complete bot loop running autonomously for 30+ minutes.

**Checklist**:
- [ ] Telegram notifications (reuse from existing bot): start, stop, holes fished, errors
- [ ] Hotkeys: F5 start/pause, F6 stop (reuse from existing bot)
- [ ] Inventory full detection — stop fishing, notify user
- [ ] Zone transition handling — if zone changes, reload HarvestMap holes
- [ ] Session stats: holes fished, fish caught, time elapsed
- [ ] Random delays between actions (anti-detection, already in `press_key()`)

**Testing step 5**:
1. Supervised run: 30 min, observe for issues
2. Count: holes visited, fish caught, stuck events, recovery success rate
3. Compare with Phase 4 YOLO bot performance
4. Fix any issues found during supervised run

---

## Implementation Order & Dependencies

```
Step 1: FishingNav Addon v2        (no dependencies)
  │
  ▼
Step 2: pixel_bridge.py            (depends on Step 1 running in ESO)
  │
  ▼
Step 3: main_v5.py navigation      (depends on Step 2 + existing code)
  │
  ▼
Step 4: Stuck detection & recovery (integrated into Step 3)
  │
  ▼
Step 5: Full integration & polish  (depends on Steps 3-4 working)
```

**Estimated effort per step**:
- Step 1: Lua addon — small file, ~80 lines total
- Step 2: Python reader — ~60 lines, straightforward
- Step 3: Navigation — ~200 lines, most complex (reuses existing functions)
- Step 4: Recovery — ~50 lines, simple escalation
- Step 5: Integration — mostly copy from existing `main.py`

**Each step is independently testable** — don't proceed to next step until current one is verified.

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

## Stuck Detection & Error Recovery

Based on research of CRADLE, FishyBot, and other game bot frameworks.

### Stuck Detection (3 methods, ordered by cost)

| Method | How | When to use |
|--------|-----|------------|
| **Coords-based** (primary) | `distance_moved < 5 units` over 3 sec | Every frame — cheapest, uses pixel bridge data |
| **Action repetition** | Same turn+sprint sequence 3+ times without progress | Every navigation cycle |
| **SSIM image similarity** | Compare screenshots, if >0.95 similarity for 5 sec | Backup — if pixel bridge fails |

### Recovery Strategies (escalating)

```
1. Jump (Space x2-3)           — unstick from small obstacles
2. Backtrack (S for 1-2 sec)   — reverse away from wall
3. Sidestep (A/D for 1-2 sec)  — try going around obstacle
4. Random walk (3-5 sec)       — break out of complex geometry
5. Skip hole (mark visited)    — give up on this hole, try next
```

### Implementation in main_v5.py

```python
# In navigation loop (step 8):
prev_pos = None
stuck_timer = 0

while distance > 20:
    state = read_player_state(sct, monitor)
    if prev_pos and euclidean(state.pos, prev_pos) < 5:
        stuck_timer += dt
        if stuck_timer > 3.0:
            execute_recovery(level=1)  # escalate on repeated stuck
            stuck_timer = 0
    else:
        stuck_timer = 0
    prev_pos = state.pos
```

---

## Future Extensibility: Combat & Dungeons

Pixel Bridge is designed as a **foundation layer**. Additional data blocks can be added for combat scenarios without changing the core protocol.

### Extended Protocol (future blocks 5-7)

| Block | R | G | B | Use case |
|-------|---|---|---|----------|
| 5 | target_hp_pct | target_dist_h | target_dist_l | Current target HP + distance |
| 6 | num_enemies | player_hp_pct | player_mag_pct | Nearby enemy count, player resources |
| 7 | ability_ready | buff_flags | debuff_flags | Cooldowns, active effects |

### What Pixel Bridge handles vs what needs YOLO

| Task | Pixel Bridge | YOLO needed? |
|------|-------------|-------------|
| Navigation (any mode) | Coordinates + bearing | No |
| Combat state detection | `IsUnitInCombat()` flag | No |
| Target HP reading | Extended block 5 | No (addon reads HP) |
| Enemy position on screen | No — addon doesn't know screen position | **Yes** |
| AoE zones on ground | No — no addon API for this | **Yes** |
| Targeting (where to aim) | No | **Yes** (or Tab-targeting) |
| Loot pickup | `hasInteraction` flag | No |

**Architecture for dungeons:**
```
Pixel Bridge (foundation):        YOLO (combat overlay):
├── Where am I? (coords)          ├── Where are enemies? (bbox)
├── Where to go? (waypoints)      ├── Red AoE circles? (detection)
├── Am I in combat? (flag)        └── Loot glow? (detection)
├── My HP/Magicka? (block 6)
├── Target HP? (block 5)
└── Route between points (A*)
```

For dungeons, YOLO model can be **lighter** (YOLOv8s) since enemies are large objects, not tiny map icons.

---

## Comparison with Other Approaches

### vs FishyBot QR Code (fishyboteso)

| Aspect | FishyBot QR | Our Pixel Bridge |
|--------|-------------|-----------------|
| Data transfer | QR code on screen | RGB pixel blocks |
| Decode speed | ~50-100ms (pyzbar) | **~1ms** (direct pixel read) |
| Data capacity | Limited by QR size | Extensible (add more blocks) |
| Screen space | Large QR visible to player | 40x8px, barely visible |
| Robustness | QR can fail with post-processing | Sync marker + checksum + tolerance |
| Proven | Yes (thousands of users) | Not yet — needs testing |

### vs SavedVariables + /reloadui (current approach)

| Aspect | SavedVariables | Pixel Bridge |
|--------|---------------|-------------|
| Update speed | 5-8 sec (reload delay) | **Every frame (~16ms)** |
| Data freshness | Stale after 1 step | Always current |
| Game interruption | /reloadui freezes game | None |
| Reliability | File I/O can be slow | Screen capture is fast |

### vs Memory Reading (banned)

| Aspect | Memory reading | Pixel Bridge |
|--------|---------------|-------------|
| Speed | Real-time | Real-time |
| ToS violation | **Yes — bannable** | No — only reads screen pixels |
| Detection risk | High (process inspection) | Low (external screen capture) |
| Data access | Everything | Only what addon exposes |

Pixel Bridge is the **optimal approach**: real-time like memory reading, safe like screen capture, extensible for future needs.
