"""Printers. These format what analysis.py computed; they do not compute."""
import random
import time
from collections import Counter, defaultdict

from mtg_utils.analysis import (analyse_mana, collapse_temps, commander_lines,
                                deck_base_name, verify, worst_lines)
from mtg_utils.castability import pips_from_cost, playsim_report
from mtg_utils.decklist import as_cmdrs, diff_multiset, flat
from mtg_utils.profiles import build_accel_profiles, build_land_profiles
from mtg_utils.roster import (ANY_COLOUR, PAIR_CYCLES, TRIPLE_CYCLES, WUBRG,
                              identity_pairs, roster_names, roster_status)
from mtg_utils.sources.collection import load_collection
from mtg_utils.sources.moxfield import moxfield_deck, moxfield_user_decks
from mtg_utils.sources.scryfall import scry_fetch
from mtg_utils.sources.spellbook import spellbook

def report_mana(cmdr, entries, scry, sims, trials, seed=17, lines=None):
    a = analyse_mana(cmdr, entries, scry, sims, trials, seed, lines)
    v, accels, rows, lines, res = (a["verify"], a["accels"], a["rows"],
                                   a["lines"], a["sim"])

    print(f"\n=== MANA BASE ({v['lands']} front-face lands"
          f" + {v['mdfc_land_backs']} MDFC land-backs, "
          f"{len(v['truly_tapped'])} truly tapped) ===")
    for n, m in v["conditional_tapped"]:
        print(f"  conditional, not counted: {n}   [{m}]")
    for n in v["truly_tapped"]:
        print(f"  TRULY TAPPED: {n}")
    restricted = [a["name"] for a in accels if a.get("restricted")]
    print(f"  accelerants counted: {len([a for a in accels if not a.get('restricted')])}"
          f"  (restricted, excluded: {', '.join(restricted) if restricted else 'none'})")

    print("\n--- sources model (colour), worst lines ---")
    for p, turn, mv, req, cards in rows:
        pips = "".join("{%s}" % x for x in req)
        print(f"  T{turn} {pips:12} {p*100:5.1f}%   {', '.join(cards[:3])}")

    print(f"\n--- play simulation, {trials} trials ---")
    print(f"  {'line':44s} {'on play':>9} {'on draw':>9} {'baseline(any N on TN)':>22}")
    for label, mv, pipstr in lines:
        if label not in res["play"]["lines"]:
            continue
        a, turn = res["play"]["lines"][label]
        b, _ = res["draw"]["lines"][label]
        g1 = res["play"]["generic"][turn]
        g2 = res["draw"]["generic"][turn]
        print(f"  {label:44s} {a:8.1f}% {b:8.1f}%   {g1:7.1f}% / {g2:.1f}%")
    print("\n  Diagnosis: a line CLOSE to its baseline is a QUANTITY problem "
          "(no land swap will help).\n  A line FAR BELOW its baseline is a "
          "COLOUR problem (a filter land for that pip is the answer).")
    return res


def report_variants(cmdr, entries, scry, land_deltas, accel_deltas, trials, seed=17):
    """Sweep land count and accelerant count. Slow; opt-in."""
    names = flat(cmdr, entries)[len(as_cmdrs(cmdr)):]
    base_lands = build_land_profiles(names, scry)
    accels = build_accel_profiles(names, scry)
    accels = [a for a in accels if not a.get("restricted")]
    basic = next((p for p in base_lands if not p["tapped"] and p["colours"]), None)
    generic_rock = {"name": "generic rock", "kind": "accel", "colours": frozenset(),
                    "filter": None, "omni": None, "amount": 1, "cost": 2,
                    "tapped": False, "cond_tap": None, "restricted": False,
                    "creature": False, "mdfc": False}
    _cl = commander_lines(cmdr, scry)
    _, cmv, _cpips = _cl[0]
    creq = pips_from_cost(_cpips)
    print(f"\n=== VARIANTS SWEEP ({trials} trials) — commander line and generic baseline ===")
    print(f"  {'config':26s} {'cmdr on curve':>16} {'any N on turn N':>18}")
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
            rng = random.Random(seed)
            r = playsim_report(lands, acc, 99,
                               [("cmdr", cmv, "".join(f"{{{x}}}" for x in creq))],
                               trials, rng)
            a, turn = r["play"]["lines"]["cmdr"]
            b, _ = r["draw"]["lines"]["cmdr"]
            g1, g2 = r["play"]["generic"][turn], r["draw"]["generic"][turn]
            print(f"  {len(lands)} lands, {len(acc)} accel"
                  f"{'':<7} {a:6.1f}% / {b:5.1f}% {g1:9.1f}% / {g2:5.1f}%")


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
        srows = worst_lines(names, scry, lands, accels, sims,
                            random.Random(17), top=1)
        lines = []
        for pr, turn, mv, req, cards in srows:
            lines.append((f"{cards[0]} T{turn}", mv,
                          "".join("{%s}" % x for x in req)))
        lines += commander_lines(cmdr, scry)
        res = playsim_report(lands, accels, 99, lines, trials, random.Random(17))

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
