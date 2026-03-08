# NEXT-STEPS — Fishing Bot Progress & Plans

## Session 2026-03-09 — Disconnect Recovery

### Completed & Tested ✅
- `detect_screen_state()` in main_v5.py — screen detection by pixel sampling (NO pixel bridge needed)
  - `error_popup` — popup overlay darkens (960,480), scenic bright at (960,350)
  - `login` — (960,480) bright scenic (sum>200), no left menu
  - `char_select` — left menu text bright (45,360) sum>450
  - `loading` — all points uniform dark gray (RGB ~31,31,31, sum<120)
- `mouse_click_win32()` — Win32 SendInput for mouse clicks (pyautogui.click didn't work with ESO)
- `handle_disconnect()` in main_v5.py — full screen-based reconnect flow
- `test_reconnect.py` — isolated test with screen detection at each step

### Calibrated Button Positions (1920x1080)
- `BTN_VOITI = (960, 648)` — calibrated from pixel scan of debug screenshot
- `BTN_IGRAT = (960, 1050)` — in the button area (scan confirmed y=990-1050 is button zone)
- Detection point `popup_area = (960, 480)` — key discriminator: error_popup vs login

### Screen Detection Pixel Data (confirmed from real screenshots)
| Point | Error popup | Login | Char select | Loading |
|-------|-------------|-------|-------------|---------|
| (960,350) upper | ~247 | ~547 | ~537 | ~93 |
| (960,480) popup | ~30 | ~496 | ~460 | ~93 |
| (960,540) center | ~35 | ~529 | ~245 | ~93 |
| (45,360) left_menu | ~54 | ~119 | ~507 | ~72 |

### Tested Flow (test_reconnect.py, 3 runs)
1. ✅ error_popup detected correctly
2. ✅ Alt closes popup → login screen
3. ✅ ВОЙТИ clicked via mouse_click_win32 → loading (5s) → char_select
4. ✅ char_select detected (left_menu sum=507 > 450)
5. ✅ ИГРАТЬ clicked via mouse_click_win32
6. ❌ Pixel bridge never appeared after 90s — game still loading (loading screen at bridge_failed.png)

### NOT YET CONFIRMED ❌
- **Pixel bridge after reconnect** — after clicking ИГРАТЬ, game still loading at 90s (step3 30s + step4 60s). Updated timeout to 120s in step4 but NOT tested yet.
- **Full successful reconnect** — never got to `read_player_state()` returning valid state after reconnect
- **Reconnect in main_v5.py** (vs test_reconnect.py) — same logic, not tested in real bot run

### Possible Root Causes for Pixel Bridge Failure
1. Total wait (90s) was not enough — updated to 120s, not tested yet
2. Addon not reinitializing after reconnect (OnPlayerActivated may not fire on reconnect?)
3. ESO connection failed again after ИГРАТЬ (loading → login oscillation seen in logs)
4. mss stale frame issue (pixel bridge IS rendering but mss misses it) — unlikely since we check every 1s

---

## Previous Session (2026-03-08)

### Fixed & Tested ✅
- Inventory false positive (free_slots=0): addon wasn't copied to ESO AddOns folder
- Header spam: `printed_hole_header` flag — only print once per hole
- F6 stop_flag in handle_disconnect — can stop mid-reconnect

### NOT YET TESTED in Real Bot Run ⚠️
- Header spam fix (code is in main_v5.py but bot hasn't run since fix)
- Inventory check accuracy (98/110 slots, was stopping incorrectly)

---

## Next Steps (Priority Order)

### 1. Test pixel bridge after reconnect (top priority)
- [ ] Force disconnect → run test_reconnect.py → see if 120s timeout is enough
- [ ] Check if addon reinitializes: add `d("[RECONNECT] OnPlayerActivated fired")` debug print to FishingNav.lua
- [ ] If still failing: try `/reloadui` after login (send `/reloadui` as chat command?)

### 2. Test main bot with header spam fix
- [ ] Run main_v5.py, verify no header spam in logs
- [ ] Run until inventory full, verify stop works

### 3. Force disconnect during bot run
- [ ] Verify disconnect detection (bridge_fail_start timeout = 15s)
- [ ] Verify full reconnect flow works end-to-end in main_v5.py
- [ ] Verify bot resumes fishing after reconnect

### 4. Cleanup
- [ ] Remove debug inventory output from FishingNav.lua
- [ ] Set up symlink: project AddOns → ESO AddOns folder

### 5. Forced relog between laps
- [ ] After all 17 holes done, force disconnect/relog to refresh hole spawns
- [ ] Use the reconnect flow to log back in

---

## Key Technical Notes

### Reconnect Architecture
```
ESO disconnect → pixel bridge unavailable (addons offline)
→ detect_screen_state() via ImageGrab pixel sampling (works without addons)
→ handle_disconnect():
   1. error_popup → Alt
   2. login → ВОЙТИ (mouse_click_win32)
   3. loading → wait for char_select
   4. char_select → ИГРАТЬ (mouse_click_win32)
   5. loading → wait for pixel bridge (addons reinitialize)
→ pixel bridge available → bot resumes
```

### Key File Locations
- `fishing/main_v5.py` — main bot + disconnect recovery
- `fishing/test_reconnect.py` — isolated reconnect test
- `AddOns/FishingNav/FishingNav.lua` — pixel bridge addon (has debug output, remove later)
- Must be copied to: `d:/Documents/Elder Scrolls Online/live/AddOns/FishingNav/`
