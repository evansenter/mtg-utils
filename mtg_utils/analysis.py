"""Compute, no printing. The report_* wrappers only format what these return."""
import random
import re

from mtg_utils.cards import front, has_land_back, is_front_land, land_face, enters_tapped
from mtg_utils.castability import (castable_faces, pips_from_cost, playsim_report,
                                   probability)
from mtg_utils.decklist import as_cmdrs, flat
from mtg_utils.profiles import build_accel_profiles, build_land_profiles

# ============================================================ verify
def verify(cmdr, entries, scry):
    cmdrs = as_cmdrs(cmdr)
    names = flat(cmdr, entries)
    total = len(names)
    gc, illegal, ci_bad = [], [], []
    ident = set()
    for cn in cmdrs:
        if scry.get(cn.lower()):
            ident |= set(scry[cn.lower()]["color_identity"])
    lands = nonland = 0
    mv_sum = 0.0
    truly, cond = [], []
    truly_n = cond_n = 0
    for n, q in list(entries.items()) + [(cn, 1) for cn in cmdrs]:
        c = scry.get(n.lower())
        if not c:
            illegal.append((n, "NOT FOUND")); continue
        if c["legalities"]["commander"] != "legal":
            illegal.append((n, c["legalities"]["commander"]))
        if set(c["color_identity"]) - ident:
            ci_bad.append((n, "".join(c["color_identity"])))
        if c.get("game_changer"):
            gc.append(n)
        if is_front_land(c):
            lands += q
            lf = land_face(c)
            t, cm = enters_tapped(lf, c)
            # The name is listed once; the COUNT is by quantity, so it is in
            # the same units as `lands` beside it in the header. They coincide
            # in singleton Commander -- basics are the only entries above one
            # and are never tapped -- so this changes no current output. The
            # two numbers were simply in different units.
            if t:
                truly.append(n)
                truly_n += q
            elif cm:
                cond.append((n, cm))
                cond_n += q
        elif n not in cmdrs:
            nonland += q
            mv_sum += float(front(c, "cmc", 0) or 0) * q
    mdfc = sum(q for n, q in entries.items()
               if scry.get(n.lower()) and has_land_back(scry[n.lower()]))
    return {"total": total, "lands": lands, "mdfc_land_backs": mdfc,
            "nonland": nonland, "avg_mv": mv_sum / nonland if nonland else 0,
            "game_changers": sorted(gc), "illegal": illegal,
            "ci_violations": ci_bad, "truly_tapped": truly,
            "conditional_tapped": cond,
            "truly_tapped_copies": truly_n, "conditional_tapped_copies": cond_n}


# ============================================================ reporting
def worst_lines(names, scry, lands, accels, sims, rng, top=5, deck_size=None):
    """Sources-model rows, worst first. Pure compute -- no printing, so a test
    can assert on the numbers instead of scraping stdout.

    deck_size is the LIBRARY, i.e. the deck minus its commanders: 99 for one
    commander and 98 for a partner or background pair. Defaults to len(names),
    which is exactly that, because `names` is already the non-commander
    multiset.
    """
    if deck_size is None:
        deck_size = len(names)
    cand = {}
    for n in names:
        c = scry.get(n.lower())
        if not c or is_front_land(c) or has_land_back(c):
            continue
        for label, cost, mv in castable_faces(c):
            req = pips_from_cost(cost)
            if not req:
                continue
            turn = max(mv, len(req), 1)
            if turn > 7:
                continue
            cand.setdefault((turn, mv, tuple(sorted(req))), []).append(label)
    rows = []
    for (turn, mv, req), cards in cand.items():
        p = probability(lands, accels, deck_size, list(req), mv, turn, sims, rng)
        rows.append((p, turn, mv, req, sorted(set(cards))))
    rows.sort()
    return rows[:top] if top else rows


def commander_lines(cmdr, scry):
    """One play-sim line per commander -- a partner pair has two curves."""
    out = []
    for cn in as_cmdrs(cmdr):
        c = scry.get(cn.lower())
        if not c:
            continue
        out.append((f"{cn} on curve", int(front(c, "cmc", 0) or 0),
                    "".join(f"{{{x}}}" for x in
                            pips_from_cost(front(c, "mana_cost", "")))))
    return out


def analyse_mana(cmdr, entries, scry, sims, trials, seed=17, lines=None):
    """The whole section 6 measurement, as data. report_mana only prints it."""
    ncmdr = len(as_cmdrs(cmdr))
    names = flat(cmdr, entries)[ncmdr:]
    lands = build_land_profiles(names, scry)
    accels = build_accel_profiles(names, scry)
    v = verify(cmdr, entries, scry)
    # The library is the deck minus its commanders -- 98 for a partner pair,
    # not 99. Drawing from a library one card too large dilutes it with an
    # extra non-source and biases every figure the same way.
    deck_size = len(names)
    rows = worst_lines(names, scry, lands, accels, sims, random.Random(seed),
                       deck_size=deck_size)
    if lines is None:
        lines, seen = [], set()
        for p, turn, mv, req, cards in rows:
            key = (mv, tuple(req))
            if key in seen:
                continue
            seen.add(key)
            lines.append((f"{cards[0]} T{turn}", mv,
                          "".join("{%s}" % x for x in req)))
        lines += commander_lines(cmdr, scry)
    res = playsim_report(lands, accels, deck_size, lines, trials, random.Random(seed))
    return {"verify": v, "lands": lands, "accels": accels,
            "rows": rows, "lines": lines, "sim": res}


def deck_base_name(name):
    """Strip a trailing bracketed tag: 'Muldrotha [Bracket 3 Temp]' -> 'muldrotha'."""
    return re.sub(r"[\[\(][^\]\)]*[\]\)]", "", name or "").strip().lower()


def collapse_temps(use):
    """Section 2: a Temp is an alternative build of the SAME physical deck, so
    it does not compete for a card with its own main list. Counting both made
    every shared card look contended and turned an output into a phantom
    purchase line. Collapse a '[... Temp]' listing into the main it shares a
    base name with; a Temp with no main of its own stands alone.
    """
    mains = {deck_base_name(n) for n in use if "temp" not in n.lower()}
    out = {}
    for name, cards in use.items():
        if "temp" in name.lower() and deck_base_name(name) in mains:
            continue
        out[name] = cards
    return out
