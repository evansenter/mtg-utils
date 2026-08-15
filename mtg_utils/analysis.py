"""Compute, no printing. The report_* wrappers only format what these return."""
import math
import random
import re

from mtg_utils.cards import (enters_tapped, front, front_name, has_land_back,
                             is_front_land, land_face)
from mtg_utils.castability import (at_least_in_draw, castable_faces,
                                   pips_from_cost, playsim_report, probability)
from mtg_utils.decklist import apply_swaps, as_cmdrs, flat
from mtg_utils.primer import parse_primer_links, unclosed_openers
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


def opening_hand_floor(lands, deck_size, hand=7):
    """How often the opening seven holds at most one land.

    `playsim` deals seven and never looks back, so every hand is kept --
    zero-land hands included. Real play mulligans, which makes every figure
    the play simulation reports a FLOOR rather than an estimate.

    This measures how big that floor is instead of leaving it to be
    inferred, and it is measured rather than simulated: the opening hand is
    a pure counting question, so it has an exact answer.

    Two reasons this is worth printing rather than describing. It is large --
    around one hand in seven on a 40-land deck. And it is DECK-DEPENDENT: a
    27-land list ships back nearly three times as many hands as a 40-land
    one, so the bias does not merely lower every number, it skews decks
    against each other. `calibrate` puts decks side by side in one table.

    "At most one land" is a deliberately crude keep rule, and the only one
    available without inventing a heuristic -- which is the failure
    KNOWN_ISSUES #13 records. Accelerants are not counted toward keepability
    on purpose: a hand of one land and a Sol Ring casts nothing on turn one.
    """
    return {"lands": lands, "hand": hand, "deck_size": deck_size,
            "p_none": 1.0 - at_least_in_draw(1, lands, hand, deck_size),
            "p_one_or_fewer": 1.0 - at_least_in_draw(2, lands, hand, deck_size)}


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
    # An MDFC back is a land you can play, so it counts toward keepability.
    floor = opening_hand_floor(v["lands"] + v["mdfc_land_backs"], deck_size)
    return {"verify": v, "lands": lands, "accels": accels,
            "rows": rows, "lines": lines, "sim": res, "floor": floor,
            "sims": sims, "trials": trials, "seed": seed, "reps": reps}


# Two-sided 95% Student-t multipliers by degrees of freedom. With three
# replicates the spread is itself estimated from three numbers, so the
# familiar 1.96 is far too tight -- the difference of two three-replicate
# means has df=4, which wants 2.78. Using 2.0 would call a comparison
# "MOVES" on noise noticeably often, and a false MOVES is the expensive
# direction: it sends someone to rebuild a manabase over nothing.
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
        7: 2.365, 8: 2.306, 10: 2.228, 15: 2.131, 20: 2.086, 30: 2.042}


def t95(df):
    """Two-sided 95% t multiplier for `df` degrees of freedom."""
    for k in sorted(_T95):
        if df <= k:
            return _T95[k]
    return 1.96


