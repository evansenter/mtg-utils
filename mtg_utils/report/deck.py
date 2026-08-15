"""Deck-composition printers: what is in the 100, and what claims to be.

The slot budget, the land roster, the combo audit and the primer link check.
None of these is a probability -- they are counts and lookups over the list as
written, and over prose that claims to describe it.
"""
import time
from collections import defaultdict
from mtg_utils.analysis import CURVE_TOP, deck_skeleton, primer_audit
from mtg_utils.decklist import as_cmdrs, flat
from mtg_utils.primer import parse_primer_links
from mtg_utils.roster import ANY_COLOUR, PAIR_CYCLES, TRIPLE_CYCLES, WUBRG, identity_pairs, roster_names, roster_status
from mtg_utils.sources.collection import load_collection
from mtg_utils.sources.scryfall import scry_fetch
from mtg_utils.sources.spellbook import spellbook


def report_skeleton(cmdr, entries, scry):
    """The slot budget and the curve. deck_skeleton computes and asserts it."""
    s = deck_skeleton(cmdr, entries, scry)
    ncmdr = s["commanders"]
    print(f"\n=== SKELETON: {' + '.join(as_cmdrs(cmdr))} ===")
    # The identity was ASSERTED by deck_skeleton before this line ran -- it is
    # printed as a statement, not as arithmetic for the reader to check. A
    # hand-written header once read "24 lands plus 75 non-land" for a
    # 100-card deck, with the commander missing from the sum.
    print(f"  {s['total']} = {ncmdr} commander{'' if ncmdr == 1 else 's'}"
          f" + {s['lands']} lands + {s['nonland']} non-land   [checked]")
    # The two manabase levers, side by side: land count and accelerant count
    # are the pair you trade against each other before choosing any card.
    print(f"  manabase levers: {s['lands']} lands"
          f" (+{s['mdfc_land_backs']} MDFC land backs)"
          f"   {s['accelerants']} accelerants at MV<=3")
    print(f"  average non-land MV {s['avg_mv']:.2f}"
          f"   Game Changers {s['game_changers']}")

    nonland_cards = sum(s["curve"].values())
    print(f"\n--- curve ({nonland_cards} non-land cards) ---")
    for mv in range(CURVE_TOP + 1):
        n = s["curve"].get(mv, 0)
        label = f"{mv}+" if mv == CURVE_TOP else str(mv)
        # rstrip: an empty bar would leave trailing spaces, which are
        # invisible in review and churn in a byte-exact snapshot.
        print(f"  {label:>3} {n:3d}  {'#' * min(n, 40)}".rstrip())

    print(f"\n--- slots by type ({sum(s['types'].values())} non-commander"
          f" cards) ---")
    for t, n in sorted(s["types"].items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {t:14s} {n:3d}")
    # Type lines are what can be counted. Ramp, draw and interaction are what
    # a skeleton actually budgets, and inferring them needs a heuristic this
    # repo would have to invent -- so they are absent rather than guessed.
    print("\n  Types, not functional roles: ramp/draw/interaction are not "
          "inferred.\n  The one measured functional count is the accelerants "
          "above.")
    return s


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


def report_primer(cmdr, entries, scry, primer_path, cache=None):
    """Check every `[[Card]]` in a primer against Scryfall and the decklist.

    NETWORK on a cache miss, like `ceiling` and `roster`: a link naming a card
    that is NOT in the list is precisely the interesting case, and its Scryfall
    record was therefore never fetched by the decklist pass. Looking up only
    the unknown names keeps the usual run to zero round trips.

    Returns the audit dict. The exit status is the caller's to set -- this is
    a check, and a check that cannot fail a script is a check nobody runs.
    """
    with open(primer_path, encoding="utf-8") as f:
        text = f.read()
    links = parse_primer_links(text)
    # Wrapped links are excluded from the fetch. Their normalised name is a
    # guess at what the author meant, and asking Scryfall about a guess turns
    # one clear "this link is broken" into a second, contradictory
    # "...and this card does not exist".
    want = [l["name"] for l in links if not l["wrapped"]]
    if want:
        scry, nf = scry_fetch(want, cache)
        if nf:
            print("  SCRYFALL NOT FOUND (primer link, front-face names "
                  "only!):", nf)
    a = primer_audit(text, cmdr, entries, scry)
    print(f"\n=== PRIMER: {primer_path} ===")
    print(f"  {len(a['links'])} links, {a['distinct']} distinct cards")
    if a["unclosed"]:
        print(f"\n  UNCLOSED '[[' ({len(a['unclosed'])}) -- no closing ']]', so "
              f"the card named here is checked by nothing:")
        for line in a["unclosed"]:
            print(f"    line {line}")
    if a["wrapped"]:
        print(f"\n  BROKEN ACROSS LINES ({len(a['wrapped'])}) -- these render as "
              f"literal text, brackets and all:")
        for l in a["wrapped"]:
            print(f"    line {l['line']}: {l['name']}")
    if a["not_found"]:
        print(f"\n  NOT A CARD ({len(a['not_found'])}) -- Scryfall does not know "
              f"this name:")
        for l in a["not_found"]:
            print(f"    line {l['line']}: {l['name']}")
    if a["not_in_deck"]:
        print(f"\n  NO LONGER IN THE DECK ({len(a['not_in_deck'])}) -- the primer "
              f"still argues for these:")
        for l in a["not_in_deck"]:
            print(f"    line {l['line']}: {l['name']}")
    if a["ok"]:
        print("  every link renders, names a real card, and is in the list.")
    return a
