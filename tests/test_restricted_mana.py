"""build_accel_profiles' restricted-mana handling.

"Spend this mana only to cast Dwarf spells" is not mana for a generic
on-curve figure. Counting it is how a restricted rock silently inflates a
number, and the flag is only worth having if the two models actually drop it.

Uses the real cards out of the frozen caches rather than invented oracle text:
Fíli and Kíli, Joyous taps for {R}{R} for Dwarf, Equipment and Saga spells
only; Delighted Halfling's coloured mana is legendary-only but its {C} is not.

Those two are the two halves of the rule and both are needed. A card whose
mana is restricted end to end is excluded; a card with one free line keeps
that line and is counted. Reading the restriction off the whole oracle text
collapses the second case into the first, which is what used to happen.
"""
import json
import os
import random

import pytest

from conftest import FIXTURES


@pytest.fixture(scope="module")
def mono_scry():
    with open(os.path.join(FIXTURES, "mono.scry.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def multi_scry():
    with open(os.path.join(FIXTURES, "multi.scry.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def colourless_scry():
    with open(os.path.join(FIXTURES, "colourless.scry.json"), encoding="utf-8") as f:
        return json.load(f)


def test_restricted_flag_is_set_from_real_oracle_text(mm, mono_scry):
    """restricted/Fíli and Kíli is flagged"""
    p = mm.build_accel_profiles(["Fíli and Kíli, Joyous"], mono_scry)
    assert len(p) == 1
    assert p[0]["restricted"] is True
    assert "spend this mana only" in mono_scry["fíli and kíli, joyous"]["oracle_text"].lower()


def test_partly_restricted_accelerant_keeps_its_free_line(mm, multi_scry):
    """restricted/Delighted Halfling keeps its {C}

    The flag is per LINE, not per card. Delighted Halfling taps for {C} with
    no strings and for any colour on legendary spells only, and the whole-text
    substring read that used to set this flag saw the second line and threw
    the card away -- a turn-one dork missing from the accelerant count
    entirely, while the identical two-line shape on a LAND (Cavern of Souls)
    was correctly counted as a {C} source.

    Both halves are asserted, because getting the flag right and the colours
    wrong is the other way to be wrong here: produced_mana lists all five
    colours plus {C} without saying what they may be spent on, so counting
    the card unrestricted while keeping that set would hand a legendary-only
    ability to every pip in the deck.
    """
    p = mm.build_accel_profiles(["Delighted Halfling"], multi_scry)
    assert len(p) == 1
    assert p[0]["restricted"] is False
    assert p[0]["colours"] == frozenset("C")
    assert set(multi_scry["delighted halfling"]["produced_mana"]) > {"C"}


def test_the_free_line_and_the_restricted_line_are_the_same_shape(mm,
                                                                  multi_scry):
    """restricted/land and accel agree on one card shape

    The bug was a DIVERGENCE, not a bad rule: the land path already read this
    per line and the accelerant path did not. Cavern of Souls and Delighted
    Halfling print the same two lines -- free {C}, then any colour with a
    restriction -- so if the two paths ever disagree again, they disagree
    here first.
    """
    land = mm.build_land_profiles(["Cavern of Souls"], multi_scry)
    accel = mm.build_accel_profiles(["Delighted Halfling"], multi_scry)
    assert len(land) == len(accel) == 1
    assert (land[0]["restricted"], land[0]["colours"]) == \
           (accel[0]["restricted"], accel[0]["colours"]) == \
           (False, frozenset("C"))


def test_unrestricted_accelerant_is_not_flagged(mm, mono_scry):
    """restricted/Sol Ring is not flagged"""
    p = mm.build_accel_profiles(["Sol Ring"], mono_scry)
    assert len(p) == 1
    assert p[0]["restricted"] is False


def test_restricted_amount_is_still_read(mm, mono_scry):
    """restricted/amount is still 2

    The flag excludes it from the totals; it does not pretend the card taps
    for less than it does. If a line genuinely qualifies you re-run with
    count_restricted and the 2 has to be right.
    """
    p = mm.build_accel_profiles(["Fíli and Kíli, Joyous"], mono_scry)
    assert p[0]["amount"] == 2


def test_an_unreadable_free_line_falls_back_to_produced_mana(mm, colourless_scry):
    """restricted/a free line with no readable colours keeps produced_mana

    unrestricted_mana reads colours off {w..c} symbols and the literal "any
    color". Real cards are worded past both -- Gilded Lotus taps for "three
    mana of any one color", Reflecting Pool for "one mana of any type that a
    land you control could produce" -- so a free line worded that way returns
    NO colours with a non-zero amount. Left alone that is a source counting
    toward the generic total that can pay no pip.

    The FIRST assertion is the one that keeps this honest: it pins that Gilded
    Lotus' real, printed line is genuinely unreadable to the parser, so the
    branch below is guarding a wording that exists rather than one invented to
    make a test pass. The second line -- the restriction -- is synthetic, and
    is the only synthetic part: no printed card combines the two, which is why
    nothing in the fixtures reaches this.
    """
    lotus = colourless_scry["gilded lotus"]["oracle_text"].lower()
    assert "any one color" in lotus
    assert mm.unrestricted_mana(lotus) == (set(), 3), "wording became readable"

    txt = lotus + "\n{t}: add {b}. spend this mana only to cast zombie spells."
    pm = {"W", "U", "B", "R", "G"}
    cols, amount, restricted = mm.drop_restricted(txt, pm, 1)
    assert restricted is False
    assert amount == 3
    assert cols == pm, "an unreadable free line must not empty the colour set"


# --- and the part that actually matters: both models must DROP it ---------
def _accel(restricted):
    return {"name": "rock", "kind": "accel", "colours": frozenset("R"),
            "filter": None, "omni": None, "amount": 1, "cost": 1,
            "tapped": False, "cond_tap": None, "restricted": restricted,
            "creature": False, "mdfc": False}


def _land():
    return {"name": "mountain", "kind": "land", "colours": frozenset("R"),
            "filter": None, "omni": None, "amount": 1, "tapped": False,
            "cond_tap": None, "mdfc": False}


def test_probability_excludes_restricted_by_default(mm):
    """restricted/probability drops it

    20 lands and 79 restricted accelerants, asking for five mana on turn five.
    Counting only the lands, five sources in eleven cards is a long shot;
    counting the restricted rocks too, every card drawn is a source and the
    only remaining question is whether a land showed up. The gap between the
    two is the whole point of the flag.

    The first draft of this test used one land and 98 accelerants and asserted
    the counted figure was >0.9. It came out at 0.08 -- not a bug, a bad
    premise: with one land in the deck the "at least one land" requirement
    caps the answer at about 9% however much mana the rocks make.
    """
    lands = [_land() for _ in range(20)]
    accels = [_accel(True) for _ in range(79)]
    off = mm.probability(lands, accels, 99, ["R"], 5, 5, 800, random.Random(9))
    on = mm.probability(lands, accels, 99, ["R"], 5, 5, 800, random.Random(9),
                        count_restricted=True)
    assert off < 0.15, off
    assert on > 0.85, on


def test_playsim_excludes_restricted_by_default(mm):
    """restricted/playsim drops it"""
    lands = [_land() for _ in range(20)]
    accels = [_accel(True) for _ in range(79)]
    off = mm.playsim(lands, accels, 99, 4, False, 200, random.Random(9))
    on = mm.playsim(lands, accels, 99, 4, False, 200, random.Random(9),
                    count_restricted=True)
    mean_off = sum(sum(p.get("amount", 1) for p in s) for s in off[4]) / 200
    mean_on = sum(sum(p.get("amount", 1) for p in s) for s in on[4]) / 200
    assert mean_on > mean_off + 1.0, (mean_off, mean_on)


def test_report_mana_names_the_excluded_accelerants(mm, mono_scry, capsys):
    """restricted/report names what it excluded

    Excluding it silently would be its own failure: the figure would be right
    and unexplained. The line says which cards were dropped.
    """
    accels = mm.build_accel_profiles(["Fíli and Kíli, Joyous", "Sol Ring"], mono_scry)
    restricted = [a["name"] for a in accels if a.get("restricted")]
    assert restricted == ["fíli and kíli, joyous"]
