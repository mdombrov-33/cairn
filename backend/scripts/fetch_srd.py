#!/usr/bin/env python3
"""
Fetch D&D 5e SRD data from dnd5eapi.co and store as JSON in src/cairn/rules/.
Run once: uv run python scripts/fetch_srd.py
Source: https://www.dnd5eapi.co (backed by https://github.com/5e-bits/5e-database)
"""

import json
import time
import urllib.request
from pathlib import Path

ROOT = "https://www.dnd5eapi.co"
BASE = f"{ROOT}/api"
OUT = Path(__file__).parent.parent / "src" / "cairn" / "rules"
OUT.mkdir(exist_ok=True)


def fetch(url: str) -> dict:
    if url.startswith("/"):
        url = f"{ROOT}{url}"
    print(f"  GET {url}")
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def fetch_list_and_each(endpoint: str) -> list[dict]:
    index = fetch(f"{BASE}/{endpoint}")
    results = []
    for item in index["results"]:
        detail = fetch(item["url"])
        results.append(detail)
        time.sleep(0.05)
    return results


def save(name: str, data: object) -> None:
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(data, indent=2))
    print(f"  -> saved {path.name} ({len(json.dumps(data)) // 1024}kb)")


print("Fetching conditions...")
conditions = fetch_list_and_each("conditions")
save("conditions", conditions)

print("Fetching spells...")
spells = fetch_list_and_each("spells")
save("spells", spells)

print("Fetching classes...")
classes = fetch_list_and_each("classes")
save("classes", classes)

print("Fetching races...")
races = fetch_list_and_each("races")
save("races", races)

print("Fetching equipment (weapons + armor)...")
equipment = fetch_list_and_each("equipment")
save("equipment", equipment)

print("Fetching magic items...")
magic_items = fetch_list_and_each("magic-items")
save("magic_items", magic_items)

print("Fetching monsters...")
monsters = fetch_list_and_each("monsters")
save("monsters", monsters)

print("Fetching skills...")
skills = fetch_list_and_each("skills")
save("skills", skills)

print("Fetching damage types...")
damage_types = fetch_list_and_each("damage-types")
save("damage_types", damage_types)

print("Fetching weapon properties...")
weapon_props = fetch_list_and_each("weapon-properties")
save("weapon_properties", weapon_props)

print("Fetching class levels (features, spell slots)...")
class_levels = {}
for cls in classes:
    slug = cls["index"]
    levels = fetch(f"{BASE}/classes/{slug}/levels")
    class_levels[slug] = levels
    time.sleep(0.05)
save("class_levels", class_levels)

print("Done. All SRD data saved to src/cairn/rules/")
