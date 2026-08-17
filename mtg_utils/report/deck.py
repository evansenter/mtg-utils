"""Deck-composition printers: what is in the 100, and what claims to be.

The slot budget, the land roster, the combo audit, the primer link check and
the floor -- what the population thinks of the cards the list already runs.
None of these is a probability -- they are counts and lookups over the list as
written, over prose that claims to describe it, and over a ranking page.

`floor` fetches, which is fine: printers are the I/O boundary here. What must
stay below them is MEASUREMENT, and floor_audit is where that lives.
"""
import time
from collections import defaultdict
from mtg_utils.analysis import (CURVE_TOP, deck_skeleton, floor_audit,
                                is_bounding_header, primer_audit)
from mtg_utils.decklist import as_cmdrs, flat
from mtg_utils.primer import parse_primer_links
from mtg_utils.roster import ANY_COLOUR, PAIR_CYCLES, TRIPLE_CYCLES, WUBRG, identity_pairs, roster_names, roster_status
from mtg_utils.sources.collection import load_collection
from mtg_utils.sources.edhrec import PAGE_CAP
from mtg_utils.sources.edhtop16 import MIN_ENTRIES
from mtg_utils.sources.ranking import SOURCE_LABEL, fetch_ranking
from mtg_utils.sources.scryfall import scry_fetch
from mtg_utils.sources.spellbook import spellbook

# Floor rows are NOT truncated, and the name column is sized to the run.
#
# Every row here is a card the reader is holding and will look up in their own
# list, where an MDFC is spelled out in full -- which is also why floor_audit
# keeps the decklist's spelling over the source's. Any fixed width cuts some
# name down to something that matches nothing they can search for, and picking
# one by eye gets it wrong: 44 was chosen to fit "Agadeem's Awakening //
# Agadeem, the Undercrypt" and truncated it, because that name is 46
# characters and not 45. This repo's own fixtures already hold a 54-character
# one ("Shatterskull Smashing // Shatterskull, the Hammer Pass").
#
# So the width is measured off the rows actually being printed, with a floor
# so a short-named list still lays out as a table rather than a ragged column.
FLOOR_NAME_MIN = 44


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


def _floor_label(row):
    """A floor row's name cell, written as the decklist line it came from.

    A quantity is shown only when there is more than one copy, so an ordinary
    singleton list is unchanged. It has to be shown at all because the counts
    beside every heading are CARDS: four Dragon's Approach is one row and four
    cards, and a block headed (4) over a single row is otherwise unexplained.
    """
    return f"{row['qty']} {row['name']}" if row["qty"] > 1 else row["name"]


def _floor_name_width(a):
    """One width for every block, measured off the rows this run will print.

    Measured once over all three blocks rather than per block, or the same
    report would lay its tables out three different ways.
    """
    labels = [_floor_label(r)
              for r in a["below"] + a["above"] + a["unranked"]]
    return max([FLOOR_NAME_MIN] + [len(l) for l in labels])


def _floor_ranked_rows(rows, width):
    """The ranked half of a floor table: measured figures, one row each."""
    print(f"  {'card':{width}s} {'incl':>6} {'syn':>7} {'n/of':>13}"
          f"  cardlist")
    for r in rows:
        n_of = f"{r['num_decks']}/{r['potential_decks']}"
        # None prints as "-", never as 0.0. Zero is a MEASURED synergy -- it
        # is exactly what a card played at the same rate everywhere scores --
        # so the two must not share a rendering. Every --cedh row is unknown.
        syn = "-" if r.get("synergy") is None else f"{r['synergy']:+.3f}"
        print(f"  {_floor_label(r):{width}s} "
              f"{r['inclusion']:5.1f}% {syn:>7} {n_of:>13}  {r['cardlist']}")


