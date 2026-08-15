"""argparse wiring. Same subcommands, same flags, same argument names."""
import argparse
import os
import sys
import time

from mtg_utils import __doc__ as _BANNER
from mtg_utils.analysis import verify
from mtg_utils.decklist import (as_cmdrs, flat, parse_swaps, read_decklist,
                                write_deck)
from mtg_utils.report import (report_calibrate, report_combos, report_contention,
                              report_ceiling, report_diff, report_mana,
                              report_own, report_roster, report_skeleton,
                              report_swap, report_variants)
from mtg_utils.sources.moxfield import moxfield_deck
from mtg_utils.sources.scryfall import scry_fetch

TESTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")


def selftest():
    """Run the pytest suite. Still a subcommand, so the CLI contract holds.

    The assertions that used to live in this file are now pytest cases with
    their names kept verbatim, plus the golden suite that diffs this code's
    output against the frozen reference. Running it is no longer a one-second
    job -- it is the whole suite, including the Monte Carlo passes over three
    real decks -- but it is the same question: did anything move.

    pytest is the only dev dependency; the package itself is standard library
    only, so the import is deliberately late and the failure explicit.
    """
    try:
        import pytest
    except ImportError:
        raise SystemExit(
            "selftest runs the pytest suite: pip install pytest\n"
            "(mtg_utils itself needs nothing but the standard library)")
    if not os.path.isdir(TESTS_DIR):
        raise SystemExit(f"no tests/ directory at {TESTS_DIR} -- selftest needs "
                         "the repository, not just an installed package")
    return pytest.main([TESTS_DIR])


