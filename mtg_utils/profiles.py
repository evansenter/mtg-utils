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
RESTRICTED_MANA = "spend this mana only"


def unrestricted_mana(txt):
    """(colours, amount) a land offers with NO strings attached.

    Scryfall puts one ability per line, and the restriction rides on the same
    line as the ability it restricts:

        {T}: Add {C}.
        {T}: Add {C}{C}. Spend this mana only to cast colorless Eldrazi spells.

    so dropping the restricted lines leaves exactly the mana that pays for
    anything. Eldrazi Temple is a 1, not a 2. Cavern of Souls and Unclaimed
    Territory produce {C} and nothing else -- their any-colour mana casts one
    creature type, and counting it as free colour made a mono-red deck look
    like it had five.

    Returns (set(), 0) when every ability is restricted, which flags the land
    for exclusion the same way build_accel_profiles flags a restricted rock.
    """
    free = "\n".join(l for l in txt.split("\n") if RESTRICTED_MANA not in l)
    cols, amount = set(), 0
    for match in re.finditer(r"add ([^.;\n]*)", free):
        clause = match.group(1)
        cols |= {c.upper() for c in re.findall(r"\{([wubrgc])\}", clause)}
        if "any color" in clause:
            cols |= set(COLOURS)
        amount = max(amount, 1)
    return cols, (mana_amount(free) if amount else 0)


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
        amount = 1 if kind in ("filter", "fetch") else mana_amount(txt)
        restricted = False
        # "Spend this mana only to cast..." is not mana for a generic total,
        # on a land exactly as on a rock. Recomputed only for lands that
        # carry the clause, so every other land is untouched.
        if kind == "normal" and RESTRICTED_MANA in txt:
            free_cols, free_amount = unrestricted_mana(txt)
            restricted = not free_amount
            if free_amount:
                pm = {x for x in free_cols if x in MANA_SYMBOLS}
                amount = free_amount
        profiles.append({
            "name": name, "kind": "land",
            "colours": frozenset(pm),
            "filter": FILTER_LANDS.get(name),
            "tapped": False if kind == "fetch" else tapped,
            "cond_tap": cond,
            "amount": amount,
            "omni": OMNI_TYPE.get(name),
            "restricted": restricted,
            "mdfc": has_land_back(c),
        })
    return profiles


# A mana source is a PERMANENT with an activated ability that adds mana.
# "Battle" and "Planeswalker" are here for completeness; front-face lands are
# already filtered out before this is consulted.
PERMANENT_TYPES = ("Artifact", "Creature", "Enchantment", "Land",
                   "Planeswalker", "Battle")
# Reminder text is parenthetical, and a Treasure token's reminder text reads
# '{T}, Sacrifice this token: Add one mana of any color'. Matching it made
# every Treasure-maker a mana source. Strip parentheticals before deciding
# whether THIS card makes mana -- but never for a land, where a dual's whole
# ability is reminder text: Taiga's oracle text is exactly "({T}: Add {R} or
# {G}.)" and stripping it would leave nothing.
REMINDER_TEXT = re.compile(r"\([^)]*\)")
# An activated ability that adds mana: a cost, a colon, then "add" before the
# clause ends. The cost deliberately does NOT have to be {T} -- Ashnod's Altar
# and Phyrexian Altar add mana off a sacrifice and are real, repeatable
# sources.
MANA_ABILITY = re.compile(r":[^.]*\badd\b")


# A TRIGGERED mana ability is the third category, and until now it was the
# invisible one: MANA_ABILITY requires a colon, so a card whose mana arrives
# off a trigger matched nothing and was dropped from the accelerant list
# entirely. Lotus Cobra and Nissa, Resurgent Animist are both MV<=3, both
# make mana, and neither was counted.
#
# The two shapes are NOT equally reliable, and collapsing them would be the
# whole mistake:
#
#   phase  "At the beginning of your first main phase, add {G}{G}."
#          Fires on its own, every turn, once it is on the battlefield. As
#          reliable as a rock.
#   event  "Landfall -- Whenever a land you control enters, add one mana of
#          any color."
#          Fires only when something happens that neither model simulates.
#
# Anchored on the trigger word so the clause has to BE the trigger: a card
# that merely mentions adding mana in a later sentence does not qualify, and
# the produced_mana gate below still has the final say either way.
TRIGGERED_PHASE = re.compile(r"at the beginning of [^.]*?,\s*add\b")
TRIGGERED_EVENT = re.compile(r"whenever [^.]*?,\s*add\b")


def triggered_mana(txt):
    """"phase", "event", or None for oracle text with no triggered mana.

    Phase is tested first, but that order is a TIE-BREAK NO PRINTED CARD
    CURRENTLY EXERCISES -- a Scryfall search for oracle text carrying both
    shapes returns nothing. It is written down rather than left implicit so
    that if such a card is ever printed the tool picks the reliable reading
    instead of whichever branch happened to be first, but there is no test
    for it, because there is no card to write one against.
    """
    if TRIGGERED_PHASE.search(txt):
        return "phase"
    if TRIGGERED_EVENT.search(txt):
        return "event"
    return None


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
        # Both halves are load-bearing. The permanent check drops one-shots:
        # Dark Ritual (Instant, MV 1, "Add {B}{B}{B}") was counted as a
        # permanent producing three mana EVERY turn from the moment it was
        # drawn. The reminder-text strip drops spells that merely make a
        # mana-producing token: An Offer You Can't Refuse is a counterspell
        # whose Treasures go to the OPPONENT, and it counted as a source.
        if not any(t in c["type_line"].split("//")[0] for t in PERMANENT_TYPES):
            continue
        # Reminder text is stripped for the triggered check too, and for the
        # same reason: a Treasure token's reminder text describes an ability
        # the TOKEN has, not one this card has.
        stripped = REMINDER_TEXT.sub(" ", txt)
        trigger = None
        if not MANA_ABILITY.search(stripped):
            trigger = triggered_mana(stripped)
            if not trigger:
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
            # None for an ordinary activated ability. "phase" and "event"
            # are consumed differently by both models -- see castability.
            "trigger": trigger,
            "creature": "Creature" in c["type_line"].split("//")[0],
            "mdfc": False,
        })
    return out