def _floor_unranked_rows(rows, width):
    """The unranked half: BOUNDS, and they are never rendered as figures.

    `<=` and not `<`: the display floor is the lowest figure the list
    actually printed, so an omitted card sits at or below it -- a tie on the
    boundary row is broken by something the payload does not expose.

    The depth quoted is `ranked`, not `entries`: the floor was measured over
    the rows that carried a ratio, and quoting the displayed count instead
    would offer a reader a number the bound does not rest on as the one piece
    of evidence they can check it against.
    """
    print(f"  {'card':{width}s} {'bound':>7}  what the page shows")
    for u in rows:
        b = u["bound"]
        if b is None:
            # The page said nothing. Not a low number, not a blank cell --
            # the one rendering that cannot be misread as evidence.
            print(f"  {_floor_label(u):{width}s} {'?':>7}  "
                  f"no ranked cardlist on this page could have held it")
            continue
        cap = f", at the {PAGE_CAP}-row cap" if b["capped"] else ""
        # Pluralised on the count: the captured page's Battles list came back
        # with exactly one row, so "(1 ranked rows)" is reachable on the very
        # commander this repo's fixture was taken from -- it stays out of the
        # snapshots only because partner.txt runs no battle.
        n = b["ranked"]
        print(f"  {_floor_label(u):{width}s} "
              f"{'<=' + format(b['floor'], '.1f') + '%':>7}  "
              f"below the {b['header']!r} display floor "
              f"({n} ranked row{'' if n == 1 else 's'}{cap})")


