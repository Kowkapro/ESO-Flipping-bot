"""Run fishing bot starting from a specific hole.
Usage: python fishing/tests/test_from_hole.py 8   (starts from hole 8/17)
Does NOT modify main_v5.py — patches read_player_state to fake nearest hole.
"""
import sys
import os
import json

START_HOLE = int(sys.argv[1]) if len(sys.argv) > 1 else 1

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main_v5
from pixel_bridge import PlayerState

# Load route to get target hole coordinates
route_file = os.path.join(os.path.dirname(__file__), "..", "route_holes.json")
with open(route_file) as f:
    holes = json.load(f)

target = holes[START_HOLE - 1]
print(f"[TEST] Will start from hole {START_HOLE}/{len(holes)} "
      f"at ({target['x']}, {target['y']})")

# Monkey-patch: first 2 read_player_state calls (init test + find nearest)
# return fake position at the target hole so "find nearest" picks it.
# After that, real reads take over.
_orig_read = main_v5.read_player_state
_call_count = [0]


def _patched_read(sct, monitor):
    _call_count[0] += 1
    if _call_count[0] <= 2:
        return PlayerState(
            x=float(target["x"]), y=float(target["y"]),
            heading=0.0, in_combat=False, has_interaction=False,
            is_fishing=False, reticle_hidden=False, is_swimming=False,
            is_hidden=False, free_slots=100,
        )
    return _orig_read(sct, monitor)


main_v5.read_player_state = _patched_read

if __name__ == "__main__":
    import pydirectinput
    try:
        main_v5.main()
    except Exception as e:
        print(f"\n[FATAL] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            pydirectinput.keyUp('w')
            pydirectinput.keyUp('shift')
        except Exception:
            pass
