"""Printers. These format what analysis.py computed; they do not compute."""
import random
import time
from collections import Counter, defaultdict

from mtg_utils.analysis import (analyse_mana, ceiling_audit, collapse_temps,
                                commander_lines, compare_swap, deck_base_name,
                                replicate_playsim, verify, worst_lines)
from mtg_utils.castability import pips_from_cost, playsim_report
from mtg_utils.decklist import as_cmdrs, diff_multiset, flat
from mtg_utils.profiles import build_accel_profiles, build_land_profiles
from mtg_utils.roster import (ANY_COLOUR, PAIR_CYCLES, TRIPLE_CYCLES, WUBRG,
                              identity_pairs, roster_names, roster_status)
from mtg_utils.sources.collection import load_collection
from mtg_utils.sources.edhrec import (PAGE_CAP, edhrec_fetch, edhrec_slug,
                                      parse_commander_page)
from mtg_utils.sources.edhtop16 import (MIN_ENTRIES, edhtop16_commander_name,
                                        edhtop16_fetch, parse_edhtop16)
from mtg_utils.sources.moxfield import moxfield_deck, moxfield_user_decks
from mtg_utils.sources.scryfall import scry_fetch
from mtg_utils.sources.spellbook import spellbook

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
                                  trials, seed, reps)
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


def report_ceiling(cmdr, entries, scry, cache=None, rec_cache=None, cedh=False,
                   threshold=50.0, sort="inclusion"):
    """Collection-ceiling audit: what is above the bar and not in the list.

    NETWORK unless both caches already hold what it needs, following the
    report_calibrate precedent. Both ranking sources are live endpoints and
    the suite is offline, so the tests drive the pure functions and frozen
    caches rather than the network.

    Takes the Scryfall cache path as well as the ranking cache because the
    interesting cards are by definition NOT in the decklist -- their prices
    and type lines were never fetched. report_roster does the same for the
    roster cycles it walks.
    """
    cmdrs = as_cmdrs(cmdr)
    if cedh:
        name = edhtop16_commander_name(cmdrs)
        data = edhtop16_fetch(name, rec_cache)
        if data is None:
            raise SystemExit(f"edhtop16: no response for {name!r}")
        rows, n_entries = parse_edhtop16(data)
        capped = []
        print(f"\n=== CEILING vs edhtop16: {name} ===")
        # The entry count sits beside every percentage, never behind it. At
        # four entries every card is 25/50/75/100% and the table would read
        # like a strong signal.
        print(f"  {n_entries} tournament entries counted")
        if n_entries < MIN_ENTRIES:
            print(f"  FEWER THAN {MIN_ENTRIES} ENTRIES -- no percentage is "
                  f"quoted from this sample.")
            print("  Run again when the commander has more results, or drop "
                  "--cedh for EDHREC.")
            return None
    else:
        slug = edhrec_slug(cmdrs)
        data = edhrec_fetch(slug, rec_cache)
        if data is None:
            raise SystemExit(
                f"EDHREC: no page for slug {slug!r}. Note apostrophes are "
                f"DROPPED, not hyphenated -- a wrong slug 403s rather than "
                f"404s, so this can read as a block.")
        rows, capped = parse_commander_page(data)
        n_entries = None
        print(f"\n=== CEILING vs EDHREC: {slug} ===")
        if not rows:
            # Zero ranked cards is a fetch problem, never a finding. Left to
            # fall through, the audit below reports nothing missing and the
            # deck reads as needing no work at all -- the most reassuring
            # possible output from a page that told us nothing.
            raise SystemExit(
                f"EDHREC page for {slug!r} ranked no cards at all. That is a "
                f"fetch or slug problem, not a deck with nothing to improve "
                f"-- refusing to report an all-clear from an empty page.")

    # The cards this command is about are the ones NOT in the deck, so their
    # Scryfall records were never fetched. Only the above-bar names are
    # looked up: fetching all ~250 ranked cards to price the handful above
    # the bar is a lot of round trips for rows nobody prints.
    have = {n.split(" // ")[0].strip().lower()
            for n in list(entries) + as_cmdrs(cmdr)}
    want = [r["name"] for r in rows
            if r["inclusion"] >= threshold
            and r["name"].split(" // ")[0].strip().lower() not in have]
    if want:
        scry, nf = scry_fetch(want, cache)
        if nf:
            print("  SCRYFALL NOT FOUND (ranked card, front-face names "
                  "only!):", nf)

    a = ceiling_audit(cmdr, entries, rows, capped, load_collection(), scry,
                      threshold, sort)
    print(f"  {a['considered']} cards ranked; bar is {threshold:.0f}% inclusion"
          f", sorted by {sort}")
    print(f"\n  {'card':34s} {'incl':>7} {'syn':>7} {'n/of':>13} {'own':>4}  price")
    for m in a["missing"]:
        n_of = f"{m['num_decks']}/{m['potential_decks']}"
        price = f"${m['price']:.2f}" if m["price"] else "-"
        # None prints as "-", not as 0.0. See parse_commander_page: zero is a
        # measured value here, so the two must not share a rendering.
        syn = "-" if m.get("synergy") is None else f"{m['synergy']:+.3f}"
        print(f"  {m['name'][:34]:34s} {m['inclusion']:6.1f}% {syn:>7} {n_of:>13} "
              f"{m['owned']:>4}  {price}")
    if not a["missing"]:
        print("  (nothing above the bar is missing from this list)")
    print(f"\n  {len(a['missing'])} missing above the bar, "
          f"{a['owned_count']} already owned; "
          f"buy total ${a['buy_total']:.2f}")
    # A capped list is the difference between "this card is unplayed" and
    # "this page did not tell us". Never printed as 0%.
    for header in capped:
        print(f"  NOTE: '{header}' came back at the {PAGE_CAP}-card display "
              f"cutoff -- cards below that cutoff are of UNKNOWN inclusion, "
              f"not 0%.")
    return a