def report_floor(cmdr, entries, scry, rec_cache=None, cedh=False,
                 threshold=50.0, sort="inclusion"):
    """The inverse of `ceiling`: what is IN the list and the population is not.

    NETWORK unless `rec_cache` already holds the page, exactly as `ceiling`
    is. Unlike `ceiling` it needs no Scryfall round trip at all -- every card
    it ranks is in the decklist, so its type line is already in the cache the
    CLI built.

    This exists because nothing in this repo priced a CUT. `ceiling` says
    what is missing; `roster` ranks lands; `variants` measures a swap once you
    have chosen one. Which card to put on the block was decided by hand every
    time, and by hand it proposed four cuts in one session with the inclusion
    figure pulled for none of them -- two of those cards were at 75.5% and
    64.5% under that commander and were restored a day later.

    So the rows above the bar are PRINTED, not counted away. A reader
    checking a cut they have already half-decided has to be able to find the
    card and see where it sits; a table that silently omits it teaches them
    that absence means "fine to cut".
    """
    rank = fetch_ranking(as_cmdrs(cmdr), rec_cache, cedh)
    print(f"\n=== FLOOR vs {SOURCE_LABEL[rank['source']]}: {rank['label']} ===")
    if rank["source"] == "edhtop16":
        # The entry count sits beside every percentage, never behind it, for
        # the same reason it does in `ceiling`: at four entries every card is
        # 25/50/75/100% and the table reads like a strong signal.
        print(f"  {rank['n_entries']} tournament entries counted")
        if rank["n_entries"] < MIN_ENTRIES:
            print(f"  FEWER THAN {MIN_ENTRIES} ENTRIES -- no percentage is "
                  f"quoted from this sample.")
            print("  Run again when the commander has more results, or drop "
                  "--cedh for EDHREC.")
            return None
    # BOTH sources, not just EDHREC. As an `elif` this could never reach the
    # edhtop16 branch, and the shape it misses is reachable: five or more
    # entries whose maindecks all come back empty pass the MIN_ENTRIES guard
    # and rank nothing at all. The mirror of ceiling's empty-page guard, and
    # it fails louder here -- fall through on EDHREC and every card comes back
    # unranked with no bound, fall through on edhtop16 and every card is
    # printed at a measured 0%. Both read as a deck of pure filler, produced
    # from a payload that told us nothing.
    if not rank["rows"]:
        detail = ("That is a fetch or slug problem, not a list the population "
                  "has never heard of"
                  if rank["source"] == "edhrec" else
                  f"{rank['n_entries']} entries came back carrying no "
                  f"decklists, which is a fetch problem, not a list nobody "
                  f"plays")
        raise SystemExit(
            f"{SOURCE_LABEL[rank['source']]} ranked no cards at all for "
            f"{rank['label']!r}. {detail} -- refusing to price a cut from a "
            f"source that told us nothing.")

    a = floor_audit(cmdr, entries, rank["rows"], rank["floors"], scry,
                    threshold, sort, rank["exhaustive"], rank["n_entries"])
    # Every count below is in CARDS, the units `verify` and `skeleton` report
    # in, so the identity line reconciles against them rather than against a
    # distinct-name total that silently drops duplicate basics.
    c = a["counts"]
    width = _floor_name_width(a)
    print(f"  {a['considered']} cards ranked; {c['nonland']} non-land cards in "
          f"this list, {c['lands']} lands skipped")
    # `g`, not `.0f`: --bar is a float, so `--bar 47.5` printed "bar is 48%"
    # and then filed a 47.8% row under BELOW THE BAR -- below the bar it was
    # measured against, above the bar the report named. Integral bars, which
    # is every one in the snapshots, print identically either way.
    print(f"  bar is {threshold:g}% inclusion, sorted by {sort}, ascending "
          f"-- the most cuttable row first")

    print(f"\n  --- BELOW THE BAR ({c['below']}) ---")
    if a["below"]:
        _floor_ranked_rows(a["below"], width)
    else:
        print("  (nothing in this list is ranked below the bar)")

    print(f"\n  --- NOT RANKED ON THIS PAGE ({c['unranked']}) ---")
    if a["unranked"]:
        _floor_unranked_rows(a["unranked"], width)
    elif a["exhaustive"]:
        print("  (none, and there cannot be: this source counts whole "
              "decklists, so a card")
        print("  it does not rank was in zero of them and is a measured 0% "
              "above)")
    else:
        print("  (none -- every non-land card in this list is ranked)")

    print(f"\n  --- AT OR ABOVE THE BAR ({c['above']}) ---")
    if a["above"]:
        # Printed rather than counted, deliberately. See the docstring: the
        # incident this command was written after was four cuts proposed with
        # the numbers pulled for none of them.
        print("  These are NOT cut candidates. Listed so a cut already "
              "half-decided can be")
        print("  looked up and found, rather than being absent for a reason "
              "the table does not give.")
        _floor_ranked_rows(a["above"], width)
    else:
        print("  (nothing in this list is ranked at or above the bar)")

    # Asserted by floor_audit before this line ran, and printed as a
    # statement rather than as arithmetic for the reader to check -- the same
    # discipline the skeleton header uses. A card in no group would otherwise
    # be a card the report neither prints nor counts.
    print(f"\n  {c['cards']} cards (commanders aside) = {c['lands']} "
          f"lands + {c['below']} below + {c['unranked']} unranked "
          f"+ {c['above']} at or above"
          f"{' + ' + str(c['unresolved']) + ' unresolved' if a['unresolved'] else ''}"
          f"   [checked]")
    if a["unresolved"]:
        # Not silently dropped: a name Scryfall could not resolve has no type
        # line, so it can be neither excluded as a land nor bounded, and a
        # card in no group is a card nobody thinks about.
        print(f"  {len(a['unresolved'])} card(s) are in no group at all "
              f"because Scryfall does not know the name: "
              f"{', '.join(a['unresolved'])}")
    print("  LANDS ARE EXCLUDED. EDHREC land data reflects a budget "
          "population, so inclusion is\n  the wrong instrument for them; "
          "`roster` is the right one and already walks every slot.")
    if a["exhaustive"]:
        print("  This source counts whole decklists, so every figure above "
              "is measured and a\n  card it does not rank is a real 0%, not "
              "a card the page stopped short of.")
    else:
        print("  A bound is not a figure. EDHREC ranks the top of each "
              "cardlist and stops, and\n  each list stops at its own depth "
              "-- so the same absence is worth far more on a\n  short list "
              "than on a capped one.")
    # Only the lists that could actually have bounded a row above. `capped`
    # arrives carrying every capped cardlist on the page, selections included,
    # because that is what `ceiling` needs -- there a card missing from ANY
    # capped list is reported as below cutoff. Here a selection list bounds
    # nothing, so its caveat would talk about "its floor" under a table in
    # which no row was measured against it.
    for header in rank["capped"]:
        if not is_bounding_header(header):
            continue
        print(f"  NOTE: {header!r} came back at the {PAGE_CAP}-card display "
              f"cutoff -- its floor is where\n  the cap fell, not where the "
              f"population stopped playing these.")
    return a
