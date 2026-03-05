"""
Dynamic Navigator for ESO Fishing Bot (Phase 3).

Visits all known fishing hole spawn points from HarvestMap data.
Uses "blind navigation": /reloadui → read position → rotate → sprint → verify.

Fishing holes spawn randomly from ~496 known positions per zone.
Bot navigates to each, checks if a hole is present via OCR, fishes if river type.

Usage:
    from dynamic_navigator import DynamicNavigator
    nav = DynamicNavigator("glenumbra")
    nav.run_circuit(check_running, fish_callback)
"""

import math
import random
import time

import cv2
import numpy as np
from PIL import ImageGrab
import pyautogui

from harvestmap_parser import get_fishing_holes
from navigation import (
    ARRIVAL_THRESHOLD,
    distance_2d,
    force_reloadui_and_read,
    move_blind_segment,
    read_player_position,
    sprint_escape,
    RELOADUI_WAIT,
)

# ─── Constants ────────────────────────────────────────────────────
MAX_CORRECTION_ATTEMPTS = 3    # Max /reloadui corrections before skipping hole
PROBE_CASTS = 2               # Casts to verify if hole is active (0 = skip probe)
SETTLE_DELAY = (1.0, 2.0)     # Delay after arriving before checking water type
BETWEEN_HOLES_DELAY = (0.5, 1.5)  # Delay between navigating to holes

# OCR detection region (center of screen where "Место для рыбалки" text appears)
# Will be calculated on init based on screen resolution
OCR_REGION = None

# Water type keywords in Russian ESO localization
WATER_TYPES = {
    "реке": "river",     # "на реке" — river (target)
    "реки": "river",     # alternative form
    "озере": "lake",     # "на озере" — lake
    "озера": "lake",
    "море": "sea",       # "на море" — sea
    "моря": "sea",
    "болот": "swamp",    # "на болоте" — swamp
}
TARGET_WATER_TYPE = "river"    # Only fish in rivers (bait: insect parts)


def get_ocr_region():
    """Calculate OCR scan region based on screen resolution."""
    global OCR_REGION
    screen_w, screen_h = pyautogui.size()
    # Fishing text appears slightly above center
    region_w = int(screen_w * 0.4)
    region_h = int(screen_h * 0.08)
    x = (screen_w - region_w) // 2
    y = int(screen_h * 0.38)
    OCR_REGION = (x, y, region_w, region_h)
    return OCR_REGION


def detect_water_type():
    """Detect fishing hole water type via OCR on screen center.

    Looks for "Место для рыбалки на <type>" text.

    Returns:
        "river", "lake", "sea", "swamp" — if fishing text detected
        None — if no fishing text found (no hole present)
    """
    if OCR_REGION is None:
        get_ocr_region()

    x, y, w, h = OCR_REGION
    bbox = (x, y, x + w, y + h)

    try:
        img = ImageGrab.grab(bbox)
        frame = np.array(img)

        # Convert to grayscale and threshold for white text
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        # ESO fishing text is white/light colored on dark background
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

        # Try Tesseract OCR if available
        try:
            import pytesseract
            text = pytesseract.image_to_string(
                thresh, lang="rus", config="--psm 7"
            ).lower().strip()
        except ImportError:
            # Fallback: no Tesseract — try template matching approach
            # For now, just check if there's enough white text in the region
            white_ratio = np.sum(thresh > 0) / thresh.size
            if white_ratio < 0.02:
                return None
            # Can't determine type without OCR — assume river for now
            print("[OCR] Tesseract not available, assuming river water type")
            return "river"

        if not text or "рыбалк" not in text:
            return None

        for keyword, water_type in WATER_TYPES.items():
            if keyword in text:
                return water_type

        # Text found but type not recognized
        print(f"[OCR] Unrecognized water text: {text}")
        return None

    except Exception as e:
        print(f"[OCR] Error: {e}")
        return None


