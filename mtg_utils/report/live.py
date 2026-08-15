"""Printers that read a LIVE Moxfield account. Network-only, both of them.

`report_calibrate` is the one printer that also MEASURES -- its per-deck loop
is analysis living in a printer. It is network-only, so no offline test could
verify a split of it; left whole deliberately.
"""
import random
import time
from collections import Counter
from mtg_utils.analysis import commander_lines, verify, worst_lines
from mtg_utils.castability import playsim_report
from mtg_utils.decklist import as_cmdrs, diff_multiset, flat
from mtg_utils.profiles import build_accel_profiles, build_land_profiles
from mtg_utils.sources.moxfield import moxfield_deck, moxfield_user_decks
from mtg_utils.sources.scryfall import scry_fetch


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
