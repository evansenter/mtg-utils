"""Ownership printers: what you have, what competes for it, what to add.

All three read the ManaBox collection. `ceiling` also reaches two ranking
endpoints and Commander Spellbook, and cross-references the roster walk; see
mtg_utils/sources/ for the traps each one carries.

`ceiling`'s inverse, `floor`, is NOT here -- it answers "what is in the 100",
reads no collection and prices no purchase, so it sits in report/deck.py with
the rest of that question. The two share their fetch through
mtg_utils/sources/ranking.py rather than through this file.
"""
import time
from collections import defaultdict
from mtg_utils.analysis import (ceiling_audit, collapse_temps,
                                combo_completions, decisions_audit)
from mtg_utils.cards import front_name
from mtg_utils.decklist import as_cmdrs, read_decisions
from mtg_utils.sources.collection import load_collection
from mtg_utils.sources.edhrec import PAGE_CAP
from mtg_utils.sources.edhtop16 import MIN_ENTRIES
from mtg_utils.sources.moxfield import moxfield_deck
from mtg_utils.sources.ranking import SOURCE_LABEL, fetch_ranking
from mtg_utils.sources.scryfall import scry_fetch
from mtg_utils.sources.spellbook import spellbook


# How many combo lines a ceiling row prints before the rest are summarised.
# Displacer Kitten alone came back with sixteen `produces` features on one
# combo; printed whole, one row buries the table it is annotating.
COMBO_LINES = 2


PRODUCES_SHOWN = 2


def _decision_lines(notes):
    """A card's decision notes, one line each.

    ANNOTATES, NEVER SUPPRESSES -- the rule the whole feature turns on. The
    proposal that prompted this wanted rejected rows hidden behind a flag, and
    hiding is the one thing a note must not do: a stale CUT would silently
    remove a card that has since become right, and a shorter table reads as
    less work to do. The row still prints, with the reason attached, and the
    reader decides.
    """
    return [f"{d['verdict']} {d['reason']}" for d in notes]


def _roster_line(note):
    """One land row's roster verdict, or None when the roster has no opinion.

    Printed ONLY when a better slot for the same colour pair is already in the
    list. A land the roster ranks below nothing is not a finding, and a line on
    every land row would bury the handful that are.
    """
    if not note or not note["better"]:
        return None
    held = ", ".join(f"{card} ({cycle})" for cycle, card in note["better"])
    this = f"this is the {note['cycle']}" if note["on_roster"] \
        else "this is on no roster cycle"
    return f"ROSTER: {note['key']} already holds {held}; {this}"


def _combo_line(c):
    """One combo, as a single line under the ceiling row it annotates."""
    pieces = list(c["with"]) + [f"{t} (template)" for t in c["templates"]]
    line = "COMBO with " + (", ".join(pieces) if pieces else "the commander")
    # The honest qualifier. "Almost included" means at least one piece is
    # missing, not exactly one, so a combo needing two more cards must not
    # read the same as one this card finishes on its own.
    if c["also_missing"]:
        line += f"  (also needs {', '.join(c['also_missing'])})"
    produces = c["produces"][:PRODUCES_SHOWN]
    if produces:
        line += " -> " + ", ".join(produces)
        extra = len(c["produces"]) - len(produces)
        if extra:
            line += f" +{extra} more"
    return line


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


