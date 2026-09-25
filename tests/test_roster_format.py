"""`roster` walks the colours the deck PLAYS, filtered to the format.

Run on a five-colour commander it printed the whole roster -- ABUR duals,
fetchlands, battlebond lands, pathways -- for a deck built in three colours,
and essentially none of it is legal in the format the deck is in. Two problems
compounding: the WU and W rows are not empty slots, they are noise; and a
shopping list of cards that cannot be registered is worse than no list.

The walk already asserts every roster name against Scryfall at report time, so
it is holding the card object and the legality with it.
"""
import os

import pytest

from conftest import FIXTURES, run_cli

BRAWL = [os.path.join(FIXTURES, "brawl.txt"),
         f"--cache={os.path.join(FIXTURES, 'brawl.scry.json')}"]
MULTI = [os.path.join(FIXTURES, "multi.txt"),
         f"--cache={os.path.join(FIXTURES, 'multi.scry.json')}"]


def _roster(mm, tmp_path, deck, *extra):
    return run_cli(mm, ["roster"] + deck + list(extra), str(tmp_path))


# --- the format filter -------------------------------------------------
def test_illegal_roster_rows_are_not_walked(mm, tmp_path):
    """roster/a format-illegal cycle member is not printed

    Bayou and Verdant Catacombs are on the BG rows of two cycles and neither
    can be registered in Standard Brawl. Printed, they read as slots the deck
    could fill.
    """
    out = _roster(mm, tmp_path, BRAWL, "--format=standardbrawl")
    assert "Bayou" not in out
    assert "Verdant Catacombs" not in out
    # ...while the format-legal member of the same pair still is.
    assert "Overgrown Tomb" in out


def test_the_count_dropped_is_said_once(mm, tmp_path):
    """roster/the filter reports a count, not forty silent omissions

    A reader who cannot see what was left out cannot tell a filtered walk
    from a short roster.
    """
    out = _roster(mm, tmp_path, BRAWL, "--format=standardbrawl")
    assert "roster names are not legal in Standard Brawl and are not walked."\
        in out


def test_a_section_the_filter_empties_says_so(mm, tmp_path):
    """roster/an emptied section is named, not left blank

    A heading with nothing under it reads as a section whose slots are all
    filled, which is the opposite of what it means.
    """
    out = _roster(mm, tmp_path, BRAWL, "--format=standardbrawl",
                  "--colours=BRG")
    body = out.split("three-colour (tapped; only if the rider is real)")[1]
    assert body.splitlines()[1] == "  (nothing here is legal in Standard Brawl)"


def test_a_pair_left_with_only_a_missing_slot_says_so(
        mm, monkeypatch, capsys, tmp_path):
    """roster/"(no such card)" does not stand in for a walked row

    Some cycles have no member for some pairs -- there is no BR Horizon land
    -- and the walk prints that row as "(no such card)". It used to COUNT it
    as walked, so a pair whose every real member was illegal in the format
    printed that one line and no note, reading as a pair with nothing to
    fill rather than as a pair the format had emptied.

    No format empties a pair on the committed capture, so the BR members are
    marked not legal here. Only the legality VALUE is edited; the records are
    otherwise the frozen ones.
    """
    import json
    import shutil

    import mtg_utils.report as report
    from conftest import load_fixture_collection, patch_everywhere
    cache = os.path.join(str(tmp_path), "brawl.scry.json")
    shutil.copyfile(os.path.join(FIXTURES, "brawl.scry.json"), cache)
    with open(cache, encoding="utf-8") as f:
        scry = json.load(f)
    br = [t["BR"] for _slot, t in mm.PAIR_CYCLES if t.get("BR")]
    assert any(not t.get("BR") for _slot, t in mm.PAIR_CYCLES), \
        "the case needs a cycle with no BR member"
    for n in br:
        rec = dict(scry[n.lower()])
        rec["legalities"] = dict(rec["legalities"], standardbrawl="not_legal")
        scry[n.lower()] = rec
    patch_everywhere(monkeypatch, "load_collection", load_fixture_collection)
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "brawl.txt"))
    report.report_roster(cmdr, entries, scry, cache, "standardbrawl", "BRG")
    block = capsys.readouterr().out.split("--- BR ---")[1].split("---")[0]
    assert "(no such card)" in block
    assert "(nothing here is legal in Standard Brawl)" in block


def test_commander_drops_nothing(mm, tmp_path):
    """roster/the default format filters nothing out

    Every card on this roster is Commander-legal, so the default run is
    byte-identical to what it was -- which is what the four Commander golden
    snapshots assert, and this says why they still pass.
    """
    out = _roster(mm, tmp_path, MULTI)
    assert "are not legal in" not in out
    assert "Bayou" in out


# --- the colour override -----------------------------------------------
def test_colours_narrows_the_walk(mm, tmp_path):
    """roster/--colours walks fewer pairs than the identity

    Terra's identity is WUBRG and the list is BRG. The WU rows are not empty
    slots for that deck; they are rows about a deck nobody is building.
    """
    wide = _roster(mm, tmp_path, BRAWL, "--format=standardbrawl")
    narrow = _roster(mm, tmp_path, BRAWL, "--format=standardbrawl",
                     "--colours=BRG")
    assert "--- WU ---" in wide
    assert "--- WU ---" not in narrow
    assert "--- BR ---" in narrow


def test_the_narrowed_walk_says_what_it_narrowed_from(mm, tmp_path):
    """roster/--colours names the identity it is not walking

    Otherwise a reader cannot tell a narrowed walk from a commander with
    three colours.
    """
    out = _roster(mm, tmp_path, BRAWL, "--colours=BRG")
    assert "=== ROSTER WALK: Terra, Magical Adept (BRG) ===" in out
    assert ("walking BRG, not the commander's identity WUBRG -- --colours "
            "narrowed it.") in out


def test_colours_cannot_widen_past_the_identity(mm, tmp_path):
    """roster/--colours refuses a colour outside the identity

    Every row it would add is ILLEGAL in the deck. Printed under a flag the
    caller typed, they read as slots that could be filled.
    """
    out = _roster(mm, tmp_path, MULTI, "--colours=WUBG")
    assert "is outside the commander's identity (UBG)" in out
    assert "The flag narrows the walk; it cannot widen it." in out


def test_no_colours_walks_the_identity(mm, tmp_path):
    """roster/without --colours the walk is the identity, unchanged"""
    out = _roster(mm, tmp_path, MULTI)
    assert "=== ROSTER WALK: Muldrotha, the Gravetide (UBG) ===" in out
    assert "--colours narrowed it" not in out


@pytest.mark.parametrize("spec", ["BRX", "C", "X"],
                         ids=["roster/--colours refuses a typo",
                              "roster/--colours refuses colourless",
                              "roster/--colours refuses a non-colour"])
def test_colours_refuses_a_letter_that_is_not_a_colour(mm, tmp_path, spec):
    """Found in review: unrecognised letters were dropped without a word, so
    `--colours C` walked nothing and printed `ROSTER WALK: ... ()` -- an empty
    walk that looks like a result, and a typo quietly narrowed the walk."""
    out = _roster(mm, tmp_path, BRAWL, f"--colours={spec}")
    assert "is not a colour" in out
    assert "=== ROSTER WALK" not in out


def test_colours_is_case_insensitive(mm, tmp_path):
    """roster/--colours brg is the same walk as --colours BRG"""
    out = _roster(mm, tmp_path, BRAWL, "--colours=brg")
    assert "=== ROSTER WALK: Terra, Magical Adept (BRG) ===" in out
