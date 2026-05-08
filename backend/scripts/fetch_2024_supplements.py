#!/usr/bin/env python3
"""
Fetch feats and traits from the 2024 D&D SRD (CC-BY-4.0) and write into src/cairn/srd/.

The 2014 API has 1 feat and 38 traits; the 2024 API has 17 feats and 67 traits.
Everything else (spells, monsters, equipment) stays on 2014 — the 2024 dataset is
incomplete there (3 monsters, no spells endpoint).

Run once from the repo root:
    uv run python backend/scripts/fetch_2024_supplements.py
"""

import json
import time
import urllib.request
from pathlib import Path

ROOT = "https://www.dnd5eapi.co"
BASE_2024 = f"{ROOT}/api/2024"
OUT = Path(__file__).parent.parent / "src" / "cairn" / "srd"


def fetch(url: str) -> dict:
    if url.startswith("/"):
        url = f"{ROOT}{url}"
    print(f"  GET {url}")
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def fetch_all(endpoint: str) -> list[dict]:
    index = fetch(f"{BASE_2024}/{endpoint}")
    results = []
    for item in index["results"]:
        detail = fetch(item["url"])
        results.append(detail)
        time.sleep(0.05)
    return results


def save(name: str, data: list) -> None:
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(data, indent=2))
    print(f"  -> {path} ({len(data)} items)")


print("Fetching feats from 2024 SRD...")
feats = fetch_all("feats")
save("feats", feats)

print("Fetching traits from 2024 SRD...")
traits = fetch_all("traits")
save("traits", traits)

print("Done.")