def report_own(cmdr, entries, scry):
    owned = load_collection()
    buckets = defaultdict(list)
    tot = 0.0
    for n in as_cmdrs(cmdr) + list(entries):
        if owned.get(n.lower(), 0) > 0:
            continue
        c = scry.get(n.lower())
        if not c:
            continue
        tl = c["type_line"]
        if "Basic Land" in tl:
            continue          # basics are NOT tracked in ManaBox; never a buy line
        if "Land" in tl.split("//")[0]:
            b = "Lands"
        elif "Equipment" in tl:
            b = "Equipment"
        elif "Creature" in tl.split("//")[0]:
            b = "Creatures"
        elif "Artifact" in tl:
            b = "Artifacts"
        elif "Enchantment" in tl:
            b = "Enchantments"
        else:
            b = "Instants / Sorceries"
        price = c.get("prices", {}).get("usd")
        buckets[b].append((n, price, c.get("edhrec_rank")))
        if price:
            tot += float(price)
    print("\n=== BUY LIST (absent from ManaBox_Collection.csv) ===")
    for b in ["Creatures", "Equipment", "Artifacts", "Enchantments",
              "Instants / Sorceries", "Lands"]:
        if b not in buckets:
            continue
        print(f"\n{b} ({len(buckets[b])})")
        for n, p, rk in sorted(buckets[b]):
            rks = f"EDHREC #{rk}" if rk else ""
            print(f"  (BUY) {n:34s} ${p if p else 'n/a':>7}  {rks}")
    print(f"\n  total listed USD (nulls excluded): ${tot:,.2f}")
    print("  Null usd (Reserved List / promo): re-query !\"Name\" with order=eur&unique=prints")


def report_contention(cmdr, entries, other_ids):
    owned = load_collection()
    use = {}
    for pid in other_ids:
        name, cmdrs, main = moxfield_deck(pid)
        use[name or pid] = set(k.lower() for k in list(main) + cmdrs)
        time.sleep(0.4)
    dropped = sorted(set(use) - set(collapse_temps(use)))
    use = collapse_temps(use)
    if dropped:
        print(f"\n  (collapsed into their main lists, not counted as separate "
              f"physical decks: {', '.join(dropped)})")
    print("\n=== CONTENTION (owned copies vs physical decks wanting the card) ===")
    hit = False
    for n in as_cmdrs(cmdr) + list(entries):
        o = owned.get(n.lower(), 0)
        if o == 0:
            continue
        others = [l for l, s in use.items() if n.lower() in s]
        if len(others) + 1 > o:
            hit = True
            print(f"  {n:30s} owned {o} | also in: {', '.join(sorted(others))}")
    if not hit:
        print("  none — every owned card here has enough copies")
    print("  (Contention is an OUTPUT. It never decides a slot.)")