# ============================================================ CLI
def main():
    ap = argparse.ArgumentParser(description=_BANNER,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["fetch", "verify", "mana", "variants", "combos",
                                    "own", "contention", "moxfield", "write", "audit",
                                    "roster", "diff", "selftest", "calibrate", "ceiling",
                                    "skeleton"])
    ap.add_argument("target", nargs="?", default=None,
                    help="decklist path, or deck id for `moxfield`; unused by `selftest`")
    ap.add_argument("--cache", default="scry.json")
    # sims/trials are the budget for the WHOLE measurement, split across
    # --reps. Defaults are unchanged from before replicates existed, so the
    # default run does the same work and the reported mean is exactly as
    # precise as it was -- the error bar comes from re-slicing, not from
    # doing more.
    ap.add_argument("--sims", type=int, default=8000,
                    help="total sources-model sims, split across --reps")
    ap.add_argument("--trials", type=int, default=20000,
                    help="total play-sim trials, split across --reps")
    ap.add_argument("--reps", type=int, default=3,
                    help="replicates used to estimate the +/- on each figure")
    ap.add_argument("--seed", type=int, default=17,
                    help="base RNG seed; replicate i uses seed+i")
    ap.add_argument("--out", default=None)
    ap.add_argument("--decks", default="", help="comma-separated Moxfield ids")
    ap.add_argument("--lands", default="-2,0,2",
                    help="land count deltas, e.g. -2,0,2 (leading minus needs --lands=-2,0,2)")
    ap.add_argument("--accel", default="0,2", help="accelerant count deltas")
    ap.add_argument("--adds", default="")
    ap.add_argument("--cuts", default="")
    ap.add_argument("--rec-cache", default="edhrec.json",
                    help="ceiling: on-disk cache for EDHREC / edhtop16 pages")
    ap.add_argument("--cedh", action="store_true",
                    help="ceiling: use edhtop16 tournament data instead of EDHREC")
    ap.add_argument("--bar", type=float, default=50.0,
                    help="ceiling: inclusion %% above which a missing card is reported")
    ap.add_argument("--sort", choices=["inclusion", "synergy"],
                    default="inclusion",
                    help="ceiling: order the reported rows; the bar stays on "
                         "inclusion either way")
    ap.add_argument("--swap", default="",
                    help="variants: measure named swaps, 'Cut->Add,Cut2->Add2' "
                         "(use ';' between pairs if a name contains a comma)")
    a = ap.parse_args()

    if a.cmd == "selftest":
        sys.exit(selftest())
    if a.cmd == "calibrate":
        report_calibrate([x for x in a.decks.split(",") if x],
                         a.cache, a.sims, a.trials, user=a.target)
        return
    if not a.target:
        ap.error(f"`{a.cmd}` needs a target")

    if a.cmd == "moxfield":
        name, cmdrs, main = moxfield_deck(a.target)
        # One header, not two. This printed a bare "# {name} (fetched ...)"
        # here AND built a second, fuller one into the text below -- so stdout
        # carried both, and writing to --out still printed the bare one to the
        # terminal. The header that survives is the one carrying the deck id,
        # because that is the provenance a delta has to name.
        out = list(cmdrs) + [""]
        out += [f"{q} {n}" for n, q in sorted(main.items(), key=lambda x: x[0].lower())]
        header = (f"# {name}  (deck {a.target}, fetched "
                  f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})")
        text = header + "\n" + "\n".join(out) + "\n"
        if a.out:
            open(a.out, "w", encoding="utf-8").write(text)
            print(f"wrote {a.out}")
        else:
            print(text)
        return

    cmdr, entries = read_decklist(a.target)
    if not cmdr:
        ap.error(f"no commander line found in {a.target}")
    if a.cmd == "diff":
        ids = [x for x in a.decks.split(",") if x]
        if len(ids) != 1:
            ap.error("`diff` needs exactly one --decks <publicId>")
        sys.exit(0 if report_diff(cmdr, entries, ids[0]) else 2)
    # Parsed before the fetch so the cards a swap ADDS are looked up too --
    # they are not in the decklist, and measuring a swap against a card the
    # cache has never seen would silently model it as producing nothing.
    swaps = parse_swaps(a.swap)
    scry, nf = scry_fetch(flat(cmdr, entries) + [add for _cut, add in swaps],
                          a.cache)
    if nf:
        print("SCRYFALL NOT FOUND (front-face names only!):", nf)

    if a.cmd in ("verify", "audit"):
        v = verify(cmdr, entries, scry)
        # The commander count is len(cmdrs), not 1. A partner or background
        # pair is TWO, and verify() has always counted both in `total` -- only
        # this sentence claimed otherwise, so the printed arithmetic came out
        # one short (100 = 1 + 60 + 38) on exactly the decks whose primer
        # header is hardest to check by eye.
        ncmdr = len(as_cmdrs(cmdr))
        print(f"\n=== VERIFY: {cmdr} ===")
        print(f"  {v['total']} cards = {ncmdr} commander"
              f"{'' if ncmdr == 1 else 's'} + {v['nonland']} non-land "
              f"+ {v['lands']} lands  ({v['mdfc_land_backs']} MDFC land-backs)")
        print(f"  average non-land MV {v['avg_mv']:.2f}")
        print(f"  Game Changers ({len(v['game_changers'])}, Scryfall game_changer): "
              f"{v['game_changers']}")
        print(f"  illegal: {v['illegal'] or 'none'}")
        print(f"  colour identity violations: {v['ci_violations'] or 'none'}")
        if v["total"] != 100:
            print(f"  *** DECK IS {v['total']} CARDS, COMMANDER IS 100 ***")
    if a.cmd in ("mana", "audit"):
        report_mana(cmdr, entries, scry, a.sims, a.trials, a.seed, reps=a.reps)
    if a.cmd == "skeleton":
        report_skeleton(cmdr, entries, scry)
    if a.cmd == "ceiling":
        report_ceiling(cmdr, entries, scry, a.cache, a.rec_cache, a.cedh,
                       a.bar, a.sort)
    if a.cmd in ("roster", "audit"):
        report_roster(cmdr, entries, scry, a.cache)
    if a.cmd == "variants":
        if swaps:
            report_swap(cmdr, entries, scry, swaps, a.sims, a.trials,
                        a.seed, a.reps)
        else:
            report_variants(cmdr, entries, scry,
                            [int(x) for x in a.lands.split(",")],
                            [int(x) for x in a.accel.split(",")], a.trials,
                            a.seed, a.reps)
    if a.cmd in ("combos", "audit"):
        report_combos(cmdr, entries)
    if a.cmd in ("own", "audit"):
        report_own(cmdr, entries, scry)
    if a.cmd == "contention":
        report_contention(cmdr, entries, [x for x in a.decks.split(",") if x])
    if a.cmd == "write":
        write_deck(cmdr, entries, a.out or "final_deck.txt",
                   [x for x in a.adds.split(",") if x],
                   [x for x in a.cuts.split(",") if x])
