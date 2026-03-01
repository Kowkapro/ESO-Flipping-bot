"""
HarvestMap data parser for fishing hole positions.

Reads fishing node coordinates from:
  1. HarvestMapData addon files (community data from server)
  2. HarvestMap SavedVariables (personal discovered data)

Data formats:
  - Community (binary): 8 bytes per node (2B x, 2B y, 2B z, 2B day), coords * 20
  - Personal (CSV): "worldX,worldY,worldZ,timestamp,version,0.0,0.0,flags"
  - Fishing pinTypeId = 8
"""

import os
import re

# HarvestMap constants
FISHING_PIN_TYPE = 8
DELETE_FLAG = 2

# Zone IDs from HarvestMap Serialization.lua
ZONE_IDS = {
    "glenumbra": 3,
    "stormhaven": 19,
    "rivenspire": 20,
    "alikr": 104,
    "bangkorai": 92,
    "stonefalls": 41,
    "deshaan": 57,
    "shadowfen": 117,
    "eastmarch": 101,
    "therift": 103,
    "auridon": 381,
    "grahtwood": 383,
    "greenshade": 108,
    "malabaltor": 58,
    "reapersmarch": 382,
}

# Zone name -> submodule file mapping
ZONE_TO_SUBMODULE = {
    "glenumbra": "DC", "stormhaven": "DC", "rivenspire": "DC",
    "alikr": "DC", "bangkorai": "DC",
    "stonefalls": "EP", "deshaan": "EP", "shadowfen": "EP",
    "eastmarch": "EP", "therift": "EP",
    "auridon": "AD", "grahtwood": "AD", "greenshade": "AD",
    "malabaltor": "AD", "reapersmarch": "AD",
}

ESO_DIR = os.path.join("d:", os.sep, "Documents", "Elder Scrolls Online", "live")
SAVED_VARS_DIR = os.path.join(ESO_DIR, "SavedVariables")
ADDON_DATA_DIR = os.path.join(os.path.dirname(__file__), "harvestmap_data")


def parse_community_binary(binary_data):
    """Parse binary community data (8 bytes per node).

    Each node: 2B worldX, 2B worldY, 2B worldZ, 2B discoveryDay
    Coordinates stored as big-endian uint16, multiply by 20 (0.2 * 100)
    to convert to raw world coordinates (matching GetUnitRawWorldPosition).
    """
    nodes = []
    if len(binary_data) % 8 != 0:
        return nodes

    for i in range(0, len(binary_data), 8):
        x1, x2, y1, y2, z1, z2, d1, d2 = binary_data[i : i + 8]
        world_x = (x1 * 256 + x2) * 20
        world_y = (y1 * 256 + y2) * 20
        world_z = (z1 * 256 + z2) * 20
        nodes.append({"x": world_x, "y": world_y, "z": world_z})

    return nodes


def parse_personal_node(csv_string):
    """Parse a single CSV node string from SavedVariables.

    Format: "worldX,worldY,worldZ,timestamp,version,0.0,0.0,flags"
    """
    parts = re.findall(r"-?\d*\.?\d+", csv_string)
    if len(parts) < 3:
        return None

    world_x = float(parts[0]) * 100
    world_y = float(parts[1]) * 100
    world_z = float(parts[2]) * 100
    flags = int(float(parts[7])) if len(parts) > 7 else 0

    if flags & DELETE_FLAG:
        return None

    return {"x": world_x, "y": world_y, "z": world_z}


def decode_lua_binary_string(raw_bytes):
    """Extract binary node data from a Lua file's raw bytes.

    The addon data file contains binary strings as raw bytes in Lua literals.
    We read the file as bytes and extract data between [8]=" and " markers.
    """
    result = bytearray()
    i = 0
    while i < len(raw_bytes):
        b = raw_bytes[i]
        if b == ord("\\") and i + 1 < len(raw_bytes):
            next_b = raw_bytes[i + 1]
            # Numeric escape \DDD
            if ord("0") <= next_b <= ord("9"):
                digits = chr(next_b)
                j = i + 2
                while j < len(raw_bytes) and j < i + 4 and ord("0") <= raw_bytes[j] <= ord("9"):
                    digits += chr(raw_bytes[j])
                    j += 1
                result.append(int(digits) % 256)
                i = j
            elif next_b == ord("n"):
                result.append(10)
                i += 2
            elif next_b == ord("t"):
                result.append(9)
                i += 2
            elif next_b == ord("r"):
                result.append(13)
                i += 2
            elif next_b == ord("\\"):
                result.append(92)
                i += 2
            elif next_b == ord('"'):
                result.append(34)
                i += 2
            else:
                result.append(next_b)
                i += 2
        else:
            result.append(b)
            i += 1
    return bytes(result)


