"""
Screenshot Collector v2 — collect training data for YOLO model.

Run this while playing ESO. Press hotkeys to save screenshots
into categorized folders for later annotation in CVAT.

Controls:
  F1 — save "map" screenshot (map with blue fishing hooks)
  F2 — save "gameplay" screenshot (fishing holes, bubbles, enemies)
  F3 — save "compass" screenshot (compass bar with waypoint marker)
  F4 — save "combat" screenshot (HP bar visible, in combat)
  F5 — save "interaction" screenshot (fishing prompt "[E] Ловить рыбу")
  F6 — save "xp" screenshot (XP popup after mob kill)
  F7 — save "navigation" screenshot (destination text, running to waypoint)
  F8 — save "general" screenshot (anything else useful)
  F10 — stop

Screenshots are saved to: fishing/AI fishing gibrid/dataset/images/{category}/
"""

import os
import time
import queue
import mss
import keyboard
from PIL import Image
from datetime import datetime


# ── Settings ─────────────────────────────────────────────────────────
MONITOR_INDEX = 1
BASE_DIR = os.path.join(os.path.dirname(__file__), "dataset", "images")
CATEGORIES = [
    "map",          # F1: Map open with blue_hook icons
    "gameplay",     # F2: World view (bubbles, enemies, fishing holes)
    "compass",      # F3: Compass with waypoint marker (left/center/right)
    "combat",       # F4: In combat (HP bar visible, skill bar)
    "interaction",  # F5: Interaction prompt ("[E] Ловить рыбу")
    "xp",           # F6: XP popup after mob kill
    "navigation",   # F7: Running to waypoint (destination text on compass)
    "general",      # F8: Miscellaneous useful screenshots
]

# Hotkey mapping: F1-F8 for categories, F10 for stop
HOTKEYS = {
    "F1": "map",
    "F2": "gameplay",
    "F3": "compass",
    "F4": "combat",
    "F5": "interaction",
    "F6": "xp",
    "F7": "navigation",
    "F8": "general",
}

# ── State ────────────────────────────────────────────────────────────
running = True
counts = {cat: 0 for cat in CATEGORIES}
# Queue for thread-safe communication: hotkey thread -> main thread
capture_queue = queue.Queue()


def ensure_dirs():
    """Create dataset directories if they don't exist."""
    for cat in CATEGORIES:
        path = os.path.join(BASE_DIR, cat)
        os.makedirs(path, exist_ok=True)
        counts[cat] = len([f for f in os.listdir(path) if f.endswith(".png")])


def make_handler(category):
    """Create a hotkey handler for a given category."""
    def handler(event):
        capture_queue.put(category)
    return handler


def on_stop(event):
    global running
    running = False
    capture_queue.put(None)  # Wake up main loop
    print("\n[F10] Stopping...")


def main():
    global running

    ensure_dirs()

    print("=" * 60)
    print("  ESO Screenshot Collector v2 (8 categories)")
    print("=" * 60)
    print(f"Save directory: {os.path.abspath(BASE_DIR)}")
    print()
    print("Existing screenshots:")
    total_existing = 0
    for cat in CATEGORIES:
        print(f"  {cat}: {counts[cat]} images")
        total_existing += counts[cat]
    print(f"  TOTAL: {total_existing} images")
    print()
    print("Controls (press while ESO is focused):")
    print("  F1  — MAP (blue hooks on map)")
    print("  F2  — GAMEPLAY (bubbles, enemies, fishing holes)")
    print("  F3  — COMPASS (waypoint marker left/center/right)")
    print("  F4  — COMBAT (HP bar, taking damage, fighting)")
    print("  F5  — INTERACTION (fishing prompt, \"[E] Ловить рыбу\")")
    print("  F6  — XP (XP popup after mob kill)")
    print("  F7  — NAVIGATION (destination text, running to waypoint)")
    print("  F8  — GENERAL (anything else)")
    print("  F10 — STOP collector")
    print()
    print("Tips for good training data:")
    print("  - Vary time of day, weather, locations")
    print("  - Compass: capture marker at LEFT, CENTER, RIGHT positions")
    print("  - Combat: capture HP full, medium, low")
    print("  - Interaction: capture different water types (river/lake/sea)")
    print()

    # Setup screen capture in main thread
    sct = mss.mss()
    monitor = sct.monitors[MONITOR_INDEX]
    print(f"Monitor: {monitor['width']}x{monitor['height']}")
    print("Waiting for hotkeys...\n")

    # Register hotkeys
    for key, category in HOTKEYS.items():
        keyboard.on_press_key(key, make_handler(category), suppress=False)
    keyboard.on_press_key("F10", on_stop, suppress=False)

    try:
        while running:
            try:
                # Wait for hotkey signal (timeout to check running flag)
                category = capture_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if category is None:
                break

            # Capture and save in main thread (mss is thread-safe here)
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"{category}_{timestamp}.png"
            filepath = os.path.join(BASE_DIR, category, filename)

            img.save(filepath)
            counts[category] += 1
            print(f"  [{category.upper()}] Saved #{counts[category]}: {filename}")

    except KeyboardInterrupt:
        pass
    finally:
        keyboard.unhook_all()
        print()
        print("Final counts:")
        for cat in CATEGORIES:
            print(f"  {cat}: {counts[cat]} images")
        total = sum(counts.values())
        print(f"  TOTAL: {total} images")
        print("Done.")


if __name__ == "__main__":
    main()
