"""
Centralized configuration for the ESO Fishing Bot.
All calibrated values and tunable constants in one place.
"""

import os

# ── Paths ────────────────────────────────────────────────────────────
FISHING_DIR = os.path.dirname(__file__)
MODEL_PATH = os.path.join(FISHING_DIR, "training", "runs", "eso_fishing", "weights", "best.pt")

# ── Mouse / Camera Calibration ──────────────────────────────────────
PIXELS_PER_360 = 9300           # Mouse px for full 360 rotation (800 DPI, ESO look speed 15)
PIXELS_PER_DEGREE = PIXELS_PER_360 / 360  # ~25.83
SCREEN_TO_MOUSE = (PIXELS_PER_360 / 2) / 1920  # Converts screen px offset to mouse px (~2.42)

# ── Navigation (Phase 3 blind nav) ──────────────────────────────────
SPRINT_SPEED = 968.6            # World units/sec (calibrated 2026-03-02)
MOUSE_SENSITIVITY = 685.5       # Pixels/radian (calibrated 2026-03-02)
ARRIVAL_THRESHOLD = 15.0        # World units to consider "arrived"

# ── YOLO Detection ──────────────────────────────────────────────────
HOOK_MIN_CONF = 0.3             # Min confidence for blue_hook on map
MARKER_MIN_CONF = 0.3           # Min confidence for compass_marker
YOLO_CONF_THRESHOLD = 0.3      # General YOLO confidence threshold

# ── Map Navigation ──────────────────────────────────────────────────
MAP_ZOOM_CLICKS = 10            # Clicks on "+" button to max-zoom centered on player

# ── Visited Hook Tracking ───────────────────────────────────────────
VISITED_DEDUP_DIST = 40         # px — if hook is within this dist of a visited one, skip it

# ── ESO Data Paths ──────────────────────────────────────────────────
ESO_LIVE_DIR = r"d:\Documents\Elder Scrolls Online\live"
SAVED_VARIABLES_DIR = os.path.join(ESO_LIVE_DIR, "SavedVariables")
ADDONS_DIR = os.path.join(ESO_LIVE_DIR, "AddOns")
