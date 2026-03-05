"""
ESO YOLO Fishing Bot — Phase 4: Visual AI Navigation

Uses a trained YOLOv8s model to:
1. Open map → find nearest blue_hook (river fishing hole)
2. Set waypoint → close map
3. Navigate via compass (compass_marker steering)
4. Detect arrival (bubbles / OCR text)
5. Fish using existing script (cast → hook → reel → loot)

Controls:
  F5 — Start / Pause
  F6 — Stop

Usage:
  python "fishing/yolo_fisher.py"
  python "fishing/yolo_fisher.py" --confidence 0.4 --zoom 5
"""

import argparse
import ctypes
import ctypes.wintypes
import math
import os
import random
import sys
import threading
import time

import cv2
import keyboard
import mss
import numpy as np
import pyautogui
import pydirectinput
import requests
from dotenv import load_dotenv
from PIL import ImageGrab
from ultralytics import YOLO

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

# Add fishing/ to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from navigation import _send_mouse_move, MOUSE_SENSITIVITY

# ── Compass Steering ─────────────────────────────────────────────────
STEER_INTERVAL = 0.15         # Seconds between compass checks (faster response)
STEER_DAMPING = 0.5           # Fraction of offset to correct per step (0-1)
STEER_MAX_PX = 150            # Max mouse correction pixels per step
STEER_DEAD_ZONE = 0.015       # Dead zone as fraction of screen width

# ── Navigation ───────────────────────────────────────────────────────
MAX_TRAVEL_TIME = 120.0       # Max seconds per waypoint travel
MARKER_LOST_TIMEOUT = 10.0    # Seconds without seeing marker before fallback
ARRIVAL_CHECK_INTERVAL = 2.0  # Seconds between arrival checks

# ── Map Interaction ──────────────────────────────────────────────────
MAP_OPEN_DELAY = (0.8, 1.2)   # Wait after pressing M for map to render
MAP_ZOOM_SCROLLS = 3          # Scroll clicks to zoom in on map
MAP_ZOOM_DELAY = (0.15, 0.25) # Delay between scroll clicks
MAP_SETTLE_DELAY = (0.3, 0.5) # Delay after zoom before detection
WAYPOINT_KEY = 'f'            # Key to set waypoint on map

# ── YOLO Thresholds ──────────────────────────────────────────────────
HOOK_MIN_CONF = 0.3           # Min confidence for blue_hook on map
BUBBLE_MIN_CONF = 0.5         # Min confidence for bubbles (arrival check)
WAYPOINT_MIN_CONF = 0.3       # Min confidence for compass_marker

# ── Fishing (copied from fishing_bot.py to avoid global state issues) ──
HOOK_WHITE_THRESHOLD = 220
HOOK_WHITE_RATIO = 0.08
LOOT_DARK_THRESHOLD = 40
LOOT_DARK_RATIO = 0.50
CAST_KEY = 'e'
LOOT_KEY = 'r'
SCAN_INTERVAL = 0.05
DELAY_AFTER_CAST = (1.0, 2.0)
DELAY_REEL_REACTION = (0.05, 0.2)
DELAY_AFTER_REEL = (1.5, 3.0)
DELAY_AFTER_LOOT = (0.5, 1.5)
DELAY_RECAST = (0.3, 0.8)
MAX_WAIT_FOR_HOOK = 45.0
MAX_WAIT_FOR_LOOT = 10.0
MAX_FAILED_CASTS = 2

# ── HP Bar (combat detection) ────────────────────────────────────────
HP_CHECK_INTERVAL = 1.0       # Seconds between HP checks during navigation

# ── Telegram ─────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── State ────────────────────────────────────────────────────────────
running = False
paused = False
fish_count = 0
cast_count = 0
failed_casts = 0


# ═══════════════════════════════════════════════════════════════════════
# Utility functions (copied from fishing_bot.py to keep self-contained)
# ═══════════════════════════════════════════════════════════════════════

