"""Scryfall: batch card fetch with an on-disk cache."""
import json
import os
import subprocess
import time

from mtg_utils.sources import UA_TOOL

# ============================================================ Scryfall
def scry_fetch(names, cache_path=None):
    cache = {}
    if cache_path and os.path.exists(cache_path):
        cache = json.load(open(cache_path))
    want = [n for n in dict.fromkeys(names) if n.lower() not in cache]
    nf = []
    for i in range(0, len(want), 75):
        chunk = want[i:i + 75]
        payload = json.dumps({"identifiers": [{"name": n.split(" // ")[0]} for n in chunk]})
        for _try in range(4):
            r = subprocess.run(
                ["curl", "-s", "-X", "POST", "-H", "Content-Type: application/json",
                 "-H", "Accept: application/json", "-H", f"User-Agent: {UA_TOOL}",
                 "-d", payload, "https://api.scryfall.com/cards/collection"],
                capture_output=True, text=True)
            try:
                d = json.loads(r.stdout)
            except Exception:
                time.sleep(2); continue
            if d.get("object") == "list":
                break
            time.sleep(2)
        else:
            raise SystemExit("Scryfall /cards/collection failed after retries")
        for c in d["data"]:
            # key on BOTH the full name and the front-face name
            cache[c["name"].lower()] = c
            cache[c["name"].split(" // ")[0].lower()] = c
        nf += [x.get("name") for x in d.get("not_found", [])]
        time.sleep(0.2)
    if cache_path:
        json.dump(cache, open(cache_path, "w"))
    return cache, nf
