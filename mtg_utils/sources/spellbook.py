"""Commander Spellbook: full-deck combo audit."""
import json
import subprocess
import time

from mtg_utils.cards import front_name
from mtg_utils.decklist import as_cmdrs, flat
from mtg_utils.sources import UA_TOOL


def spellbook_name(name, scry=None):
    """A decklist name written the way Commander Spellbook can match it.

    THE FULL `A // B` FORM, which is the opposite of what EDHREC wants and the
    same as what edhtop16 wants -- a third source, a third convention, and no
    two of them agree.

    Spellbook resolves a double-faced card by its full name only. Sent the
    front face alone it does not fail: it silently drops the card, derives the
    deck's colour identity from what is left, and answers the question about a
    DIFFERENT deck. Measured against the live endpoint on 2026-08-30, one
    commander and one spell:

        "Terra, Magical Adept"                  identity UR, included 0
        "Terra, Magical Adept // Esper Terra"   identity WUBRG, included 1

    The tell is visible in the output and easy to walk past: the combo comes
    back under `almostIncluded` as "one card away, needs Terra, Magical
    Adept", while Terra is the commander of the list being audited. A card
    cannot be one away from a piece that is always available.

    That is the worst failure shape available here, because the output is not
    merely wrong, it is reassuring: a deck being assessed for a bracket reads
    "in-deck combos: 0" and stops. Any commander-plus-one-card infinite -- the
    single most bracket-relevant thing a list can hold -- is exactly what it
    misses.

    Falls back to the name as written when the cache has never seen it, which
    is the pre-existing behaviour and no worse than it was.
    """
    c = (scry or {}).get(name.lower()) or (scry or {}).get(front_name(name).lower())
    return c["name"] if c else name


# ============================================================ external APIs
def spellbook(cmdr, entries, scry=None):
    cmdrs = as_cmdrs(cmdr)
    payload = json.dumps({"commanders": [{"card": spellbook_name(c, scry)}
                                         for c in cmdrs],
                          "main": [{"card": spellbook_name(n, scry)}
                                   for n in flat(cmdr, entries)[len(cmdrs):]]})
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