def send_telegram(message):
    """Send a notification to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"[TG] Failed: {e}")


def human_delay(delay_range):
    """Sleep for a random duration within range."""
    time.sleep(random.uniform(*delay_range))


def press_key(key):
    """Press a key via DirectInput with human-like hold time."""
    hold_time = random.uniform(0.04, 0.12)
    pydirectinput.keyDown(key)
    time.sleep(hold_time)
    pydirectinput.keyUp(key)


# ── Screen regions for fishing detection ─────────────────────────────
SCAN_REGION_HOOK = None
SCAN_REGION_LOOT = None
HP_BAR_REGION = None


def init_screen_regions():
    """Calculate scan regions based on screen resolution."""
    global SCAN_REGION_HOOK, SCAN_REGION_LOOT, HP_BAR_REGION

    screen_w, screen_h = pyautogui.size()

    # Hook icon: center 25% of screen
    center_x, center_y = screen_w // 2, screen_h // 2
    hook_size = min(screen_w, screen_h) // 4
    SCAN_REGION_HOOK = (
        center_x - hook_size // 2,
        center_y - hook_size // 2,
        hook_size,
        hook_size,
    )

    # Loot window: right-center area
    SCAN_REGION_LOOT = (
        int(screen_w * 0.55),
        int(screen_h * 0.30),
        int(screen_w * 0.30),
        int(screen_h * 0.40),
    )

    # HP bar: bottom-center of screen (ESO shows HP/magicka/stamina bars there)
    # HP bar is roughly at bottom 8%, center 30% of screen
    HP_BAR_REGION = (
        int(screen_w * 0.35),
        int(screen_h * 0.90),
        int(screen_w * 0.30),
        int(screen_h * 0.04),
    )

    print(f"[INFO] Screen: {screen_w}x{screen_h}")


def capture_region(region):
    """Capture a screen region and return as numpy array."""
    x, y, w, h = region
    bbox = (x, y, x + w, y + h)
    img = ImageGrab.grab(bbox)
    return np.array(img)


def detect_hook():
    """Detect white hook icon in center of screen."""
    frame = capture_region(SCAN_REGION_HOOK)
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    white_pixels = np.sum(gray > HOOK_WHITE_THRESHOLD)
    return (white_pixels / gray.size) > HOOK_WHITE_RATIO


def detect_loot_window():
    """Detect dark loot panel in bottom-right of screen."""
    frame = capture_region(SCAN_REGION_LOOT)
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    dark_pixels = np.sum(gray < LOOT_DARK_THRESHOLD)
    return (dark_pixels / gray.size) > LOOT_DARK_RATIO


def check_hp_decreasing():
    """Check if player HP bar is visible and decreasing (under attack).

    In ESO, HP/magicka/stamina bars appear at the bottom of screen during combat.
    The HP bar (top bar) is green/red. If it's visible and not full, player is in combat.

    Returns True if HP bar is visible and appears damaged.
    """
    if HP_BAR_REGION is None:
        return False

    frame = capture_region(HP_BAR_REGION)
    # HP bar in ESO is typically green-ish when healthy, red when low
    # When out of combat, the bars are hidden (dark/transparent)
    # When in combat, bars appear — check for non-dark pixels
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

    # Check if bars are visible (bright enough to be shown)
    bright_pixels = np.sum(gray > 60)
    bar_visible = (bright_pixels / gray.size) > 0.15

    if not bar_visible:
        return False  # Bars not visible = not in combat

    # Bars visible = in combat. Check if HP is not full.
    # HP bar is the top bar, colored. Look for red pixels (low HP)
    # or check if there's a gap (dark area) in the bar region
    hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
    # Red hue range in HSV (HP bar turns red when damaged)
    red_mask = ((hsv[:, :, 0] < 15) | (hsv[:, :, 0] > 165)) & (hsv[:, :, 1] > 50)
    red_ratio = np.sum(red_mask) / red_mask.size

    # If significant red OR bars are visible (combat), consider under attack
    # We mainly care about combat state — if bars are showing, we're being attacked
    return bar_visible


def wait_for_hook():
    """Wait for white hook icon to appear. Returns True if detected."""
    start = time.time()
    while running and not paused:
        if time.time() - start > MAX_WAIT_FOR_HOOK:
            return False
        if detect_hook():
            return True
        time.sleep(SCAN_INTERVAL)
    return False


def fish_one_hole():
    """Fish at the current hole until depleted.

    Returns True if hole was depleted, False if stopped externally.
    """
    global fish_count, cast_count, failed_casts

    hole_fish = 0

    while running and not paused:
        cast_count += 1
        print(f"  [{cast_count}] Casting...")
        press_key(CAST_KEY)
        human_delay(DELAY_AFTER_CAST)

        print(f"  [{cast_count}] Waiting for bite...")
        if not wait_for_hook():
            if not running:
                return False

            failed_casts += 1
            print(f"  [{cast_count}] No bite (failed: {failed_casts}/{MAX_FAILED_CASTS})")

            if failed_casts >= MAX_FAILED_CASTS:
                print(f"  [BOT] HOLE DEPLETED! Fish from this hole: {hole_fish}")
                failed_casts = 0
                return True
            else:
                human_delay(DELAY_RECAST)
            continue

        failed_casts = 0

        human_delay(DELAY_REEL_REACTION)
        print(f"  [{cast_count}] HOOK! Reeling in...")
        press_key(CAST_KEY)

        human_delay(DELAY_AFTER_REEL)

        fish_count += 1
        hole_fish += 1
        print(f"  [{cast_count}] Fish #{fish_count}! Looting...")
        press_key(LOOT_KEY)
        time.sleep(0.3)
        press_key(LOOT_KEY)
        human_delay(DELAY_AFTER_LOOT)

    return False


# ═══════════════════════════════════════════════════════════════════════
# Water type detection (from dynamic_navigator.py)
# ═══════════════════════════════════════════════════════════════════════

WATER_TYPES = {
    "реке": "river",
    "реки": "river",
    "озере": "lake",
    "озера": "lake",
    "море": "sea",
    "моря": "sea",
    "болот": "swamp",
}
TARGET_WATER_TYPE = "river"
OCR_REGION = None


def get_ocr_region():
    """Calculate OCR scan region for fishing text detection."""
    global OCR_REGION
    screen_w, screen_h = pyautogui.size()
    region_w = int(screen_w * 0.4)
    region_h = int(screen_h * 0.08)
    x = (screen_w - region_w) // 2
    y = int(screen_h * 0.38)
    OCR_REGION = (x, y, region_w, region_h)
    return OCR_REGION


def detect_water_type():
    """Detect fishing hole water type via OCR on screen center.

    Returns "river", "lake", "sea", "swamp", or None (no hole).
    """
    if OCR_REGION is None:
        get_ocr_region()

    x, y, w, h = OCR_REGION
    bbox = (x, y, x + w, y + h)

    try:
        img = ImageGrab.grab(bbox)
        frame = np.array(img)
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

        try:
            import pytesseract
            text = pytesseract.image_to_string(
                thresh, lang="rus", config="--psm 7"
            ).lower().strip()
        except ImportError:
            white_ratio = np.sum(thresh > 0) / thresh.size
            if white_ratio < 0.02:
                return None
            print("[OCR] Tesseract not available, assuming river")
            return "river"

        if not text or "рыбалк" not in text:
            return None

        for keyword, water_type in WATER_TYPES.items():
            if keyword in text:
                return water_type

        print(f"[OCR] Unrecognized water text: {text}")
        return None

    except Exception as e:
        print(f"[OCR] Error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════
# YOLODetector — model wrapper + screen capture
# ═══════════════════════════════════════════════════════════════════════

class YOLODetector:
    """Wraps YOLO model with mss screen capture for ESO detection."""

    def __init__(self, model_path, confidence=0.3, imgsz=640):
        print(f"[YOLO] Loading model: {model_path}")
        self.model = YOLO(model_path)
        self.confidence = confidence
        self.imgsz = imgsz
        self.sct = mss.mss()
        self.monitor = self.sct.monitors[1]  # primary monitor
        self.screen_w = self.monitor["width"]
        self.screen_h = self.monitor["height"]

        # Warm up
        dummy = np.zeros((imgsz, imgsz, 3), dtype=np.uint8)
        self.model(dummy, verbose=False)
        print(f"[YOLO] Model loaded on {self.model.device}")
        if hasattr(self.model, "names"):
            print(f"[YOLO] Classes: {self.model.names}")

    def capture_screen(self):
        """Capture full screen, return BGR numpy array."""
        screenshot = self.sct.grab(self.monitor)
        frame = np.array(screenshot)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def detect(self, frame):
        """Run YOLO on frame, return list of detection dicts."""
        results = self.model(
            frame, imgsz=self.imgsz, conf=self.confidence, verbose=False
        )
        detections = []
        if results[0].boxes is not None:
            for box in results[0].boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                cls_id = int(box.cls[0])
                detections.append({
                    "class": self.model.names[cls_id],
                    "conf": float(box.conf[0]),
                    "x1": float(x1), "y1": float(y1),
                    "x2": float(x2), "y2": float(y2),
                    "cx": float((x1 + x2) / 2),
                    "cy": float((y1 + y2) / 2),
                })
        return detections

    def detect_on_screen(self):
        """Capture screen + run YOLO, return detections."""
        frame = self.capture_screen()
        return self.detect(frame)

    @staticmethod
    def find_class(detections, class_name):
        """Filter detections by class name."""
        return [d for d in detections if d["class"] == class_name]


# ═══════════════════════════════════════════════════════════════════════
# YOLOFisher — main bot logic
# ═══════════════════════════════════════════════════════════════════════

class YOLOFisher:
    """YOLO-powered fishing bot: map → waypoint → compass → fish."""

    def __init__(self, detector: YOLODetector):
        self.detector = detector
        self.screen_w = detector.screen_w
        self.screen_h = detector.screen_h
        self.screen_cx = self.screen_w // 2
        self.screen_cy = self.screen_h // 2

        # Stats
        self.holes_visited = 0
        self.holes_fished = 0
        self.holes_skipped = 0

        # Configurable
        self.map_zoom_scrolls = MAP_ZOOM_SCROLLS

        # HP tracking for combat detection
        self._last_hp_check = 0
        self._hp_samples = []  # recent HP bar brightness values

    def _check_running(self):
        return running and not paused

    def _wait_paused(self):
        while paused and running:
            time.sleep(0.3)

    def _nearest_to_center(self, detections):
        """Find detection closest to screen center (= nearest to player on map)."""
        if not detections:
            return None
        return min(detections, key=lambda d:
            (d["cx"] - self.screen_cx) ** 2 + (d["cy"] - self.screen_cy) ** 2)

    # ── Pre-check: already at a fishing hole? ────────────────────────

    def check_already_at_hole(self):
        """Check if we're already standing at a fishing hole.

        Checks for bubbles (YOLO) and fishing text (OCR) before opening map.
        Returns water_type string if at a hole, None otherwise.
        """
        print("[PRE] Checking if already at fishing hole...")

        # Check YOLO for bubbles (use lower threshold for pre-check)
        detections = self.detector.detect_on_screen()
        bubbles = self.detector.find_class(detections, "bubbles")

        # Log all detections for debugging
        det_summary = {}
        for d in detections:
            cls = d["class"]
            if cls not in det_summary:
                det_summary[cls] = []
            det_summary[cls].append(f"{d['conf']:.2f}")
        print(f"[PRE] YOLO sees: {det_summary}")

        has_bubbles = any(b["conf"] >= 0.3 for b in bubbles)  # lower threshold
        if bubbles:
            bubble_confs = [f"{b['conf']:.2f}" for b in bubbles]
            print(f"[PRE] Bubbles: {bubble_confs}")

        # Check OCR for fishing text
        water_type = detect_water_type()
        print(f"[PRE] OCR water_type: {water_type}")

        if water_type:
            print(f"[PRE] -> At fishing hole! type={water_type}")
            return water_type
        elif has_bubbles:
            print("[PRE] -> Bubbles visible! (no OCR text)")
            return "unknown"

        print("[PRE] -> No fishing hole detected")
        return None

    # ── Phase 1: Open map and find blue_hook ──────────────────────────

    def open_map_and_find_hook(self):
        """Open map, zoom in, detect blue_hooks, pick nearest to center.

        Returns detection dict of chosen hook, or None.
        """
        # Open map
        press_key('m')
        human_delay(MAP_OPEN_DELAY)

        # Zoom in for better YOLO accuracy
        for _ in range(self.map_zoom_scrolls):
            pyautogui.scroll(3)  # scroll up = zoom in
            human_delay(MAP_ZOOM_DELAY)
        human_delay(MAP_SETTLE_DELAY)

        # Detect
        detections = self.detector.detect_on_screen()
        hooks = self.detector.find_class(detections, "blue_hook")
        hooks = [h for h in hooks if h["conf"] >= HOOK_MIN_CONF]

        if not hooks:
            print("[MAP] No blue_hooks found on map")
            press_key('m')  # close map
            time.sleep(0.5)
            return None

        print(f"[MAP] Found {len(hooks)} blue_hook(s)")

        # Pick nearest to screen center
        best = self._nearest_to_center(hooks)
        dist_from_center = math.sqrt(
            (best["cx"] - self.screen_cx) ** 2 +
            (best["cy"] - self.screen_cy) ** 2
        )
        print(f"[MAP] Target: ({best['cx']:.0f}, {best['cy']:.0f}), "
              f"conf={best['conf']:.2f}, dist_from_center={dist_from_center:.0f}px")
        return best

    # ── Phase 2: Set waypoint and close map ───────────────────────────

    def set_waypoint_and_close_map(self, hook_detection):
        """Move cursor to hook on map, press F to set waypoint, close map."""
        target_x = int(hook_detection["cx"])
        target_y = int(hook_detection["cy"])

        # Move mouse to hook position on map
        # pyautogui.moveTo works for ESO map UI (normal cursor, not raw input)
        pyautogui.moveTo(target_x, target_y, duration=random.uniform(0.3, 0.6))
        human_delay((0.1, 0.2))

        # Press F to set waypoint
        press_key(WAYPOINT_KEY)
        human_delay((0.3, 0.5))

        # Close map
        press_key('m')
        human_delay((0.5, 0.8))

        print(f"[MAP] Waypoint set at ({target_x}, {target_y}), map closed")

    # ── Phase 3: Navigate to waypoint via compass ─────────────────────

    def navigate_to_waypoint(self):
        """Steer toward waypoint using compass marker detection.

        Returns reason string: "arrived", "timeout", "combat", "lost_marker", "stopped"
        """
        start_time = time.time()
        last_arrival_check = 0
        last_marker_seen = time.time()
        last_hp_check = 0
        last_log_time = 0
        steer_count = 0
        no_marker_count = 0

        # Start sprinting
        pydirectinput.keyDown('shift')
        time.sleep(0.05)
        pydirectinput.keyDown('w')

        print("[NAV] Sprinting started (W + Shift)")

        try:
            while self._check_running():
                now = time.time()
                elapsed = now - start_time

                if elapsed > MAX_TRAVEL_TIME:
                    print("[NAV] Travel timeout!")
                    return "timeout"

                # Capture screen and detect
                detections = self.detector.detect_on_screen()

                # Log all detections periodically for debugging
                if now - last_log_time > 3.0:
                    last_log_time = now
                    det_summary = {}
                    for d in detections:
                        cls = d["class"]
                        det_summary[cls] = det_summary.get(cls, 0) + 1
                    print(f"[NAV] {elapsed:.0f}s | Detections: {det_summary} | "
                          f"steers: {steer_count}, no_marker: {no_marker_count}")

                # Find compass_marker on compass
                markers = self.detector.find_class(detections, "compass_marker")
                markers = [m for m in markers if m["conf"] >= WAYPOINT_MIN_CONF]

                if markers:
                    last_marker_seen = now
                    marker = max(markers, key=lambda m: m["conf"])
                    marker_x = marker["cx"]

                    # Steer: offset from screen center
                    offset = marker_x - self.screen_cx
                    dead_zone_px = self.screen_w * STEER_DEAD_ZONE

                    if abs(offset) > dead_zone_px:
                        # More aggressive steering: use 0.5 damping and higher max
                        correction = int(offset * STEER_DAMPING)
                        correction = max(-STEER_MAX_PX, min(STEER_MAX_PX, correction))

                        # Send mouse move in small steps for reliability
                        step = 30
                        remaining = abs(correction)
                        direction = 1 if correction > 0 else -1
                        while remaining > 0:
                            move = min(step, remaining)
                            _send_mouse_move(direction * move, 0)
                            remaining -= move
                            time.sleep(0.005)

                        steer_count += 1

                        # Log significant corrections
                        if abs(offset) > self.screen_w * 0.1:
                            print(f"[NAV] STEER: marker at x={marker_x:.0f}, "
                                  f"offset={offset:.0f}px, correction={correction}px, "
                                  f"conf={marker['conf']:.2f}")
                else:
                    no_marker_count += 1
                    if now - last_marker_seen > MARKER_LOST_TIMEOUT:
                        print(f"[NAV] Waypoint marker lost! "
                              f"(not seen for {MARKER_LOST_TIMEOUT:.0f}s)")
                        return "lost_marker"

                # Periodically check for arrival
                if now - last_arrival_check > ARRIVAL_CHECK_INTERVAL:
                    last_arrival_check = now

                    # Check bubbles (YOLO)
                    bubbles = self.detector.find_class(detections, "bubbles")
                    high_conf_bubbles = [b for b in bubbles if b["conf"] >= BUBBLE_MIN_CONF]
                    if high_conf_bubbles:
                        best = max(high_conf_bubbles, key=lambda b: b["conf"])
                        print(f"[NAV] Bubbles detected! conf={best['conf']:.2f}")
                        return "arrived"

                    # Check fishing hole text (OCR)
                    water_type = detect_water_type()
                    if water_type is not None:
                        print(f"[NAV] Fishing hole text: {water_type}")
                        return "arrived"

                # Check HP bar for combat
                if now - last_hp_check > HP_CHECK_INTERVAL:
                    last_hp_check = now
                    if check_hp_decreasing():
                        print("[NAV] Under attack! (HP bar visible)")
                        return "combat"

                time.sleep(STEER_INTERVAL)

        finally:
            pydirectinput.keyUp('w')
            pydirectinput.keyUp('shift')
            time.sleep(0.1)
            print(f"[NAV] Stopped. Total steers: {steer_count}, "
                  f"no_marker frames: {no_marker_count}")

        return "stopped"

    # ── Combat handling ───────────────────────────────────────────────

    def handle_combat(self):
        """React to being attacked: turn around and sprint away."""
        print("[BOT] Under attack! Sprinting away...")
        send_telegram("⚔️ Враг атакует — убегаю!")

        # Turn ~180 degrees
        turn_pixels = int(math.pi * MOUSE_SENSITIVITY)
        step_size = 50
        for _ in range(turn_pixels // step_size):
            _send_mouse_move(step_size, 0)
            time.sleep(0.01)

        time.sleep(0.2)

        # Sprint away
        pydirectinput.keyDown('shift')
        pydirectinput.keyDown('w')
        time.sleep(5.0 + random.uniform(-0.5, 0.5))
        pydirectinput.keyUp('w')
        pydirectinput.keyUp('shift')

        # Wait for combat to end
        time.sleep(random.uniform(3.0, 5.0))

        # Verify combat ended
        if check_hp_decreasing():
            print("[BOT] Still in combat, waiting longer...")
            time.sleep(random.uniform(5.0, 10.0))

    # ── Main loop ─────────────────────────────────────────────────────

    def run(self):
        """Main bot loop: map → waypoint → navigate → fish → repeat."""
        global fish_count, cast_count

        print("\n[BOT] YOLO Fisher starting...")
        send_telegram("🎣 YOLO Fisher запущен!")

        while self._check_running():
            self._wait_paused()
            if not running:
                break

            # === Pre-check: already at a fishing hole? ===
            print(f"\n[BOT] === Looking for fishing hole "
                  f"(visited: {self.holes_visited}, "
                  f"fished: {self.holes_fished}) ===")

            already_here = self.check_already_at_hole()
            if already_here and already_here == TARGET_WATER_TYPE:
                print(f"[BOT] Already at river hole! Fishing immediately.")
                self.holes_visited += 1
                self.holes_fished += 1
                depleted = fish_one_hole()
                if depleted:
                    msg = (
                        f"🐟 Лунка #{self.holes_fished} исчерпана\n"
                        f"Рыб: {fish_count}, Забросов: {cast_count}"
                    )
                    print(f"[BOT] {msg}")
                    send_telegram(msg)
                human_delay((1.0, 3.0))
                continue
            elif already_here and already_here != TARGET_WATER_TYPE and already_here != "unknown":
                print(f"[BOT] At {already_here} hole — SKIP (want {TARGET_WATER_TYPE})")
                # Still need to navigate away
            elif already_here == "unknown":
                # Bubbles visible but no OCR text — try fishing
                print("[BOT] Bubbles visible, trying to fish...")
                self.holes_visited += 1
                self.holes_fished += 1
                depleted = fish_one_hole()
                if depleted:
                    msg = (
                        f"🐟 Лунка #{self.holes_fished} исчерпана\n"
                        f"Рыб: {fish_count}, Забросов: {cast_count}"
                    )
                    print(f"[BOT] {msg}")
                    send_telegram(msg)
                human_delay((1.0, 3.0))
                continue

            # === Step 1: Open map and find nearest blue_hook ===
            hook = self.open_map_and_find_hook()

            if hook is None:
                print("[BOT] No hooks found. Waiting before retry...")
                human_delay((3.0, 5.0))
                continue

            # === Step 2: Set waypoint and close map ===
            self.set_waypoint_and_close_map(hook)

            # === Step 3: Navigate to waypoint via compass ===
            print("[NAV] Running to waypoint...")
            result = self.navigate_to_waypoint()
            self.holes_visited += 1

            if result == "combat":
                self.handle_combat()
                continue

            if result in ("timeout", "lost_marker"):
                print(f"[BOT] Navigation failed: {result}. Trying next hole...")
                self.holes_skipped += 1
                human_delay((1.0, 2.0))
                continue

            if result == "stopped":
                break

            # === Step 4: Arrived — check water type ===
            if result == "arrived":
                human_delay((0.8, 1.5))  # settle before checking

                water_type = detect_water_type()
                print(f"[BOT] Water type: {water_type}")

                if water_type is None:
                    # No fishing text — maybe just bubbles, try anyway
                    # Double check with YOLO
                    detections = self.detector.detect_on_screen()
                    bubbles = self.detector.find_class(detections, "bubbles")
                    if not bubbles:
                        print("[BOT] No fishing hole confirmed. Skipping.")
                        self.holes_skipped += 1
                        human_delay((1.0, 2.0))
                        continue
                    # Bubbles visible but no text — might be river, try fishing
                    print("[BOT] Bubbles visible but no OCR text. Trying to fish...")

                elif water_type != TARGET_WATER_TYPE:
                    print(f"[BOT] {water_type} — SKIP (want {TARGET_WATER_TYPE})")
                    self.holes_skipped += 1
                    human_delay((1.0, 2.0))
                    continue

                # === Step 5: Fish! ===
                print(f"[BOT] FISHING! (type: {water_type or 'unknown'})")
                self.holes_fished += 1

                depleted = fish_one_hole()

                if depleted:
                    msg = (
                        f"🐟 Лунка #{self.holes_fished} исчерпана\n"
                        f"Рыб: {fish_count}, Забросов: {cast_count}"
                    )
                    print(f"[BOT] {msg}")
                    send_telegram(msg)

                human_delay((1.0, 3.0))

        # Done
        msg = (
            f"⏹ YOLO Fisher остановлен\n"
            f"Лунок: {self.holes_fished}/{self.holes_visited}\n"
            f"Пропущено: {self.holes_skipped}\n"
            f"Рыб: {fish_count}, Забросов: {cast_count}"
        )
        print(f"\n[BOT] {msg}")
        send_telegram(msg)


# ═══════════════════════════════════════════════════════════════════════
# Hotkeys and main
# ═══════════════════════════════════════════════════════════════════════

def hotkey_listener():
    """Listen for F5 (toggle pause) and F6 (stop) hotkeys."""
    global running, paused

    def on_f5():
        global paused
        paused = not paused
        state = "PAUSED" if paused else "RUNNING"
        print(f"\n[BOT] {state}")

    def on_f6():
        global running
        running = False
        print("\n[BOT] Stopping...")

    keyboard.on_press_key("f5", lambda _: on_f5(), suppress=False)
    keyboard.on_press_key("f6", lambda _: on_f6(), suppress=False)

    while running:
        time.sleep(0.1)

    keyboard.unhook_all()


def main():
    global running

    parser = argparse.ArgumentParser(description="ESO YOLO Fishing Bot")
    parser.add_argument("--confidence", type=float, default=0.3,
                        help="YOLO confidence threshold")
    parser.add_argument("--zoom", type=int, default=MAP_ZOOM_SCROLLS,
                        help="Map zoom scroll clicks")
    parser.add_argument("--test", action="store_true",
                        help="Test mode: open map, show detections, close")
    args = parser.parse_args()

    print("=" * 55)
    print("  ESO YOLO Fishing Bot — Phase 4")
    print("=" * 55)
    print("  F5 — Start / Pause")
    print("  F6 — Stop")
    print("=" * 55)

    # Init screen regions
    init_screen_regions()
    get_ocr_region()

    # Load YOLO model
    model_path = os.path.join(
        os.path.dirname(__file__), "training", "runs", "eso_fishing", "weights", "best.pt"
    )
    if not os.path.exists(model_path):
        print(f"\n[ERROR] Model not found: {model_path}")
        print("Run train.py first to train the model.")
        sys.exit(1)

    detector = YOLODetector(model_path, confidence=args.confidence)
    fisher = YOLOFisher(detector)
    fisher.map_zoom_scrolls = args.zoom

    # Test mode
    if args.test:
        print("\n[TEST] Opening map and detecting...")
        time.sleep(2)  # give time to switch to ESO
        press_key('m')
        human_delay(MAP_OPEN_DELAY)

        for _ in range(args.zoom):
            pyautogui.scroll(3)
            human_delay(MAP_ZOOM_DELAY)
        human_delay(MAP_SETTLE_DELAY)

        detections = detector.detect_on_screen()
        print(f"\n[TEST] Detections ({len(detections)}):")
        for d in sorted(detections, key=lambda x: -x["conf"]):
            print(f"  {d['class']:20s} conf={d['conf']:.2f} "
                  f"at ({d['cx']:.0f}, {d['cy']:.0f})")

        hooks = detector.find_class(detections, "blue_hook")
        print(f"\n[TEST] Blue hooks: {len(hooks)}")

        press_key('m')  # close map
        return

    # Wait for F5
    print("\n[BOT] Press F5 to start...")
    keyboard.wait("f5")

    running = True
    time.sleep(0.3)

    # Start hotkey listener
    hotkey_thread = threading.Thread(target=hotkey_listener, daemon=True)
    hotkey_thread.start()

    try:
        fisher.run()
    except KeyboardInterrupt:
        running = False
        print("\n[BOT] Interrupted by user")
    finally:
        keyboard.unhook_all()


if __name__ == "__main__":
    main()