def report_combos(cmdr, entries):
    res = spellbook(cmdr, entries)
    inc = res.get("included", [])
    almost = res.get("almostIncluded", [])
    deck = set(n.lower() for n in flat(cmdr, entries))
    print(f"\n=== COMMANDER SPELLBOOK ({time.strftime('%Y-%m-%d')}) ===")
    print(f"  in-deck combos: {len(inc)}")
    for v in inc:
        print("   *", " + ".join(u["card"]["name"] for u in v.get("uses", [])),
              "->", ", ".join(f["feature"]["name"] for f in v.get("produces", [])))
    print(f"  one card away: {len(almost)}")
    grp = defaultdict(list)
    for v in almost:
        us = [u["card"]["name"] for u in v.get("uses", [])]
        tmpl = [t["template"]["name"] for t in v.get("requires", [])]
        have = [u for u in us if u.lower() in deck]
        miss = [u for u in us if u.lower() not in deck]
        for h in have:
            grp[h].append((miss, len(us) + len(tmpl)))
    print("  grouped by the piece already in the deck:")
    for k, v in sorted(grp.items(), key=lambda x: -len(x[1])):
        twos = sorted({m[0] for m, sz in v if sz == 2 and len(m) == 1})
        print(f"    {k}: {len(v)}" + (f"   two-card: {', '.join(twos)}" if twos else ""))
    print("  Spellbook is a CANDIDATE GENERATOR. Verify every piece count against")
    print("  oracle text before believing it (otherPrerequisites is often empty).")


def report_diff(cmdr, entries, deck_id):
    """Section 3: changes are not real until imported, and a delta must be
    re-based on a fresh fetch before it is applied. This is that check."""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    name, live_cmdrs, live_main = moxfield_deck(deck_id)
    ol, ov, cc = diff_multiset(cmdr, entries, live_cmdrs, live_main)
    print(f"\n=== DIFF vs LIVE  (deck {deck_id}, '{name}', fetched {stamp}) ===")
    if cc:
        print(f"  COMMANDER DIFFERS: local {cc[0]} | live {cc[1]}")
    lt = len(as_cmdrs(cmdr)) + sum(entries.values())
    vt = len(live_cmdrs) + sum(live_main.values())
    print(f"  local {lt} cards | live {vt} cards")
    if not ol and not ov and not cc:
        print("  IDENTICAL -- the live list already matches this file.")
        return True
    for n, c in ov:
        print(f"  -{c} {n}      (in live, not in file)")
    for n, c in ol:
        print(f"  +{c} {n}      (in file, not in live)")
    print("  Paste as a delta only after confirming this is the base you built on.")
    return False


def report_calibrate(deck_ids, cache_path, sims, trials, user=None):
    """Regenerate the whole calibration table from LIVE decks in one pass.

    The table is a set of dated measurements, not a fact about a deck. It is
    wrong the moment a list changes, the moment the model changes, and it
    carries Monte Carlo noise besides. Regenerate it; never quote a stored row.
    """
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not deck_ids:
        deck_ids = [i for i, _n in moxfield_user_decks(user or "evansenter")]
    rows = []
    for did in deck_ids:
        try:
            name, cmdrs, main = moxfield_deck(did)
        except Exception as e:
            rows.append((did, f"FETCH FAILED: {e}", None)); continue
        if not cmdrs:
            continue
        cmdr = cmdrs
        entries = Counter(main)
        scry, nf = scry_fetch(flat(cmdr, entries), cache_path)
        if nf:
            print(f"  [{name}] Scryfall not found: {nf}")
        v = verify(cmdr, entries, scry)
        names = flat(cmdr, entries)[len(as_cmdrs(cmdr)):]
        lands = build_land_profiles(names, scry)
        accels = build_accel_profiles(names, scry)
        deck_size = len(names)          # the library: deck minus commanders
        srows = worst_lines(names, scry, lands, accels, sims,
                            random.Random(17), top=1, deck_size=deck_size)
        lines = []
        for pr, turn, mv, req, cards in srows:
            lines.append((f"{cards[0]} T{turn}", mv,
                          "".join("{%s}" % x for x in req)))
        lines += commander_lines(cmdr, scry)
        res = playsim_report(lands, accels, deck_size, lines, trials, random.Random(17))

        worst = None
        for label, mv, pipstr in lines:
            if label not in res["play"]["lines"]:
                continue
            a, turn = res["play"]["lines"][label]
            g = res["play"]["generic"][turn]
            d = a - g
            if worst is None or a < worst[1]:
                worst = (label, a, res["draw"]["lines"][label][0], d,
                         "quantity" if d > -3.0 else "COLOUR")
        rows.append((name, v, worst))
        time.sleep(0.3)

    print(f"\n=== CALIBRATION (regenerated {stamp}) ===")
    print("  Monte Carlo: sources model %d sims, play sim %d trials, seed 17."
          % (sims, trials))
    print(f"  {'deck':34s} {'lands':>5} {'tap':>4} {'GC':>3}  worst line "
          "(on play / on draw, delta vs baseline)")
    for r in rows:
        if r[2] is None and not isinstance(r[1], dict):
            print(f"  {r[0][:34]:34s} {r[1]}")
            continue
        name, v, worst = r
        mb = f"{v['lands']}" + (f"+{v['mdfc_land_backs']}" if v["mdfc_land_backs"] else "")
        if worst is None:
            print(f"  {name[:34]:34s} {mb:>5} {len(v['truly_tapped']):>4} "
                  f"{len(v['game_changers']):>3}  (no coloured line)")
            continue
        label, a, b, d, diag = worst
        print(f"  {name[:34]:34s} {mb:>5} {len(v['truly_tapped']):>4} "
              f"{len(v['game_changers']):>3}  {label[:38]} — "
              f"{a:.1f}% / {b:.1f}%, {d:+.1f} ({diag})")
    print("\n  A line within ~3 points of its baseline is a QUANTITY problem and "
          "no land\n  swap will move it. Further below is a COLOUR problem and a "
          "filter land for\n  that pip is the answer. These rows are dated "
          "measurements: re-run, never quote.")
    return rows


