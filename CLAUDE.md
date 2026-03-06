# CLAUDE.md — Project Rules

## #1 DEVELOPMENT WORKFLOW (highest priority, ALWAYS follow)
RULE: Every feature follows this EXACT sequence. NEVER skip steps.
1. Implement the feature
2. Test that it works (run it, verify output)
3. Ask user to confirm/approve the result
4. ONLY after user approval: update relevant docs (`FISHING_BOT.md`, `CLAUDE.md`, `ESO_План_Запуска.md`)
5. Run `/push`

RULE: NEVER make large untested changes. One feature at a time.
RULE: NEVER run `/push` without completing steps 1-4 above.
RULE: After completing a milestone, check it off in `ESO_План_Запуска.md`.
RULE: When discovering a bug/gotcha, add it to KNOWN ISSUES below.

## LANGUAGE
- RULE: Speak Russian to the user. Plans, explanations, task descriptions — always in Russian.
- RULE: Code, code comments, git commits — in English.
- RULE: ESO game terms (skills, items, locations) — in Russian, official RU localization.

## FOCUS
- RULE: Stay focused on goals in `ESO_План_Запуска.md`. Do NOT suggest unrelated features or topics.

## CODE
- RULE: ALWAYS read a file before modifying it.
- RULE: Do NOT create new files unless absolutely necessary.
- RULE: ESO addon files (SavedVariables, PriceTable*.lua) — READ ONLY, never modify.

## YOLO / ML
- RULE: YOLO retraining — ALWAYS merge ALL previous CVAT exports with new ones, never use only the latest export.
- RULE: Before rebuilding dataset — verify all classes are present and counts have not decreased vs previous version.
- RULE: Store all CVAT `.zip` exports in `fishing/training/exports/` as backup.

## SECURITY (hard rules, NEVER override)
- NEVER put secrets (passwords, API keys, tokens) in code — use `.env`
- NEVER commit: `.env`, `*.pt`, `*.log`, `SavedVariables/`, `PriceTable*.lua`
- NEVER commit payment data, marketplace accounts, buyer names
- Bot actions MUST have random delays (human-like behavior)
- TTC requests: max 1 per 3-5 seconds, browser User-Agent

## GIT
- Commits: short, English, descriptive
- `.gitignore` must include: `.env`, `*.log`, `SavedVariables/`, `__pycache__/`, `*.pt`

## KNOWN ISSUES
- `pydirectinput.moveRel()` broken with ESO — use Win32 `SendInput` with `MOUSEEVENTF_MOVE`
- `pydirectinput.typewrite()` types in current layout — switch to EN via `PostMessageW(WM_INPUTLANGCHANGEREQUEST)`
- `GetAsyncKeyState` fails when ESO has focus — use `keyboard` library (low-level hooks)
- SavedVariables only save on `/reloadui` (5-8 sec delay) — Pixel Bridge replaces this
- SavedVariables polling does NOT work for real-time data transfer to external programs
- `RequestAddOnSavedVariablesPrioritySave` unreliable — ESO may skip saves if write takes too long
- ESO caches addon manifests — new .lua files need addon reinstall
- `GetMapPlayerPosition` heading = character direction, NOT camera — need step (W) after mouse turn
- `GetMapPlayerPosition('reticleover')` disabled since v1.2.3 — anti-bot measure, only "player" works
- Pre-planned routes don't work — player moves, map re-centers, saved coords stale -> fresh YOLO scan each iteration
- YOLO nav has architectural issues: pixel distance on map != real distance, OCR too slow for running, compass marker always ~35px
- `mss` can't run in keyboard hook thread — use queue to main thread
- Compass marker width always ~35px regardless of distance — can't use for distance estimation
- Model trained on `compass_marker`, NOT `waypoint_marker` — don't confuse class names
- `bubbles` class weak (mAP50=0.359) — don't rely on it, false positives while running
- ESO May 2025 ban wave targeted auto-fishing bots (FishyBot users) — use random delays, human-like behavior
- DXcam/BetterCam only works in windowed/borderless fullscreen (not exclusive fullscreen)
- BetterCam `grab()` returns None if frame unchanged — always check for None
- Combat loop: if mob too strong for AoE '5', `handle_combat` timeout loops forever — need flee or death detection
- ESO disconnect screens: error popup [Alt]OK → "ВОЙТИ" button (960,490) → "ИГРАТЬ" button (960,1050) on 1920x1080