def compare_swap(cmdr, entries, scry, swaps, sims, trials, seed=17, reps=3):
    """Measure a named swap: the same deck before and after, as data.

    `variants` sweeps COUNTS. It could not answer "what does swapping these
    three checklands for these three filter lands do", which is the question
    nearly every time a manabase is questioned -- so it was being answered by
    regex substitution against the raw .txt, outside the package and with no
    assertions.

    Both sides run through analyse_mana at the same seed, and the lines are
    chosen from the BASE deck and passed to the swapped deck explicitly.
    Letting each side pick its own worst five would compare different
    questions and could show a "change" that is only a change of subject.

    Each row carries the error of the DIFFERENCE, not of either side: the two
    measurements are independent, so the noise on the delta is the two
    spreads added in quadrature. `beyond_noise` compares the delta against
    that noise times the 95% t multiplier for df = 2*(reps-1) -- not against
    a flat 2 sigma, because with three replicates the noise estimate is
    itself built from three numbers and a flat multiplier over-calls.

    At reps=1 there is no spread to test against and nothing is ever
    reported as moving: one replicate cannot establish that anything changed,
    and saying so is better than dividing by a zero error bar.
    """
    # A swap target the cache cannot resolve builds no land profile and no
    # accelerant profile, so it is modelled as a card that produces nothing.
    # That reads as a catastrophic result -- "this swap cost you 12 points" --
    # rather than as the typo it is. Checked here rather than in the CLI so
    # it is reachable without a decklist or a network call.
    missing = sorted({add for _cut, add in swaps if not scry.get(add.lower())})
    if missing:
        raise SystemExit(
            f"--swap: no Scryfall entry for {missing}. An unresolved swap "
            f"target would be modelled as producing no mana, which reads as a "
            f"catastrophic result rather than as a misspelling.")
    base = analyse_mana(cmdr, entries, scry, sims, trials, seed, reps=reps)
    after_entries = apply_swaps(cmdr, entries, swaps)
    after = analyse_mana(cmdr, after_entries, scry, sims, trials, seed,
                         lines=base["lines"], reps=reps)

    crit = t95(2 * (reps - 1)) if reps > 1 else None

    def row(label, before_t, after_t):
        b, sb = before_t
        a, sa = after_t
        noise = math.sqrt(sb ** 2 + sa ** 2)
        moved = False if crit is None else abs(a - b) > crit * noise
        return {"label": label, "before": b, "after": a, "delta": a - b,
                "noise": noise, "beyond_noise": moved}

    # Sources model, matched by (turn, mv, req) rather than by row position:
    # the table is sorted, so comparing positionally compares different cards.
    #
    # Scaled to percent here, because the play-simulation rows below are
    # already percentages and both end up in the same column of the same
    # report. Two adjacent numbers in different units is the bug this repo
    # already had once, with tapped-land counts against land counts.
    base_rows = {(t, mv, req): (p * 100, sp * 100)
                 for p, t, mv, req, _c, sp in base["rows"]}
    after_rows = {(t, mv, req): (p * 100, sp * 100)
                  for p, t, mv, req, _c, sp in after["rows"]}
    cards = {(t, mv, req): c for p, t, mv, req, c, sp in base["rows"]}
    sources = []
    for key in sorted(base_rows.keys() & after_rows.keys(),
                      key=lambda k: base_rows[k][0]):
        turn, mv, req = key
        label = f"T{turn} " + "".join("{%s}" % x for x in req)
        r = row(label, base_rows[key], after_rows[key])
        r["cards"] = cards[key]
        sources.append(r)

    play = []
    for label, mv, pipstr in base["lines"]:
        if label not in base["sim"]["play"]["lines"]:
            continue
        for side in ("play", "draw"):
            b, turn, sb = base["sim"][side]["lines"][label]
            a, _, sa = after["sim"][side]["lines"][label]
            play.append(dict(row(f"{label} (on {side})", (b, sb), (a, sa)),
                             side=side, turn=turn))
    return {"swaps": swaps, "base": base, "after": after,
            "entries_after": after_entries,
            "sources": sources, "play": play,
            # A key present on one side only means the swap changed which
            # spells exist, not just how well they cast. Reported, never
            # silently dropped.
            "sources_only_before": sorted(base_rows.keys() - after_rows.keys()),
            "sources_only_after": sorted(after_rows.keys() - base_rows.keys())}


def ceiling_audit(cmdr, entries, rows, capped, owned, scry, threshold=50.0,
                  sort="inclusion"):
    """Which cards above the inclusion bar for this commander are missing.

    Pure compute; report_ceiling only formats it.

    `sort` orders the reported rows; it does NOT select them. The bar stays on
    inclusion whichever way the table is sorted, because synergy is a
    difference of two inclusion rates and is at its noisiest exactly where
    inclusion is lowest -- a bar on synergy would promote fringe cards played
    in a handful of decks over the staples the audit exists to catch.

    Every name on both sides is reduced to its FRONT FACE before comparison.
    This is the whole reason the audit belongs in the package: run by hand it
    keyed the deck on the full DFC name while EDHREC returns front faces
    only, and reported a card as missing that was sitting in the list.
    edhtop16 has the opposite convention -- full "A // B" names -- so a
    comparison that handles only one of them is wrong against the other.

    `capped` is the list of EDHREC cardlists that came back at the display
    cap. It is carried through untouched: a card absent from a capped list is
    of UNKNOWN inclusion, not 0%, and nothing here may turn one into the
    other.
    """
    have = {front_name(n).lower() for n in list(entries) + as_cmdrs(cmdr)}
    missing = []
    for r in rows:
        if r["inclusion"] < threshold:
            continue
        key = front_name(r["name"]).lower()
        if key in have:
            continue
        card = scry.get(key) or scry.get(r["name"].lower())
        price = (card or {}).get("prices", {}).get("usd")
        missing.append(dict(r, owned=owned.get(key, 0),
                            price=float(price) if price else None,
                            type_line=(card or {}).get("type_line", "")))
    # A card with no synergy figure sorts LAST under --sort=synergy rather
    # than at zero. Unknown is not "no synergy": every --cedh row is unknown,
    # and floating them through the middle of the table on a 0.0 they were
    # never measured at is how the column would start lying.
    if sort == "synergy":
        missing.sort(key=lambda r: (r.get("synergy") is None,
                                    -(r.get("synergy") or 0.0), -r["inclusion"]))
    else:
        missing.sort(key=lambda r: -r["inclusion"])
    return {"missing": missing, "threshold": threshold, "capped": capped,
            "sort": sort,
            "considered": len(rows),
            "owned_count": sum(1 for m in missing if m["owned"] > 0),
            "buy_total": sum(m["price"] for m in missing
                             if m["price"] and not m["owned"])}


# Skeleton buckets are NOT report_own's buckets, and the two must not be
# "deduplicated" into one list. `own` groups for SHOPPING -- it splits
# Equipment out because that is how a buy list reads, and it skips basics
# because ManaBox does not track them. A skeleton groups for SLOT BUDGETING,
# where Instants and Sorceries are different decisions (interaction versus
# value) and basics are most of the manabase. Same words, different job.
SKELETON_TYPES = ("Land", "Creature", "Artifact", "Enchantment", "Instant",
                  "Sorcery", "Planeswalker", "Battle")

