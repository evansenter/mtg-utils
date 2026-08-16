"""Mana printers: the two models, the count sweep and the named swap.

Everything here formats a Monte Carlo measurement, so everything here prints
a figure with its noise beside it. analysis.py does the measuring.
"""
from mtg_utils.analysis import analyse_mana, commander_lines, compare_swap, replicate_playsim
from mtg_utils.castability import pips_from_cost
from mtg_utils.decklist import as_cmdrs, flat
from mtg_utils.profiles import (build_accel_profiles, build_land_profiles,
                                build_ritual_profiles)


def _burst_note(rituals):
    """'dark ritual +2' -- the rituals counted, with their NETS.

    Shared by the two tables that mention rituals. What they say ABOUT the
    burst legitimately differs -- report_mana says which model uses it,
    report_variants says it is held constant across the sweep -- but the fact
    itself is one fact, and rendering it twice is how the two drift into
    quoting different nets for the same deck.
    """
    return ", ".join("%s +%d" % (r["name"], r["amount"]) for r in rituals)


def _reps(n):
    """'3 reps' / '1 rep'. The provenance line is read by people copying a
    figure into a primer, and '1 reps' reads as a bug in the tool."""
    return f"{n} rep" + ("" if n == 1 else "s")


def report_mana(cmdr, entries, scry, sims, trials, seed=17, lines=None, reps=3):
    a = analyse_mana(cmdr, entries, scry, sims, trials, seed, lines, reps)
    # Everything is unpacked HERE, before the play-simulation loop below
    # rebinds `a` to a percentage. Reading a["floor"] after that loop gets a
    # float and a TypeError several lines from the cause.
    v, accels, rows, lines, res, floor = (a["verify"], a["accels"], a["rows"],
                                          a["lines"], a["sim"], a["floor"])
    rituals = a["rituals"]

    print(f"\n=== MANA BASE ({v['lands']} front-face lands"
          f" + {v['mdfc_land_backs']} MDFC land-backs, "
          f"{v['truly_tapped_copies']} truly tapped) ===")
    for n, m in v["conditional_tapped"]:
        print(f"  conditional, not counted: {n}   [{m}]")
    for n in v["truly_tapped"]:
        print(f"  TRULY TAPPED: {n}")
    restricted = [a["name"] for a in accels if a.get("restricted")]
    print(f"  accelerants counted: {len([a for a in accels if not a.get('restricted')])}"
          f"  (restricted, excluded: {', '.join(restricted) if restricted else 'none'})")
    # Printed on its own line, and never added to the accelerant count above.
    # A ritual is not a source: it is one turn of mana, it appears in the play
    # simulation only, and the sources model below does not see it. Saying so
    # here is what stops the two tables in this report reading as a
    # contradiction on a deck that runs one.
    #
    # Printed only when there ARE rituals, unlike the "restricted ... none"
    # note above it. That is not a formatting preference: a deck with no
    # ritual then produces output byte-identical to before rituals existed, so
    # the ritual-free fixtures stay a live control on this gate. If the
    # colourless snapshot ever moves, the gate is admitting something it
    # should not, and the golden suite says so instead of showing a diff that
    # is all header line.
    if rituals:
        print(f"  rituals counted, play simulation only (net burst): "
              f"{_burst_note(rituals)}")

    # Every figure carries the wobble of its own reported value. Without it a
    # 0.4-point gap between two variants reads exactly like a 4-point one, and
    # deciding which of those is real was being done by hand, outside the tool.
    print(f"\n--- sources model (colour), worst lines "
          f"({sims} sims over {_reps(reps)}, seed {seed}) ---")
    for p, turn, mv, req, cards, sp in rows:
        pips = "".join("{%s}" % x for x in req)
        print(f"  T{turn} {pips:12} {p*100:5.1f}% ±{sp*100:3.1f}"
              f"   {', '.join(cards[:3])}")

    print(f"\n--- play simulation, {trials} trials over {_reps(reps)},"
          f" seed {seed} ---")
    print(f"  {'line':44s} {'on play':>11} {'on draw':>11}"
          f" {'baseline(any N on TN)':>28}")
    for label, mv, pipstr in lines:
        if label not in res["play"]["lines"]:
            continue
        a, turn, sa = res["play"]["lines"][label]
        b, _, sb = res["draw"]["lines"][label]
        g1, s1 = res["play"]["generic"][turn]
        g2, s2 = res["draw"]["generic"][turn]
        print(f"  {label:44s} {a:6.1f}±{sa:3.1f}% {b:6.1f}±{sb:3.1f}%"
              f"   {g1:6.1f}±{s1:3.1f}% / {g2:.1f}±{s2:.1f}%")
    print("\n  Diagnosis: a line CLOSE to its baseline is a QUANTITY problem "
          "(no land swap will help).\n  A line FAR BELOW its baseline is a "
          "COLOUR problem (a filter land for that pip is the answer).")
    print("  A gap smaller than the two ± beside it is noise, not a finding.")

    # No mulligan is modelled, so every figure above is a floor. Said with a
    # measured size rather than as a caveat: the share is large, and it is
    # deck-dependent, so it skews decks against each other as well as
    # lowering each one. Exact rather than simulated -- the opening hand is a
    # counting question, and it is NOT a castability figure.
    print("\n  No mulligan is modelled: every opening seven is kept, so the "
          "figures above are FLOORS.")
    print(f"  {floor['p_one_or_fewer']*100:.1f}% of opening sevens hold at most "
          f"one land ({floor['p_none']*100:.1f}% hold none), off"
          f" {floor['lands']} lands in {floor['deck_size']}.")
    print("  Those hands are kept here and shipped back in real play. The "
          "share moves with\n  land count, so it skews deck-to-deck "
          "comparison and not just the level.")
    return res