def report_roster(cmdr, entries, scry, cache_path=None):
    ci = set()
    for cn in as_cmdrs(cmdr):
        if scry.get(cn.lower()):
            ci |= set(scry[cn.lower()]["color_identity"])
    ident = "".join(c for c in WUBRG if c in ci)
    deck_names = {n.lower() for n in entries} | {c.lower() for c in as_cmdrs(cmdr)}
    owned = load_collection()
    names = roster_names(ident)
    scry2, nf = scry_fetch(names, cache_path)
    scry2.update(scry)

    print(f"\n=== ROSTER WALK: {' + '.join(as_cmdrs(cmdr))} ({ident}) ===")
    if nf:
        print(f"  *** ROSTER NAME NOT ON SCRYFALL: {nf} ***")
    bad = [n for n in names
           if scry2.get(n.lower())
           and set(scry2[n.lower()]["color_identity"]) - set(ident)]
    if bad:
        print(f"  *** OFF-IDENTITY, ILLEGAL HERE: {bad} ***")

    def price(n):
        c = scry2.get(n.lower()) or {}
        p = (c.get("prices") or {}).get("usd")
        return f"${p}" if p else "-"

    empty = []
    if not identity_pairs(ident):
        # Section 6: in a mono-colour identity the two-colour cycles are
        # ILLEGAL, not merely unnecessary (Sunbaked Canyon is RW, every filter
        # land is two-colour). Say so; do not silently omit the rows.
        print(f"  {len(PAIR_CYCLES)} two-colour cycles "
              f"({', '.join(s for s, _ in PAIR_CYCLES)}) are off-identity "
              f"and ILLEGAL in {ident} -- no pair rows to walk.")
        print("  Fetchlands and any-colour painlands are legal here and "
              "strictly worse than a basic without shuffle payoffs: "
              "walked and skipped.")
    for pk in identity_pairs(ident):
        print(f"\n  --- {pk} ---")
        for slot, table in PAIR_CYCLES:
            name = table.get(pk)
            if not name:
                print(f"  {slot:18s} {'(no such card)':30s}")
                continue
            st = roster_status(name, deck_names, owned)
            extra = "" if st == "IN" else f"   {price(name)}"
            print(f"  {slot:18s} {name:30s} {st}{extra}")
            if st != "IN" and slot in ("ABUR dual", "Shockland", "Fetchland",
                                       "Filter land", "Painland",
                                       "Battlebond land", "Horizon land"):
                empty.append((pk, slot, name, st))

    print("\n  --- off-pair fetchlands (reach one colour of the identity) ---")
    for pk, name in PAIR_CYCLES[2][1].items():
        if set(pk) & set(ident) and not set(pk) <= set(ident):
            st = roster_status(name, deck_names, owned)
            print(f"  {pk:18s} {name:30s} {st}"
                  + ("" if st == "IN" else f"   {price(name)}"))

    if ident in TRIPLE_CYCLES:
        print("\n  --- three-colour (tapped; only if the rider is real) ---")
        for name in TRIPLE_CYCLES[ident]:
            st = roster_status(name, deck_names, owned)
            print(f"  {'Triome/tri-land':18s} {name:30s} {st}"
                  + ("" if st == "IN" else f"   {price(name)}"))

    print("\n  --- identity-independent ---")
    for slot, name in ANY_COLOUR:
        st = roster_status(name, deck_names, owned)
        print(f"  {slot:18s} {name:30s} {st}"
              + ("" if st == "IN" else f"   {price(name)}"))

    print(f"\n  PREMIUM SLOTS NOT IN THE LIST: {len(empty)}")
    for pk, slot, name, st in empty:
        print(f"    {pk} {slot:18s} {name:30s} {st}")
    print("  Ownership routes the purchase; it never decides the slot.")
    return empty
