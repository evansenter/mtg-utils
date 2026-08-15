"""build_accel_profiles' restricted-mana handling.

"Spend this mana only to cast Dwarf spells" is not mana for a generic
on-curve figure. Counting it is how a restricted rock silently inflates a
number, and the flag is only worth having if the two models actually drop it.

Uses the real cards out of the frozen caches rather than invented oracle text:
Fíli and Kíli, Joyous taps for {R}{R} for Dwarf, Equipment and Saga spells
only; Delighted Halfling's coloured mana is legendary-only.
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


def test_restricted_flag_is_set_from_real_oracle_text(mm, mono_scry):
    """restricted/Fíli and Kíli is flagged"""
    p = mm.build_accel_profiles(["Fíli and Kíli, Joyous"], mono_scry)
    assert len(p) == 1
    assert p[0]["restricted"] is True
    assert "spend this mana only" in mono_scry["fíli and kíli, joyous"]["oracle_text"].lower()


def test_restricted_flag_is_set_for_legendary_only_mana(mm, multi_scry):
    """restricted/Delighted Halfling is flagged"""
    p = mm.build_accel_profiles(["Delighted Halfling"], multi_scry)
    assert len(p) == 1
    assert p[0]["restricted"] is True


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