class DynamicNavigator:
    """Navigates dynamically between all known fishing holes in a zone.

    Uses HarvestMap data for spawn point locations.
    Visits each location, checks for active fishing hole, fishes if appropriate.
    """

    def __init__(self, zone_name="glenumbra"):
        self.zone_name = zone_name
        self.spawn_points = []  # All known fishing hole positions
        self.visited = set()    # Indices of visited holes this circuit
        self.fished = set()     # Indices of holes we actually fished
        self.empty = set()      # Indices where no hole was present
        self.skipped = set()    # Indices skipped (wrong water type)
        self.circuit_count = 0
        self.total_holes_fished = 0

        # Load spawn points
        self._load_spawn_points()

        # Init OCR region
        get_ocr_region()

    def _load_spawn_points(self):
        """Load all fishing hole spawn points from HarvestMap data."""
        holes = get_fishing_holes(self.zone_name)
        if not holes:
            print(f"[DYN] No fishing holes found for {self.zone_name}!")
            return

        self.spawn_points = holes
        print(f"[DYN] Loaded {len(self.spawn_points)} spawn points for {self.zone_name}")

    def find_nearest_unvisited(self, current_x, current_y):
        """Find the nearest unvisited spawn point.

        Args:
            current_x, current_y: Current player world coordinates

        Returns:
            (index, distance) tuple, or (None, None) if all visited
        """
        best_idx = None
        best_dist = float("inf")

        for i, hole in enumerate(self.spawn_points):
            if i in self.visited:
                continue
            dist = distance_2d(current_x, current_y, hole["x"], hole["y"])
            if dist < best_dist:
                best_dist = dist
                best_idx = i

        return best_idx, best_dist if best_idx is not None else (None, None)

    def navigate_to_hole(self, hole_idx, check_running):
        """Navigate to a specific hole using blind navigation.

        Loop: /reloadui → rotate → sprint → /reloadui → check distance

        Args:
            hole_idx: Index into self.spawn_points
            check_running: Callable returning False to abort

        Returns:
            True if arrived within ARRIVAL_THRESHOLD, False otherwise
        """
        target = self.spawn_points[hole_idx]
        target_x, target_y = target["x"], target["y"]

        for attempt in range(MAX_CORRECTION_ATTEMPTS + 1):
            if not check_running():
                return False

            # Get current position via /reloadui
            if attempt == 0:
                # First attempt — we may already have a recent position
                pos = read_player_position()
                if not pos:
                    print("[DYN] No cached position, doing /reloadui...")
                    pos = force_reloadui_and_read()
            else:
                print(f"[DYN] Correction attempt {attempt}/{MAX_CORRECTION_ATTEMPTS}")
                pos = force_reloadui_and_read()
                # Wait for UI to reload after /reloadui
                time.sleep(RELOADUI_WAIT)

            if not pos:
                print("[DYN] Failed to read position!")
                return False

            # Check distance
            dist = distance_2d(pos["worldX"], pos["worldY"], target_x, target_y)
            print(f"[DYN] Distance to hole #{hole_idx}: {dist:.0f} units")

            if dist < ARRIVAL_THRESHOLD:
                print(f"[DYN] Arrived at hole #{hole_idx}!")
                return True

            if not check_running():
                return False

            # Move blind toward target
            print(f"[DYN] Moving blind toward hole #{hole_idx} "
                  f"(x={target_x:.0f}, y={target_y:.0f})")
            move_blind_segment(target_x, target_y, pos, sprint=True)

        # Out of correction attempts
        # Do one final position check
        pos = force_reloadui_and_read()
        time.sleep(RELOADUI_WAIT)
        if pos:
            dist = distance_2d(pos["worldX"], pos["worldY"], target_x, target_y)
            if dist < ARRIVAL_THRESHOLD:
                return True
            print(f"[DYN] Failed to reach hole #{hole_idx} (dist={dist:.0f})")
        return False

    def run_circuit(self, check_running, fish_callback, on_hole_done=None):
        """Run one full circuit of all spawn points.

        Args:
            check_running: Callable returning False to stop
            fish_callback: Callable() that fishes one hole (like fish_one_hole)
                          Returns True if hole was depleted, False if stopped
            on_hole_done: Optional callback(hole_idx, result) after each hole

        Returns:
            Dict with circuit stats
        """
        self.circuit_count += 1
        self.visited.clear()
        self.fished.clear()
        self.empty.clear()
        self.skipped.clear()

        print(f"\n[DYN] === Circuit #{self.circuit_count} ===")
        print(f"[DYN] {len(self.spawn_points)} spawn points to check")

        # Get initial position
        pos = force_reloadui_and_read()
        time.sleep(RELOADUI_WAIT)
        if not pos:
            print("[DYN] Cannot read initial position!")
            return self._circuit_stats()

        holes_checked = 0

        while check_running():
            current_x = pos["worldX"]
            current_y = pos["worldY"]

            # Find nearest unvisited
            hole_idx, dist = self.find_nearest_unvisited(current_x, current_y)
            if hole_idx is None:
                print("[DYN] All spawn points visited this circuit!")
                break

            holes_checked += 1
            hole = self.spawn_points[hole_idx]
            print(f"\n[DYN] [{holes_checked}/{len(self.spawn_points)}] "
                  f"Heading to hole #{hole_idx} "
                  f"(x={hole['x']:.0f}, y={hole['y']:.0f}, dist={dist:.0f})")

            # Navigate to hole
            arrived = self.navigate_to_hole(hole_idx, check_running)
            self.visited.add(hole_idx)

            if not arrived:
                if not check_running():
                    break
                print(f"[DYN] Skipping hole #{hole_idx} — navigation failed")
                self.empty.add(hole_idx)
                # Read position for next iteration
                pos = force_reloadui_and_read()
                time.sleep(RELOADUI_WAIT)
                if not pos:
                    break
                continue

            # Settle and check water type
            time.sleep(random.uniform(*SETTLE_DELAY))

            water_type = detect_water_type()
            if water_type is None:
                print(f"[DYN] Hole #{hole_idx}: no fishing hole present (empty)")
                self.empty.add(hole_idx)
            elif water_type != TARGET_WATER_TYPE:
                print(f"[DYN] Hole #{hole_idx}: {water_type} — skipping (want {TARGET_WATER_TYPE})")
                self.skipped.add(hole_idx)
            else:
                print(f"[DYN] Hole #{hole_idx}: {water_type} — FISHING!")
                self.fished.add(hole_idx)
                self.total_holes_fished += 1

                # Fish!
                depleted = fish_callback()
                if not check_running():
                    break

                result = "depleted" if depleted else "stopped"
                if on_hole_done:
                    on_hole_done(hole_idx, result)

            # Small delay between holes
            time.sleep(random.uniform(*BETWEEN_HOLES_DELAY))

            # Read position for next hole
            pos = force_reloadui_and_read()
            time.sleep(RELOADUI_WAIT)
            if not pos:
                print("[DYN] Lost position, trying one more time...")
                time.sleep(2)
                pos = force_reloadui_and_read()
                time.sleep(RELOADUI_WAIT)
                if not pos:
                    print("[DYN] Cannot read position, aborting circuit")
                    break

        stats = self._circuit_stats()
        print(f"\n[DYN] Circuit #{self.circuit_count} complete:")
        print(f"  Visited: {stats['visited']}/{stats['total']}")
        print(f"  Fished: {stats['fished']}")
        print(f"  Empty: {stats['empty']}")
        print(f"  Skipped (wrong type): {stats['skipped']}")
        return stats

    def _circuit_stats(self):
        """Return stats dict for the current circuit."""
        return {
            "circuit": self.circuit_count,
            "total": len(self.spawn_points),
            "visited": len(self.visited),
            "fished": len(self.fished),
            "empty": len(self.empty),
            "skipped": len(self.skipped),
        }