def parse_addon_data_file(filepath, zone_name="glenumbra"):
    """Parse a HarvestMapData addon file for fishing nodes.

    File format: HarvestXX_Data={[zoneId]={["map/map_base"]={[pinTypeId]="binary",...},...},...}
    The binary data is stored as raw bytes in Lua string literals.
    """
    if not os.path.exists(filepath):
        return []

    zone_id = ZONE_IDS.get(zone_name)
    if zone_id is None:
        return []

    with open(filepath, "rb") as f:
        raw = f.read()

    nodes = []
    zone_prefix = zone_name.encode("ascii")

    # Find all map blocks for this zone that contain fishing data [8]=
    # Pattern: ["zonename/mapname"]={...[8]="<binary>"...}
    # We search for map names starting with the zone name
    map_pattern = rb'\["(' + zone_prefix + rb'/[^"]+)"\]=\{'
    for map_match in re.finditer(map_pattern, raw):
        map_name = map_match.group(1).decode("ascii")
        start = map_match.end()

        # Find the fishing pinType [8]=" within this map block
        # Search within reasonable range (blocks are typically < 50KB)
        search_end = min(start + 50000, len(raw))
        chunk = raw[start:search_end]

        # Stop at next map block
        next_map = re.search(rb'\["[a-z]', chunk)
        if next_map:
            chunk = chunk[: next_map.start()]

        # Find [8]="..." - fishing data
        fishing_match = re.search(rb'\[8\]="', chunk)
        if not fishing_match:
            continue

        # Extract binary string between quotes
        data_start = fishing_match.end()
        # Find closing quote (not preceded by backslash)
        pos = data_start
        while pos < len(chunk):
            if chunk[pos] == ord('"') and chunk[pos - 1] != ord("\\"):
                break
            # Handle escaped quote \"
            if chunk[pos] == ord("\\"):
                pos += 2
            else:
                pos += 1

        binary_lua_str = chunk[data_start:pos]
        binary_data = decode_lua_binary_string(binary_lua_str)
        map_nodes = parse_community_binary(binary_data)

        if map_nodes:
            for node in map_nodes:
                node["map"] = map_name
            nodes.extend(map_nodes)

    return nodes


def parse_savedvars_file(filepath, zone_name="glenumbra"):
    """Parse a HarvestMap SavedVariables Lua file for personal fishing nodes."""
    if not os.path.exists(filepath):
        return []

    zone_id = ZONE_IDS.get(zone_name)
    if zone_id is None:
        return []

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    nodes = []

    zone_pattern = rf"\[{zone_id}\]\s*=\s*\{{(.*?)\n\s*\}},"
    zone_match = re.search(zone_pattern, content, re.DOTALL)
    if not zone_match:
        return []

    zone_content = zone_match.group(1)

    # Find all [8] blocks (fishing) across all maps
    for fishing_match in re.finditer(r"\[8\]\s*=\s*\{(.*?)\},", zone_content, re.DOTALL):
        fishing_content = fishing_match.group(1)
        node_strings = re.findall(r'"([^"]+)"', fishing_content)
        for s in node_strings:
            node = parse_personal_node(s)
            if node:
                nodes.append(node)

    return nodes


def deduplicate_nodes(nodes, threshold=500.0):
    """Remove duplicate nodes within threshold distance of each other."""
    unique = []
    for node in nodes:
        is_dup = False
        for existing in unique:
            dx = node["x"] - existing["x"]
            dy = node["y"] - existing["y"]
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < threshold:
                is_dup = True
                break
        if not is_dup:
            unique.append(node)
    return unique


def get_fishing_holes(zone_name="glenumbra"):
    """Get all known fishing hole positions for a zone.

    Reads from both addon data files and personal SavedVariables.
    Returns deduplicated list of {x, y, z} dicts.
    """
    all_nodes = []
    submodule = ZONE_TO_SUBMODULE.get(zone_name, "DLC")

    # 1. Community data from downloaded HarvestMap data
    addon_file = os.path.join(
        ADDON_DATA_DIR, f"Harvest{submodule}_Data.lua"
    )
    addon_nodes = parse_addon_data_file(addon_file, zone_name)
    all_nodes.extend(addon_nodes)
    if addon_nodes:
        maps = set(n.get("map", "?") for n in addon_nodes)
        print(f"Community data: {len(addon_nodes)} fishing holes across {len(maps)} maps")
        for m in sorted(maps):
            count = sum(1 for n in addon_nodes if n.get("map") == m)
            print(f"  {m}: {count} holes")

    # 2. Personal data from SavedVariables
    sv_file = os.path.join(SAVED_VARS_DIR, f"Harvest{submodule}_SavedVars.lua")
    personal_nodes = parse_savedvars_file(sv_file, zone_name)
    all_nodes.extend(personal_nodes)
    if personal_nodes:
        print(f"Personal data: {len(personal_nodes)} fishing holes")

    if not all_nodes:
        print(f"No fishing hole data found for {zone_name}.")
        print("Run DownloadNewData.bat in HarvestMapData addon folder to download community data.")
        return []

    # Deduplicate
    unique = deduplicate_nodes(all_nodes, threshold=500.0)
    print(f"Total unique fishing holes: {len(unique)}")
    return unique


if __name__ == "__main__":
    print("=== HarvestMap Fishing Hole Parser ===\n")

    holes = get_fishing_holes("glenumbra")

    if holes:
        print(f"\nFirst 10 fishing holes in Glenumbra:")
        for i, hole in enumerate(holes[:10]):
            map_name = hole.get("map", "unknown")
            print(f"  #{i+1}: x={hole['x']:.1f}, y={hole['y']:.1f}, z={hole['z']:.1f}  ({map_name})")