def report_ceiling(cmdr, entries, scry, cache=None, rec_cache=None, cedh=False,
                   threshold=50.0, sort="inclusion", combos=True,
                   decklist=None):
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
    # The fetch, the slug/name rules and the "no response" guard are shared
    # with `floor` -- see mtg_utils/sources/ranking.py. Only the guards that
    # sit AFTER the header line are still here, because that is where they
    # print.
    rank = fetch_ranking(cmdrs, rec_cache, cedh)
    rows, capped = rank["rows"], rank["capped"]
    n_entries, slug = rank["n_entries"], rank["label"]
    print(f"\n=== CEILING vs {SOURCE_LABEL[rank['source']]}: {slug} ===")
    if rank["source"] == "edhtop16":
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
    elif not rows:
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
    have = {front_name(n).lower() for n in list(entries) + as_cmdrs(cmdr)}
    want = [r["name"] for r in rows
            if r["inclusion"] >= threshold
            and front_name(r["name"]).lower() not in have]
    if want:
        scry, nf = scry_fetch(want, cache)
        if nf:
            print("  SCRYFALL NOT FOUND (ranked card, front-face names "
                  "only!):", nf)

    # The combo cross-check is ON by default and DEGRADES LOUDLY. The card
    # this matters for is the one you would never have looked up: a row can
    # form a forced draw or a two-card infinite with something already in the
    # list, and on the deck that prompted this the intersection sat at 7%
    # inclusion -- below any default bar, reachable only by lowering it, which
    # is exactly when nobody thinks to add a flag. Opt-in would have put the
    # check behind the decision it exists to inform.
    #
    # A Spellbook outage must not take `ceiling` down with it, and must not
    # quietly turn into "no combos found" either -- an unrun check and a clean
    # result are the same empty column.
    # Notes live in the decklist file, so they are read from it rather than
    # from a store keyed on the commander. `decklist` is optional: every other
    # caller of report_ceiling predates notes and must keep working.
    decisions = decisions_audit(read_decisions(decklist) if decklist else [],
                                cmdr, entries)
    completions, combo_note = {}, None
    if combos:
        try:
            completions = combo_completions(spellbook(cmdr, entries), cmdr,
                                            entries)
        except SystemExit as e:
            combo_note = str(e)
    a = ceiling_audit(cmdr, entries, rows, capped, load_collection(), scry,
                      threshold, sort, completions)
    # `g` rather than `.0f` for the same reason `floor` uses it: --bar is a
    # float and rounding it in print puts the bar the report NAMES on the far
    # side of a row from the bar it was measured against. No snapshot moves --
    # every bar in them is integral, which prints identically either way.
    print(f"  {a['considered']} cards ranked; bar is {threshold:g}% inclusion"
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
        for line in _decision_lines(decisions["by_card"].get(
                front_name(m["name"]).lower(), [])):
            print(f"      {line}")
        roster_line = _roster_line(m.get("roster"))
        if roster_line:
            print(f"      {roster_line}")
        for c in m["combos"][:COMBO_LINES]:
            print(f"      {_combo_line(c)}")
        if len(m["combos"]) > COMBO_LINES:
            # Never a silent cap. A row saying "2 combos" when it has nine is
            # a smaller number than the truth, printed with confidence.
            print(f"      ...and {len(m['combos']) - COMBO_LINES} more combo"
                  f"{'' if len(m['combos']) - COMBO_LINES == 1 else 's'}")
    if not a["missing"]:
        print("  (nothing above the bar is missing from this list)")
    print(f"\n  {len(a['missing'])} missing above the bar, "
          f"{a['owned_count']} already owned; "
          f"buy total ${a['buy_total']:.2f}")
    # The staleness report is the falsifiable half, and it is printed whether
    # or not the stale note's card came up in this run -- a note nobody is
    # looking at is exactly the one that rots.
    if decisions["readmitted"]:
        print(f"\n  NOTES THAT NOW CONTRADICT THE LIST "
              f"({len(decisions['readmitted'])}):")
        for d in decisions["readmitted"]:
            print(f"    line {d['line']}: {d['card']} is marked {d['verdict']} "
                  f"and is IN the deck")
    if decisions["stale"]:
        print(f"\n  NOTES WHOSE REASON HAS EXPIRED ({len(decisions['stale'])}):")
        for d in decisions["stale"]:
            print(f"    line {d['line']}: {d['card']} -- reason cites "
                  f"{', '.join(d['gone'])}, no longer in the deck")
    downgrades = sum(1 for m in a["missing"] if _roster_line(m.get("roster")))
    if downgrades:
        # Said once at the bottom as well as inline, because the land rows are
        # scattered through a table sorted on something else entirely.
        print(f"  {downgrades} land row{'' if downgrades == 1 else 's'} sit "
              f"below a roster slot this deck has already filled. EDHREC land "
              f"data\n  reflects a budget population; inclusion is the right "
              f"tool for spells, the roster\n  walk is the right tool for "
              f"lands.")
    if combo_note:
        # Absence of a check is not a clean result. Said out loud, or the
        # empty combo column reads as "nothing here interacts".
        print(f"  COMBO CROSS-CHECK DID NOT RUN: {combo_note}")
        print("  The rows above are NOT known to be free of combos with this "
              "list.")
    elif combos:
        print(f"  {a['combo_rows']} row"
              f"{'' if a['combo_rows'] == 1 else 's'} interact with cards "
              f"already in the list (Commander Spellbook).")
        if a["combo_rows"]:
            # Deliberately not "recommended". The interaction that prompted
            # this feature was a card forming a FORCED DRAW with two cards in
            # the deck -- a combo is a fact about the list, and whether it is
            # an argument for or against the card is not Spellbook's to say.
            print("  A combo is a fact, not a recommendation: verify the "
                  "pieces against oracle\n  text and decide which direction "
                  "it argues in.")
    # A capped list is the difference between "this card is unplayed" and
    # "this page did not tell us". Never printed as 0%.
    for header in capped:
        print(f"  NOTE: '{header}' came back at the {PAGE_CAP}-card display "
              f"cutoff -- cards below that cutoff are of UNKNOWN inclusion, "
              f"not 0%.")
    return a
