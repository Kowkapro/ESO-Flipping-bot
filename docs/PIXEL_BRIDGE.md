# Pixel Bridge — Real-time ESO Data via Pixel Encoding

> **Status**: IMPLEMENTED & TESTED (Steps 1-4 complete)
> **Replaces**: Phase 4 YOLO-based navigation (`fishing/main.py`)
> **Last updated**: 2026-03-06

---

## Overview

ESO Lua addon renders RGB-colored pixel blocks encoding game data (coordinates, heading, flags). Python reads pixels from screen capture — instant, 100% accurate, no file I/O.

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
| - isSwimming flag       |           | - 17 holes from JSON route|
| - isReticleHidden flag  |           | - calc bearing + distance |
|                         |           | - rotate + sprint         |
| Renders 5 colored       |           | - stop when dist < 800    |
| 8x8px blocks at (0,0)   |           | - fish when addon signals |
+-------------------------+           +---------------------------+
```

### Why Pixel Bridge (vs Phase 4 YOLO)

| Aspect | Phase 4 (YOLO) | Pixel Bridge |
|--------|----------------|-------------|
| Player position | Screen center guess | Exact world coordinates (every frame) |
| Navigation | Compass marker tracking (35px, drifts) | Exact bearing from coordinates |
| Arrival detection | Marker jump / OCR / circling | `distance < 800 units` (exact) |
| Fishing prompt | OCR 200-300ms (misses while running) | Addon API, encoded in pixels (~16ms) |
| Combat detection | YOLO enemy class (weak) | `EVENT_PLAYER_COMBAT_STATE` from game API |
| Swimming detection | Not possible | `IsUnitSwimming("player")` from game API |

### What YOLO Still Does

- **Fishing bite detection** (white hook icon from Votan's Fisherman) — replaced by mss-based `detect_hook_mss()` in main_v5 (same pixel approach, no YOLO model needed)

---

## Pixel Protocol

**Position**: top-left corner of screen, `(0,0)` to `(40,8)`

5 blocks, each 8x8 pixels, using `CT_BACKDROP` controls:

| Block | R | G | B | Description |
|-------|---|---|---|-------------|
| 0 | `0xAA` | `0x55` | `0xCC` | Sync marker (validates bar is visible) |
| 1 | X_high | X_mid | X_low | worldX encoded as 3 bytes (0-16,777,215) |
| 2 | Y_high | Y_mid | Y_low | worldY encoded as 3 bytes |
| 3 | H_high | H_low | flags | heading (0-65535 -> 0-2pi) + flags byte |
| 4 | checksum | `0x00` | `0x00` | XOR of all 9 data bytes (blocks 1-3) |

### Flags byte (block 3, blue channel)

| Bit | Value | Flag | Source API |
|-----|-------|------|-----------|
| 0 | 1 | `inCombat` | `EVENT_PLAYER_COMBAT_STATE` |
| 1 | 2 | `hasInteraction` | `GetGameCameraInteractableActionInfo()` |
| 2 | 4 | `isFishing` | interactableName contains "рыбалк" |
| 3 | 8 | `reticleHidden` | `IsReticleHidden()` |
| 4 | 16 | `isSwimming` | `IsUnitSwimming("player")` |
| 5-7 | — | reserved | — |

**Reading**: Python samples center pixel of each 8x8 block (offset +4,+4) to avoid anti-aliasing edges. Sync marker tolerance: +/-2 per channel.

---

## Files

| File | Description |
|------|-------------|
| `AddOns/FishingNav/FishingNav.lua` | ESO addon: pixel rendering + event listeners + polling |
| `fishing/pixel_bridge.py` | Python pixel reader + decoder, `PlayerState` dataclass |
| `fishing/main_v5.py` | Route-based navigation bot (navigate + fish + combat) |
| `fishing/route_holes.json` | 17 manually recorded fishing holes (Glenumbra river) |

---

## ESO Coordinate System (reverse-engineered)

- `GetUnitRawWorldPosition("player")` returns `_, worldX, worldZ, worldY` (**Z/Y swapped!**)
- `GetMapPlayerPosition("player")` returns `mapX, mapY, heading`
- Heading 0 = North (Y decreasing), increases **counter-clockwise**
- 90° = West, 180° = South, 270° = East
- Bearing formula: `atan2(-dx, -dy)`
- Mouse conversion: `-angle / (2*pi) * PIXELS_PER_360` (9300 px at 800 DPI, speed 15)

---

## ESO API Reference (used by addon)

### Currently used

| API | Returns | Usage |
|-----|---------|-------|
| `GetUnitRawWorldPosition("player")` | `_, worldX, worldZ, worldY` | Player coordinates |
| `GetMapPlayerPosition("player")` | `mapX, mapY, heading` | Character heading (NOT camera) |
| `GetGameCameraInteractableActionInfo()` | `action, interactableName` | What's under reticle |
| `IsUnitSwimming("player")` | `bool` | Swimming state |
| `IsReticleHidden()` | `bool` | Reticle hidden (during cast animation) |
| `EVENT_PLAYER_COMBAT_STATE` | `_, inCombat` | Combat enter/exit |
| `BitXor(a, b)` | `int` | XOR for checksum (built-in, no zo_ prefix) |

### Available for future use

| API | Returns | Potential use |
|-----|---------|--------------|
| `GetNumBagFreeSlots(BAG_BACKPACK)` | `int` | Stop when inventory full |
| `IsUnitDead("player")` | `bool` | Detect death, need respawn |
| `IsMounted("player")` | `bool` | Mount for faster travel between holes |
| `GetUnitPower("player", POWERTYPE_HEALTH)` | `current, max` | HP monitoring, heal if low |
| `GetUnitPower("player", POWERTYPE_STAMINA)` | `current, max` | Stamina for sprint |
| `GetTimeOfDay()` | `float 0.0-1.0` | In-game time |
| `GetItemLink(BAG_BACKPACK, slot)` | `string` | What was caught (statistics) |
| `GetNumLootItems()` | `int` | Verify all loot picked up |
| `HasActiveAction()` | `bool` | Animation in progress |

### Known API limitations

- `GetMapPlayerPosition('reticleover')` disabled since ESO v1.2.3 (anti-bot)
- `GetInteractionType()` returns 0 for fishing holes — **does NOT work**
- `DoesUnitExist("reticleover")` returns false for fishing holes
- `RequestAddOnSavedVariablesPrioritySave` unreliable — ESO may skip saves
- Heading = character direction, NOT camera — need W step after mouse turn

---

## Navigation Architecture (main_v5.py)

1. Load route from `route_holes.json` (17 holes, sequential cyclic)
2. Start from nearest hole
3. Sprint with course correction every 100ms (bearing -> mouse pixels)
4. During nav: check flags every frame
   - `in_combat=True` -> stop -> spam AoE key '5' -> resume
   - `is_fishing=True` and NOT `is_swimming` -> stop -> fish
   - `is_fishing=True` and `is_swimming` -> ignore, keep running
   - `has_interaction=True` but not fishing -> ignore
5. On "arrived" (dist < 800) without prompt -> `look_for_fishing_hole` (360° rotation, 30° steps)
6. On "fishing" -> press E -> `fish_one_hole` (cast/detect/reel/loot cycle)
7. Stuck detection: 3 sec no movement -> escalating recovery (jump -> backtrack -> sidestep -> random -> skip)

### Hook Bite Detection

Uses `detect_hook_mss(sct)` — captures center 270x270px region via `mss`, converts to grayscale, checks white pixel ratio > 8% (Votan's Fisherman addon shows white hook icon on bite). Uses same `mss` instance as pixel bridge (no ImageGrab conflict).

---

## Known Issues

- `mss` can't run in keyboard hook thread — use queue to main thread
- `keyboard` lib auto-repeats on key hold — need debounce for recorders
- Addon: check `pixelBridgeReady` before `CreatePixelBlocks` (duplicate name crash on /reloadui)
- `CT_TEXTURE` does NOT work for colored blocks — use `CT_BACKDROP`
- `TopLevelWindow` required as parent for UI to render above HUD
- `pixelBridgeReady` guard needed — `OnPlayerActivated` fires on `/reloadui` too
- `ImageGrab.grab()` conflicts with active `mss.mss()` context — use only mss
- Fishing prompt detected while sprinting: character overshoots, reticle moves off hole (partial fix: check distance)

---

## Comparison with Other Approaches

### vs FishyBot QR Code

| Aspect | FishyBot QR | Our Pixel Bridge |
|--------|-------------|-----------------|
| Data transfer | QR code on screen | RGB pixel blocks |
| Decode speed | ~50-100ms (pyzbar) | **~1ms** (direct pixel read) |
| Screen space | Large QR visible | 40x8px, barely visible |
| Robustness | QR can fail with post-processing | Sync marker + checksum + tolerance |

### vs SavedVariables + /reloadui

| Aspect | SavedVariables | Pixel Bridge |
|--------|---------------|-------------|
| Update speed | 5-8 sec (reload delay) | **Every frame (~16ms)** |
| Game interruption | /reloadui freezes game | None |

### vs Memory Reading (banned)

| Aspect | Memory reading | Pixel Bridge |
|--------|---------------|-------------|
| ToS violation | **Yes — bannable** | No — reads screen pixels |
| Detection risk | High (process inspection) | Low (external screen capture) |

---

## Future: Extended Protocol (blocks 5-7)

| Block | R | G | B | Use case |
|-------|---|---|---|----------|
| 5 | bag_free_slots | is_dead | is_mounted | Inventory + death + mount state |
| 6 | hp_pct | stamina_pct | magicka_pct | Player resources (0-255 = 0-100%) |
| 7 | reserved | reserved | reserved | — |

Adding new blocks requires:
1. Lua: create block in `CreatePixelBlocks`, encode in `PixelUpdate`, update checksum
2. Python: extend `PlayerState`, decode new block in `read_player_state`
3. Update block dimensions: `tlw:SetDimensions(N*8, 8)`, region width in Python
