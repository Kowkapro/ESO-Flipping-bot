"""Launch main_v5 bot starting from a specific hole (default: hole 8).

Usage:
  python fishing/test_from_hole.py          # start from hole 8
  python fishing/test_from_hole.py 12       # start from hole 12
"""

import sys
import main_v5

# Patch: override nearest-hole search to use specified index
_original_main = main_v5.main

def patched_main():
    start_hole = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    # Monkey-patch distance so nearest-hole search always picks our hole
    orig_distance = main_v5.distance
    target_idx = start_hole - 1  # 0-based

    def fake_distance(x1, y1, x2, y2):
        # During init, holes are compared — make our target closest
        return orig_distance(x1, y1, x2, y2)

    # Simpler: just patch best_idx after main starts.
    # We'll override the load_route to reorder holes starting from target.
    orig_load = main_v5.load_route

    def reordered_route():
        holes = orig_load()
        # Rotate list so target hole is first, then nearest-hole search picks idx 0
        return holes[target_idx:] + holes[:target_idx]

    main_v5.load_route = reordered_route
    print(f"\n*** TEST MODE: starting from hole {start_hole} ***\n")

    try:
        _original_main()
    finally:
        main_v5.load_route = orig_load

patched_main()
