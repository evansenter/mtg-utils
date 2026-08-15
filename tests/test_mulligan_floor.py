"""No mulligan is modelled, and `mana` now says so with a measured size.

`playsim` deals seven and never looks back, so every opening hand is kept --
zero-land hands included. Real play mulligans, which makes every play-
simulation figure a FLOOR rather than an estimate, and the output used to read
as a complete play model.

The size is the point. Roughly one hand in seven on a 40-land deck, and more
than one in three on the 27-land colourless fixture. Because it moves with
land count it does not merely lower every number -- it skews decks against
each other, and `calibrate` puts decks side by side in one table.

Measured exactly rather than simulated: the opening hand is a counting
question. It is NOT a castability figure and the cases here pin that it is
never presented as one.
"""
import json
import math
import os

import pytest

from conftest import DECKS, FIXTURES, deck_args, run_cli


def _deck(mm, name):
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, f"{name}.txt"))
    with open(os.path.join(FIXTURES, f"{name}.scry.json"), encoding="utf-8") as f:
        return cmdr, entries, json.load(f)


def _exact(k, lands, deck, hand=7):
    """P(exactly k lands in the opening hand), computed independently.

    Deliberately not written in terms of at_least_in_draw: a test that reuses
    the function it checks asserts only that the code equals itself.
    """
    return (math.comb(lands, k) * math.comb(deck - lands, hand - k)
            / math.comb(deck, hand))


@pytest.mark.parametrize("lands,deck", [(36, 99), (40, 99), (27, 99), (39, 98)],
                         ids=["floor/mono 36", "floor/multi 40",
                              "floor/colourless 27", "floor/partner 98-card"])
def test_the_floor_matches_an_independent_computation(mm, lands, deck):
    f = mm.opening_hand_floor(lands, deck)
    assert f["p_none"] == pytest.approx(_exact(0, lands, deck))
    assert f["p_one_or_fewer"] == pytest.approx(
        _exact(0, lands, deck) + _exact(1, lands, deck))


def test_a_landless_deck_never_keeps(mm):
    f = mm.opening_hand_floor(0, 99)
    assert f["p_none"] == pytest.approx(1.0)
    assert f["p_one_or_fewer"] == pytest.approx(1.0)


def test_an_all_land_deck_always_keeps(mm):
    f = mm.opening_hand_floor(99, 99)
    assert f["p_none"] == pytest.approx(0.0)
    assert f["p_one_or_fewer"] == pytest.approx(0.0)


def test_the_floor_shrinks_as_land_count_rises(mm):
    """The deck-dependence is the reason this is printed rather than
    described. A 27-land list ships back nearly three times as many hands as
    a 40-land one, so the bias skews decks against each other and not just
    the level of each -- which is what makes it a problem for `calibrate`,
    where decks sit side by side in one table.
    """
    floors = [mm.opening_hand_floor(L, 99)["p_one_or_fewer"]
              for L in (27, 33, 36, 40, 45)]
    assert floors == sorted(floors, reverse=True), floors
    assert floors[0] > 2.5 * floors[-1], floors


def test_mdfc_land_backs_count_toward_keepability(mm):
    """An MDFC back is a land you can play, so a hand holding one is not a
    one-lander. The multi fixture has three, and ignoring them would report
    a floor for a 37-land deck that is actually a 40-land deck."""
    cmdr, entries, scry = _deck(mm, "multi")
    a = mm.analyse_mana(cmdr, entries, scry, sims=20, trials=20, reps=1)
    v = a["verify"]
    assert v["mdfc_land_backs"] > 0, "fixture no longer exercises this"
    assert a["floor"]["lands"] == v["lands"] + v["mdfc_land_backs"]


def test_the_floor_is_drawn_from_the_real_library(mm):
    """A partner deck has 98 cards behind its two commanders. Drawing the
    opening hand from 99 is the same off-by-one the play simulation already
    had fixed."""
    cmdr, entries, scry = _deck(mm, "partner")
    a = mm.analyse_mana(cmdr, entries, scry, sims=20, trials=20, reps=1)
    assert a["floor"]["deck_size"] == 98


@pytest.mark.parametrize("deck", DECKS)
def test_mana_states_the_floor_and_labels_it(mm, deck, tmp_path):
    """The figure has to be unmistakably about the opening hand.

    Every other percentage in this report is a castability or on-curve
    number, and `hypergeometric` was renamed precisely because a bare
    probability is easy to paste into a primer as though it were one.
    """
    out = run_cli(mm, deck_args(deck, "mana", ["--trials=900", "--sims=300"]),
                  str(tmp_path))
    assert "No mulligan is modelled" in out
    assert "FLOORS" in out
    assert "of opening sevens hold at most one land" in out
    # Stated after the play-simulation table, so it reads as a caveat on
    # those figures rather than as another row of them.
    assert out.index("play simulation") < out.index("No mulligan is modelled")


def test_the_printed_floor_is_the_computed_one(mm, tmp_path):
    """Asserted against the computation rather than eyeballed, so a format
    change cannot quietly print a different number than the one measured."""
    cmdr, entries, scry = _deck(mm, "colourless")
    a = mm.analyse_mana(cmdr, entries, scry, sims=20, trials=20, reps=1)
    out = run_cli(mm, deck_args("colourless", "mana",
                                ["--trials=900", "--sims=300"]), str(tmp_path))
    assert f"{a['floor']['p_one_or_fewer']*100:.1f}% of opening sevens" in out
    assert f"({a['floor']['p_none']*100:.1f}% hold none)" in out
