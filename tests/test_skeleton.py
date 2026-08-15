"""The skeleton: the slot budget, asserted rather than printed.

Deciding land count, non-land count and the per-category budget BEFORE
selecting cards is what prevents repeated rebuilds, and nothing printed it --
so every skeleton was hand arithmetic. Hand arithmetic has already shipped a
header block reading "24 lands plus 75 non-land" for a 100-card deck: the
commander was missing from the sum and nothing caught it.

Hence the shape of these cases. The identity `100 = commanders + lands +
non-land` is checked in `deck_skeleton` and RAISES when it does not hold, so
the printed line is a statement rather than arithmetic for a reader to
re-do. A test that only scraped the printed line would be testing the very
thing that failed last time.
"""
import json
import os

import pytest

from conftest import DECKS, FIXTURES, deck_args, run_cli


def _deck(mm, name):
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, f"{name}.txt"))
    with open(os.path.join(FIXTURES, f"{name}.scry.json"), encoding="utf-8") as f:
        return cmdr, entries, json.load(f)


# --- the identity -----------------------------------------------------
@pytest.mark.parametrize("deck", DECKS)
def test_the_identity_closes(mm, deck):
    """100 = commanders + lands + non-land, on every shape including the
    partner pair, where the commander count is two and the library is 98."""
    cmdr, entries, scry = _deck(mm, deck)
    s = mm.deck_skeleton(cmdr, entries, scry)
    assert s["commanders"] + s["lands"] + s["nonland"] == s["total"]
    assert s["total"] == 100
    assert s["commanders"] == len(mm.as_cmdrs(cmdr))


def test_an_unaccounted_card_raises(mm):
    """A name Scryfall cannot resolve lands in NO category -- `verify` skips
    it -- so the parts stop summing to the total. That is the exact shape of
    the bug this command exists to prevent, so it must be an error and not a
    quietly wrong header.
    """
    cmdr, entries, scry = _deck(mm, "mono")
    entries = dict(entries)
    entries["Definitely Not A Real Card"] = 1
    with pytest.raises(SystemExit) as e:
        mm.deck_skeleton(cmdr, entries, scry)
    msg = str(e.value)
    assert "Definitely Not A Real Card" in msg
    assert "no category" in msg


def test_the_raise_names_the_arithmetic(mm):
    """The message has to show the sum that failed, not just that one did --
    otherwise the reader is back to doing the arithmetic by hand."""
    cmdr, entries, scry = _deck(mm, "mono")
    entries = dict(entries)
    entries["Another Fake Card"] = 1
    with pytest.raises(SystemExit) as e:
        mm.deck_skeleton(cmdr, entries, scry)
    msg = str(e.value)
    assert "commander" in msg and "lands" in msg and "non-land" in msg


# --- the curve --------------------------------------------------------
@pytest.mark.parametrize("deck", DECKS)
def test_the_curve_counts_every_non_land_once(mm, deck):
    cmdr, entries, scry = _deck(mm, deck)
    s = mm.deck_skeleton(cmdr, entries, scry)
    assert sum(s["curve"].values()) == s["nonland"]


def test_lands_are_not_in_the_curve(mm):
    """A 37-land deck with lands in the curve would show a mountain at MV 0
    and read as an absurdly cheap list."""
    cmdr, entries, scry = _deck(mm, "multi")
    s = mm.deck_skeleton(cmdr, entries, scry)
    assert s["curve"].get(0, 0) < s["lands"]
    assert sum(s["curve"].values()) + s["lands"] + s["commanders"] == s["total"]


def test_the_top_bucket_gathers_everything_above_it(mm):
    """`7+` is a bucket, not a slot: an eight-drop belongs in it, and a curve
    that silently dropped one would understate the top end."""
    entries = {"Sol Ring": 1, "Expropriate": 1, "Blightsteel Colossus": 1}
    scry = {
        "sol ring": {"type_line": "Artifact", "cmc": 1,
                     "legalities": {"commander": "legal"}, "color_identity": []},
        "expropriate": {"type_line": "Sorcery", "cmc": 9,
                        "legalities": {"commander": "legal"}, "color_identity": []},
        "blightsteel colossus": {"type_line": "Artifact Creature — Golem", "cmc": 12,
                                 "legalities": {"commander": "legal"},
                                 "color_identity": []},
        "cmdr": {"type_line": "Creature — Human", "cmc": 2,
                 "legalities": {"commander": "legal"}, "color_identity": []},
    }
    s = mm.deck_skeleton("Cmdr", entries, scry)
    assert s["curve"][mm.CURVE_TOP] == 2, s["curve"]
    assert s["curve"][1] == 1


