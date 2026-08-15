"""Compute, no printing. The report_* wrappers only format what these return."""
import math
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


# ============================================================ Monte Carlo noise
def split_budget(total, reps):
    """Divide a Monte Carlo budget across replicates, preserving the total.

    `--sims` and `--trials` are the budget for the whole measurement, not per
    replicate, so turning replicates on does not silently triple the work or
    change how precise the reported figure is. The mean of R replicates at
    T/R trials has exactly the variance of one run at T trials -- the error
    bar comes out of re-slicing the same work, not out of doing more of it.

    reps=1 returns [total], so a single-replicate run at a given seed is
    bit-identical to the code before replicates existed. That is what pins
    this as a re-slicing rather than a change of method.
    """
    if reps < 1:
        raise SystemExit(f"reps must be at least 1, got {reps}")
    base, extra = divmod(total, reps)
    if base < 1:
        raise SystemExit(
            f"cannot split a budget of {total} across {reps} replicates: each "
            f"would get fewer than one trial. Raise --sims/--trials or lower "
            f"--reps.")
    return [base + (1 if i < extra else 0) for i in range(reps)]


def mean_spread(values):
    """(mean, standard error of the mean) over replicate measurements.

    The spread reported is the wobble of the REPORTED figure, which is the
    mean of the replicates -- not the spread of the replicates themselves.
    The mean of R replicates moves 1/sqrt(R) as much as any one of them, so
    quoting the replicate spread would overstate the uncertainty of the
    printed number by exactly that factor. An error bar that is wrong in a
    plausible direction is worse than no error bar, which is the whole reason
    this repo does not let a number ship unlabelled.
    """
    n = len(values)
    m = sum(values) / n
    if n < 2:
        return m, 0.0
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    return m, math.sqrt(var / n)


def replicate_playsim(lands, accels, deck_size, lines, trials, seed, reps):
    """playsim_report over `reps` replicates, aggregated to (mean, spread).

    Shapes deliberately differ from playsim_report's, so a caller cannot read
    an aggregated figure as a raw one by accident:

        generic[turn] -> (mean, spread)
        lines[label]  -> (mean, turn, spread)
    """
    per = [playsim_report(lands, accels, deck_size, lines, t, random.Random(seed + i))
           for i, t in enumerate(split_budget(trials, reps))]
    out = {}
    for side in ("play", "draw"):
        generic, labelled = {}, {}
        for t in per[0][side]["generic"]:
            generic[t] = mean_spread([r[side]["generic"][t] for r in per])
        for label in per[0][side]["lines"]:
            m, sp = mean_spread([r[side]["lines"][label][0] for r in per])
            labelled[label] = (m, per[0][side]["lines"][label][1], sp)
        out[side] = {"generic": generic, "lines": labelled}
    return out


def analyse_mana(cmdr, entries, scry, sims, trials, seed=17, lines=None, reps=3):
    """The whole section 6 measurement, as data. report_mana only prints it.

    `sims` and `trials` are totals across `reps` replicates -- see
    split_budget. Rows carry their spread as a sixth element.
    """
    ncmdr = len(as_cmdrs(cmdr))
    names = flat(cmdr, entries)[ncmdr:]
    lands = build_land_profiles(names, scry)
    accels = build_accel_profiles(names, scry)
    v = verify(cmdr, entries, scry)
    # The library is the deck minus its commanders -- 98 for a partner pair,
    # not 99. Drawing from a library one card too large dilutes it with an
    # extra non-source and biases every figure the same way.
    deck_size = len(names)
    # top=None, then take the worst five from the AGGREGATE. Letting each
    # replicate pick its own top five would average different questions: the
    # fifth-worst line is not stable across seeds, so the mean of five rows
    # could mix a line measured three times with one measured once. The
    # candidate set itself is RNG-free -- it comes from the decklist -- so
    # every replicate returns the identical key set, and no extra work is
    # done: probability() is already called for every candidate before the
    # old top=5 slice threw most of them away.
    acc = {}
    for i, s in enumerate(split_budget(sims, reps)):
        for p, turn, mv, req, cards in worst_lines(
                names, scry, lands, accels, s, random.Random(seed + i),
                top=None, deck_size=deck_size):
            acc.setdefault((turn, mv, req), (cards, []))[1].append(p)
    rows = []
    for (turn, mv, req), (cards, ps) in acc.items():
        m, sp = mean_spread(ps)
        rows.append((m, turn, mv, req, cards, sp))
    # Sort on the first five fields only: that is the whole of the old
    # 5-tuple, so at reps=1 the ordering here is the ordering rows.sort()
    # produced before the spread was appended.
    rows.sort(key=lambda r: r[:5])
    rows = rows[:5]
    if lines is None:
        lines, seen = [], set()
        for p, turn, mv, req, cards, sp in rows:
            key = (mv, tuple(req))
            if key in seen:
                continue
            seen.add(key)
            lines.append((f"{cards[0]} T{turn}", mv,
                          "".join("{%s}" % x for x in req)))
        lines += commander_lines(cmdr, scry)
    res = replicate_playsim(lands, accels, deck_size, lines, trials, seed, reps)
    return {"verify": v, "lands": lands, "accels": accels,
            "rows": rows, "lines": lines, "sim": res,
            "sims": sims, "trials": trials, "seed": seed, "reps": reps}


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