def report_variants(cmdr, entries, scry, land_deltas, accel_deltas, trials,
                    seed=17, reps=3):
    """Sweep land count and accelerant count. Slow; opt-in."""
    names = flat(cmdr, entries)[len(as_cmdrs(cmdr)):]
    base_lands = build_land_profiles(names, scry)
    accels = build_accel_profiles(names, scry)
    accels = [a for a in accels if not a.get("restricted")]
    # Held CONSTANT across the sweep, and not counted in the "N accel" label:
    # --accel varies how many accelerants the deck runs, and a ritual is not
    # one. Folding them into that count would make the config column disagree
    # with what the sweep actually varied.
    rituals = build_ritual_profiles(names, scry)
    basic = next((p for p in base_lands if not p["tapped"] and p["colours"]), None)
    if basic is None and any(d > 0 for d in land_deltas):
        # dict(None) raises TypeError several frames later, which reads as a
        # crash rather than as "this deck has nothing to clone". Guards fail
        # loudly and by name here.
        raise SystemExit(
            "variants: cannot add lands to a deck with no untapped "
            "colour-producing land to copy. Drop the positive entries from "
            "--lands, or add one such land to the list first.")
    generic_rock = {"name": "generic rock", "kind": "accel", "colours": frozenset(),
                    "filter": None, "omni": None, "amount": 1, "cost": 2,
                    "tapped": False, "cond_tap": None, "restricted": False,
                    "creature": False, "mdfc": False}
    _cl = commander_lines(cmdr, scry)
    _, cmv, _cpips = _cl[0]
    creq = pips_from_cost(_cpips)
    print(f"\n=== VARIANTS SWEEP ({trials} trials over {_reps(reps)}, seed {seed})"
          f" — commander line and generic baseline ===")
    # Named here for the same reason report_mana names it, and it matters more
    # here: this table exists to attribute a movement to the thing that was
    # varied, and the burst is in EVERY row while the config column says
    # nothing about it. Without this line, someone diffing a stored sweep
    # against a fresh one sees identical configs and moved numbers.
    if rituals:
        print(f"  every row includes the ritual burst, held constant and not in "
              f"the accel count: {_burst_note(rituals)}")
    print(f"  {'config':26s} {'cmdr on curve':>20} {'any N on turn N':>22}")
    for dl in land_deltas:
        for da in accel_deltas:
            if dl >= 0:
                lands = base_lands + [dict(basic) for _ in range(dl)]
            else:
                lands = list(base_lands)
                for _ in range(-dl):
                    drop = next((i for i, p in enumerate(lands)
                                 if not p["tapped"] and not p["filter"]
                                 and p.get("amount", 1) == 1
                                 and len(p["colours"]) == 1), None)
                    if drop is None:
                        break
                    lands.pop(drop)
            acc = accels + [dict(generic_rock) for _ in range(da)]
            # Comparing configs is the entire purpose of this table, so a
            # figure without its wobble beside it cannot do the job: the
            # question is always whether one row differs from another.
            r = replicate_playsim(lands, acc, 99,
                                  [("cmdr", cmv, "".join(f"{{{x}}}" for x in creq))],
                                  trials, seed, reps, rituals=rituals)
            a, turn, sa = r["play"]["lines"]["cmdr"]
            b, _, sb = r["draw"]["lines"]["cmdr"]
            g1, s1 = r["play"]["generic"][turn]
            g2, s2 = r["draw"]["generic"][turn]
            print(f"  {len(lands)} lands, {len(acc)} accel"
                  f"{'':<7} {a:6.1f}±{sa:3.1f} / {b:5.1f}±{sb:3.1f}"
                  f" {g1:8.1f}±{s1:3.1f} / {g2:5.1f}±{s2:3.1f}")