CURVE_TOP = 7          # everything at or above this is one "7+" bucket


def type_bucket(type_line):
    """First matching type on the FRONT face, in SKELETON_TYPES order.

    Front face only: an MDFC whose front is a spell is a spell slot, and its
    land back is already counted separately by verify. Order matters --
    'Artifact Creature' is a creature slot, because that is the slot you
    are budgeting when you write down "10 creatures".
    """
    front = (type_line or "").split("//")[0]
    for t in SKELETON_TYPES:
        if t in front:
            return t
    return "Other"


def deck_skeleton(cmdr, entries, scry):
    """The slot budget: 100 = commanders + lands + non-land, plus the curve.

    Deciding land count, non-land count and the per-category budget BEFORE
    selecting cards is what prevents repeated rebuilds, and nothing printed
    it -- so every skeleton was hand arithmetic. Hand arithmetic has already
    shipped a header block reading "24 lands plus 75 non-land" for a
    100-card deck: the commander was missing from the sum and nothing caught
    it.

    So the identity is ASSERTED here, not printed for a reader to check. An
    inconsistent total raises, and names the cards that did not land in any
    bucket -- which in practice means a name Scryfall could not resolve,
    since `verify` skips those and they then belong to no category at all.

    Roles are TYPE-LINE categories, deliberately. Functional roles -- ramp,
    draw, interaction -- are what a skeleton really wants, and they are not
    inferrable without a heuristic this repo would have to invent. The one
    functional count here is measured rather than guessed: accelerants come
    from build_accel_profiles, the same gate the mana models use.
    """
    cmdrs = as_cmdrs(cmdr)
    v = verify(cmdr, entries, scry)
    parts = len(cmdrs) + v["lands"] + v["nonland"]
    if parts != v["total"]:
        missing = [n for n, why in v["illegal"] if why == "NOT FOUND"]
        raise SystemExit(
            f"skeleton: {v['total']} cards but "
            f"{len(cmdrs)} commander(s) + {v['lands']} lands + "
            f"{v['nonland']} non-land = {parts}. "
            f"{len(missing)} card(s) resolved to nothing and are in no "
            f"category: {missing or 'none -- and that is the surprising part'}")

    curve, types = {}, {}
    for n, q in entries.items():
        c = scry.get(n.lower())
        if not c:
            continue
        types[type_bucket(c["type_line"])] = \
            types.get(type_bucket(c["type_line"]), 0) + q
        if is_front_land(c):
            continue
        mv = int(float(front(c, "cmc", 0) or 0))
        key = CURVE_TOP if mv >= CURVE_TOP else mv
        curve[key] = curve.get(key, 0) + q

    names = flat(cmdr, entries)[len(cmdrs):]
    accels = [a for a in build_accel_profiles(names, scry)
              if not a.get("restricted")]
    return {"commanders": len(cmdrs), "lands": v["lands"],
            "mdfc_land_backs": v["mdfc_land_backs"], "nonland": v["nonland"],
            "total": v["total"], "avg_mv": v["avg_mv"],
            "curve": curve, "types": types, "accelerants": len(accels),
            "game_changers": len(v["game_changers"])}


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


def primer_audit(text, cmdr, entries, scry):
    """Every `[[Card]]` in a primer, checked against Scryfall and the decklist.

    Pure compute; report_primer only formats it.

    Three findings, in the order they cost you something:

    `wrapped`   -- the link does not render at all. Nothing downstream sees a
                   card here, so this is the only finding that is invisible in
                   the rendered page rather than merely wrong in it.
    `not_found` -- Scryfall does not know the name. A typo in a link renders as
                   a dead link, and the primer still reads as if the card is in
                   the deck.
    `not_in_deck` -- a real card that is no longer in the list. THE failure a
                   primer accumulates on its own: editing a decklist touches
                   nothing in the prose that argues for the cards.

    A wrapped link is NOT also reported as not-found or not-in-deck even when
    its normalised name would qualify. One broken link is one problem, and
    listing it three times buries the other two.
    """
    links = parse_primer_links(text)
    have = {front_name(n).lower() for n in list(entries) + as_cmdrs(cmdr)}
    wrapped, not_found, not_in_deck = [], [], []
    for l in links:
        key = front_name(l["name"]).lower()
        if l["wrapped"]:
            wrapped.append(l)
            continue
        if not scry.get(key) and not scry.get(l["name"].lower()):
            not_found.append(l)
            continue
        if key not in have:
            not_in_deck.append(l)
    return {"links": links,
            "distinct": len({front_name(l["name"]).lower() for l in links}),
            "wrapped": wrapped,
            "unclosed": unclosed_openers(text, links),
            "not_found": not_found,
            "not_in_deck": not_in_deck,
            "ok": not (wrapped or not_found or not_in_deck
                       or unclosed_openers(text, links))}
