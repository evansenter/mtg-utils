"""Commander Spellbook: full-deck combo audit."""
import json
import subprocess
import time

from mtg_utils.decklist import as_cmdrs, flat
from mtg_utils.sources import UA_TOOL

# ============================================================ external APIs
def spellbook(cmdr, entries):
    cmdrs = as_cmdrs(cmdr)
    payload = json.dumps({"commanders": [{"card": c} for c in cmdrs],
                          "main": [{"card": n} for n in flat(cmdr, entries)[len(cmdrs):]]})
    for _try in range(3):
        r = subprocess.run(["curl", "-s", "-X", "POST",
                            "-H", "Content-Type: application/json",
                            "-H", f"User-Agent: {UA_TOOL}", "-d", payload,
                            "https://backend.commanderspellbook.com/find-my-combos/"],
                           capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
        except Exception:
            time.sleep(2); continue
        if isinstance(d, dict) and "results" in d:
            return d["results"]
        time.sleep(2)
    raise SystemExit("Commander Spellbook find-my-combos failed after retries "
                     f"(last body: {r.stdout[:200]!r})")
