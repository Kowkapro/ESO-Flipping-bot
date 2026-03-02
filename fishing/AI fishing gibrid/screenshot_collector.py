"""
Screenshot Collector — collect training data for YOLO model.

Run this while playing ESO. Press hotkeys to save screenshots
into categorized folders for later annotation.

Controls:
  F7 — save screenshot as "map" (map with fishing hooks)
  F8 — save screenshot as "gameplay" (fishing, combat, navigation)
  F9 — save screenshot as "compass" (compass bar with waypoint)
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
CATEGORIES = ["map", "gameplay", "compass"]

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


def on_map(event):
    capture_queue.put("map")

def on_gameplay(event):
    capture_queue.put("gameplay")

def on_compass(event):
    capture_queue.put("compass")

def on_stop(event):
    global running
    running = False
    capture_queue.put(None)  # Wake up main loop
    print("\n[F10] Stopping...")


def main():
    global running

    ensure_dirs()

    print("=" * 50)
    print("  ESO Screenshot Collector")
    print("=" * 50)
    print(f"Save directory: {os.path.abspath(BASE_DIR)}")
    print()
    print("Existing screenshots:")
    for cat in CATEGORIES:
        print(f"  {cat}: {counts[cat]} images")
    print()
    print("Controls (press while ESO is focused):")
    print("  F7  — save MAP screenshot (open map with hooks)")
    print("  F8  — save GAMEPLAY screenshot (fishing/combat/world)")
    print("  F9  — save COMPASS screenshot (compass with waypoint)")
    print("  F10 — stop collector")
    print()

    # Setup screen capture in main thread
    sct = mss.mss()
    monitor = sct.monitors[MONITOR_INDEX]
    print(f"Monitor: {monitor['width']}x{monitor['height']}")
    print("Waiting for hotkeys...\n")

    # Register hotkeys
    keyboard.on_press_key("F7", on_map, suppress=False)
    keyboard.on_press_key("F8", on_gameplay, suppress=False)
    keyboard.on_press_key("F9", on_compass, suppress=False)
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
