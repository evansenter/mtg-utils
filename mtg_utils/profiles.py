"""Source profiles: what each land and cheap accelerant actually produces."""
import re

from mtg_utils.cards import (COLOURS, MANA_SYMBOLS, BASIC_TYPE_COLOUR, enters_tapped,
                             fetch_targets, front, has_land_back, is_front_land,
                             land_face, mana_amount)

FILTER_LANDS = {
    "mystic gate": "WU", "sunken ruins": "UB", "graven cairns": "BR",
    "fire-lit thicket": "RG", "wooded bastion": "GW", "fetid heath": "WB",
    "cascade bluffs": "UR", "twilight mire": "BG", "rugged prairie": "RW",
    "flooded grove": "GU",
}


OMNI_TYPE = {"urborg, tomb of yawgmoth": "B", "yavimaya, cradle of growth": "G"}


# ============================================================ profiles
def build_land_profiles(deck_names, scry):
    profiles = []
    for n in deck_names:
        c = scry.get(n.lower())
        if not c:
            continue
        lf = land_face(c)
        if not lf:
            continue
        name = c["name"].lower()
        txt = (lf.get("oracle_text") or "").lower()
        pm = set(x for x in (lf.get("produced_mana") or c.get("produced_mana") or [])
                 if x in MANA_SYMBOLS)
        kind = "normal"
        if name in FILTER_LANDS:
            kind = "filter"
            pm = set(FILTER_LANDS[name])
        elif not pm:
            ft = fetch_targets(txt)
            if ft:
                kind = "fetch"
                pm = set()
                for n2 in deck_names:
                    c2 = scry.get(n2.lower())
                    if not c2:
                        continue
                    lf2 = land_face(c2)
                    if not lf2:
                        continue
                    tl = lf2.get("type_line", "").lower()
                    if any(t in tl for t, col in BASIC_TYPE_COLOUR.items() if col in ft):
                        pm.update(x for x in (lf2.get("produced_mana") or []) if x in COLOURS)
        tapped, cond = enters_tapped(lf, c)
        profiles.append({
            "name": name, "kind": "land",
            "colours": frozenset(pm),
            "filter": FILTER_LANDS.get(name),
            "tapped": False if kind == "fetch" else tapped,
            "cond_tap": cond,
            "amount": 1 if kind in ("filter", "fetch") else mana_amount(txt),
            "omni": OMNI_TYPE.get(name),
            "mdfc": has_land_back(c),
        })
    return profiles


def build_accel_profiles(deck_names, scry, max_mv=3):
    """Cheap accelerants: non-land, MV <= max_mv, taps for mana.

    Restricted mana ("spend this mana only to cast Dwarf spells") is flagged
    and excluded from generic totals by default -- counting it as free mana is
    how a restricted rock silently inflates an on-curve number.
    """
    out = []
    for n in deck_names:
        c = scry.get(n.lower())
        if not c or is_front_land(c):
            continue
        mv = float(front(c, "cmc", c.get("cmc", 0)) or 0)
        if mv > max_mv:
            continue
        txt = (front(c, "oracle_text", "") or "").lower()
        if not re.search(r"\{t\}[^:]*:\s*add", txt) and "add " not in txt:
            continue
        if "add" not in txt:
            continue
        pm = set(x for x in (c.get("produced_mana") or []) if x in MANA_SYMBOLS)
        if not pm and re.search(r"add \{c\}", txt):
            pm = {"C"}
        if not pm:
            continue
        tapped, cond = enters_tapped(c, c)
        out.append({
            "name": c["name"].lower(), "kind": "accel",
            "colours": frozenset(pm), "filter": None, "omni": None,
            "amount": mana_amount(txt),
            "cost": int(mv),
            "tapped": tapped, "cond_tap": cond,
            "restricted": "spend this mana only" in txt,
            "creature": "Creature" in c["type_line"].split("//")[0],
            "mdfc": False,
        })
    return out