# --- type buckets -----------------------------------------------------
@pytest.mark.parametrize("type_line,want", [
    ("Land", "Land"),
    ("Basic Land — Island", "Land"),
    ("Artifact Creature — Golem", "Creature"),
    ("Legendary Creature — Human Cleric", "Creature"),
    ("Artifact — Equipment", "Artifact"),
    ("Instant", "Instant"),
    ("Sorcery", "Sorcery"),
    ("Legendary Planeswalker — Teferi", "Planeswalker"),
    ("Sorcery // Land", "Sorcery"),
    ("Land // Sorcery", "Land"),
], ids=["bucket/land", "bucket/basic", "bucket/artifact creature is a creature",
        "bucket/legendary creature", "bucket/equipment is an artifact",
        "bucket/instant", "bucket/sorcery", "bucket/planeswalker",
        "bucket/MDFC spell front", "bucket/MDFC land front"])
def test_type_bucket(mm, type_line, want):
    """An Artifact Creature is a CREATURE slot: that is the slot you are
    budgeting when you write down "10 creatures". The MDFC pair is the point
    of reading the front face only -- the land back is already counted by
    verify, and counting it twice would break the identity."""
    assert mm.type_bucket(type_line) == want


@pytest.mark.parametrize("deck", DECKS)
def test_types_cover_the_non_commander_cards(mm, deck):
    """The buckets partition the 99 (or 98), not the 100 -- commanders are
    their own line in the identity and must not be double-counted."""
    cmdr, entries, scry = _deck(mm, deck)
    s = mm.deck_skeleton(cmdr, entries, scry)
    assert sum(s["types"].values()) == s["total"] - s["commanders"]


def test_skeleton_buckets_are_not_the_buy_list_buckets(mm):
    """`own` splits Equipment out because that is how a buy list reads, and
    skips basics because ManaBox does not track them. A skeleton needs
    neither: Equipment is an artifact slot, and basics are most of the
    manabase. The two lists look alike and must not be merged."""
    assert mm.type_bucket("Artifact — Equipment") == "Artifact"
    assert mm.type_bucket("Basic Land — Mountain") == "Land"
    assert "Equipment" not in mm.SKELETON_TYPES


# --- the accelerant count ---------------------------------------------
@pytest.mark.parametrize("deck", DECKS)
def test_the_accelerant_count_is_the_measured_one(mm, deck):
    """The one functional count in the report, and it comes from the same
    gate the mana models use rather than from a fresh guess. Restricted mana
    is excluded, exactly as `mana` excludes it."""
    cmdr, entries, scry = _deck(mm, deck)
    s = mm.deck_skeleton(cmdr, entries, scry)
    names = mm.flat(cmdr, entries)[len(mm.as_cmdrs(cmdr)):]
    want = [a for a in mm.build_accel_profiles(names, scry)
            if not a.get("restricted")]
    assert s["accelerants"] == len(want)
    assert s["accelerants"] > 0, "fixture no longer exercises this"


# --- the report -------------------------------------------------------
@pytest.mark.parametrize("deck", DECKS)
def test_the_report_states_the_identity(mm, deck, tmp_path):
    cmdr, entries, scry = _deck(mm, deck)
    s = mm.deck_skeleton(cmdr, entries, scry)
    out = run_cli(mm, deck_args(deck, "skeleton"), str(tmp_path))
    noun = "commander" if s["commanders"] == 1 else "commanders"
    assert (f"{s['total']} = {s['commanders']} {noun} + {s['lands']} lands"
            f" + {s['nonland']} non-land") in out
    # Both manabase levers on one line: they are the pair you trade against
    # each other before choosing a single card.
    assert f"{s['lands']} lands" in out
    assert f"{s['accelerants']} accelerants at MV<=3" in out


def test_the_report_disclaims_functional_roles(mm, tmp_path):
    """Type lines are what can be counted. Ramp, draw and interaction are
    what a skeleton actually budgets, and inferring them needs a heuristic
    this repo would have to invent -- so they are absent and SAID to be
    absent, rather than approximated."""
    out = run_cli(mm, deck_args("mono", "skeleton"), str(tmp_path))
    assert "not inferred" in out
    assert "ramp/draw/interaction" in out