def _swap_row(r):
    """One before/after line. 44 wide to match report_mana's label column --
    'Thrasios, Triton Hero on curve (on play)' is 40 characters and a
    narrower field pushes every number on that row out of its column."""
    verdict = "MOVES" if r["beyond_noise"] else "within noise"
    return (f"  {r['label']:44s} {r['before']:6.1f}% -> {r['after']:6.1f}%"
            f"   {r['delta']:+6.1f} ±{r['noise']:4.1f}   {verdict}")


def report_swap(cmdr, entries, scry, swaps, sims, trials, seed=17, reps=3):
    """Print a named swap measured before and after. compare_swap computes it."""
    c = compare_swap(cmdr, entries, scry, swaps, sims, trials, seed, reps)
    print(f"\n=== NAMED SWAP ({trials} trials over {_reps(reps)}, seed {seed}) ===")
    for cut, add in swaps:
        print(f"  cut {cut}  ->  add {add}")
    # The count sweep answers a different question and is not run. Said out
    # loud: a silently skipped sweep reads as a sweep that found nothing.
    print("  (count sweep not run -- --swap measures a named swap, not a count)")

    print("\n--- sources model (colour): before -> after ---")
    for r in c["sources"]:
        print(_swap_row(r) + f"   {', '.join(r['cards'][:2])}")
    for key in c["sources_only_before"]:
        print(f"  line only in the BASE deck, not compared: {key}")
    for key in c["sources_only_after"]:
        print(f"  line only in the SWAPPED deck, not compared: {key}")

    print("\n--- play simulation: before -> after ---")
    for r in c["play"]:
        print(_swap_row(r))

    rows = c["sources"] + c["play"]
    moved = [r for r in rows if r["beyond_noise"]]
    if moved:
        print(f"\n  {len(moved)} of {len(rows)} lines moved beyond their noise "
              f"at 95%.")
        # Each row is its own 95% test, so about one row in twenty reads MOVES
        # on noise alone. A single MOVES in a long table is not a finding; a
        # cluster pointing the same way is.
        print(f"  Each line is a separate 95% test, so roughly "
              f"{len(rows) / 20:.0f} of {len(rows)} will read MOVES by chance.")
    else:
        # This is a real answer, not an absence of one -- a swap that changes
        # nothing because the deck has no unmet pip is exactly the finding
        # that used to take an afternoon of regex substitution to reach.
        print("\n  NOTHING MOVED beyond its noise. On this deck the swap is "
              "not\n  measurable -- which is a result, not a failure to "
              "measure.")
    return c
