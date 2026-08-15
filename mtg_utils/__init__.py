"""
mana_model.py — deck validation and castability for Commander decks.

ONE FILE. Do not create a second script beside this one; extend it and
re-deliver the whole thing (see PROJECT NOTES at the bottom).

Two models, because they answer different questions:

  sources model   "can I make these pips"      -> analyse()
  play simulation "do I have N mana on turn N" -> playsim()

Mana sources are LANDS PLUS CHEAP ACCELERANTS (mana value <= 3 that tap for
mana) plus MDFC land backs. Lands-only understates castability badly: measured
on Pantlaza, {2}{R}{G}{W} on turn five was 36.4% lands-only and 53.5% once the
accelerants were counted. The lands-only figure is a statement about land
count, not about castability, and must not be reported as one.

Subcommands
-----------
  fetch       build/refresh the Scryfall cache for a decklist
  verify      count, legality, colour identity, Game Changers, MV, tapped classes
  mana        sources model + play simulation (the full section 6 pass)
  roster      section 6 roster walk: every cycle slot, IN / benched / buy
  ceiling     EDHREC (or --cedh edhtop16) inclusion: what is above the bar
              and missing from the list, with ownership and price
  variants    opt-in land/accelerant sweep; slow, run when the base is unsettled
  combos      Commander Spellbook full-deck audit
  own         ownership vs ManaBox + grouped buy list
  contention  copies owned vs Moxfield decks wanting the card
  moxfield    fetch a live deck into decklist format
  write       write the final 100 and assert it back
  diff        card-multiset diff of a local list against the LIVE Moxfield deck
  audit       verify + mana + roster + combos + own  (full pass, no variants)
  selftest    offline regression tests; run after ANY edit to this file
  calibrate   re-measure every live deck into one table (never store the rows)

Decklist format: first non-blank line is the commander, then one entry per
line as "N Card Name" or bare "Card Name".
"""
# The docstring above is argparse's `description` and is therefore
# OUTPUT: cli.py passes it explicitly rather than relying on __doc__,
# which would silently become cli.py's own docstring instead.
#
# Everything public is re-exported here so `import mana_model` keeps
# working for anything that used the single file as a library.

from mtg_utils.cards import (BASIC_TYPE_COLOUR, COLOURS, CONDITIONAL_TAP_MARKERS,
                             CONDITIONAL_TAP_PATTERNS, MANA_SYMBOLS, WORDNUM,
                             enters_tapped, faces, fetch_targets, front,
                             front_name, has_land_back, is_front_land, land_face,
                             mana_amount)
from mtg_utils.profiles import (FILTER_LANDS, OMNI_TYPE, build_accel_profiles,
                                build_land_profiles)
from mtg_utils.castability import (_match, at_least_in_draw, castable,
                                   castable_faces, pips_from_cost, playable_set,
                                   playsim, playsim_report, probability)
from mtg_utils.decklist import (apply_swaps, as_cmdrs, diff_multiset, flat,
                                parse_swaps, read_decklist, write_deck)
from mtg_utils.roster import (ANY_COLOUR, PAIR_CYCLES, TRIPLE_CYCLES, WUBRG,
                              identity_pairs, pair_key, roster_names, roster_status)
from mtg_utils.analysis import (analyse_mana, ceiling_audit, collapse_temps,
                                commander_lines, compare_swap, deck_base_name,
                                mean_spread, opening_hand_floor,
                                replicate_playsim, split_budget, t95, verify,
                                worst_lines)
from mtg_utils.sources import UA_BROWSER, UA_TOOL
from mtg_utils.sources.collection import COLLECTION, load_collection
from mtg_utils.sources.moxfield import (moxfield_deck, moxfield_user_decks,
                                        parse_moxfield)
from mtg_utils.sources.edhrec import (PAGE_CAP, edhrec_fetch, edhrec_slug,
                                      parse_commander_page)
from mtg_utils.sources.edhtop16 import (MIN_ENTRIES, edhtop16_commander_name,
                                        edhtop16_fetch, parse_edhtop16)
from mtg_utils.sources.scryfall import scry_fetch
from mtg_utils.sources.spellbook import spellbook
from mtg_utils.report import (report_calibrate, report_combos, report_contention,
                              report_ceiling, report_diff, report_mana,
                              report_own, report_roster, report_swap,
                              report_variants)


# `hypergeometric` was renamed to `at_least_in_draw`. Everything here is
# re-exported so `import mana_model` keeps working as a library import, so a
# bare rename would give a caller a plain AttributeError several frames from
# the cause. This fails by name and says what to do instead -- and it
# deliberately does NOT alias the old name, because the whole point of the
# rename is that `hypergeometric` reads like a figure worth quoting.
def __getattr__(name):
    if name == "hypergeometric":
        raise AttributeError(
            "hypergeometric() is now at_least_in_draw(k, sources, cards_seen, "
            "deck). The name was changed because it described the maths rather "
            "than the question, and it is NOT a castability figure -- use "
            "probability() for the sources model or playsim() for the play "
            "simulation.")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
