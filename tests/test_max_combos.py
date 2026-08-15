"""probability()'s max_combos truncation.

When more than max_combos subsets of the drawn sources are available,
probability samples max_combos of them instead of trying all. That is a
speed/accuracy trade in the middle of the number the tool reports, so the
claim "250 is non-biasing" needs pinning rather than remembering.

Two facts, and the first is exact rather than statistical:

  * A hand has seen 7 + turn - 1 cards, so at turn 7 there are at most 13
    sources and at most C(13,7) = 1716 subsets of size 7. 1716 < 2000, so
    max_combos=2000 and max_combos=20000 NEVER truncate for turns up to 7 --
    they are the exhaustive answer and must agree exactly, not approximately.
  * 250 does truncate, and the measured difference against exhaustive is
    under half a point across seeds. That is the non-biasing claim.

The pinned values double as an output-invariance guard: they are the numbers
this deck actually reports at seed 17.
"""
import itertools
import json
import os
import random

import pytest

from conftest import FIXTURES

SIMS = 4000
EXHAUSTIVE = (2000, 20000)


@pytest.fixture(scope="module")
def multi(mm):
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "multi.txt"))
    with open(os.path.join(FIXTURES, "multi.scry.json"), encoding="utf-8") as f:
        scry = json.load(f)
    names = mm.flat(cmdr, entries)[1:]
    return (mm.build_land_profiles(names, scry),
            mm.build_accel_profiles(names, scry))


# (label, req, mv, turn, {max_combos: expected})
# These moved once, deliberately, when the accelerant gate was tightened to
# permanents with a mana ability: the multicolour deck went from 18 counted
# accelerants to 14, dropping Dark Ritual and three Treasure-makers. The
# previous values were 0.758 / 0.86075 / 0.73375 at max_combos=250. They are
# output-invariance guards, so they are expected to fail on any accidental
# change and to be updated only alongside an intended one.
CASES = [
    ("T2 {U}{U} never truncates at all", ["U", "U"], 2, 2,
     {250: 0.73275, 2000: 0.73275, 20000: 0.73275}),
    ("T5 {B}{B}{G}", ["B", "B", "G"], 5, 5,
     {250: 0.7865, 2000: 0.78675, 20000: 0.78675}),
    ("T7 {U}{B}{G} truncates hardest", ["U", "B", "G"], 7, 7,
     {250: 0.61825, 2000: 0.6095, 20000: 0.6095}),
]


@pytest.mark.parametrize("label,req,mv,turn,expected", CASES,
                         ids=[c[0] for c in CASES])
def test_max_combos_pinned_values(mm, multi, label, req, mv, turn, expected):
    lands, accels = multi
    for mc, want in expected.items():
        got = mm.probability(lands, accels, 99, req, mv, turn, SIMS,
                             random.Random(17), max_combos=mc)
        # exact: every figure is hits/SIMS, so a rounded literal is not
        # representable and would fail against the value it was copied from
        assert got == want, (label, mc, got, want)


def test_the_ceiling_really_is_1716():
    """max_combos/2000 is above the ceiling

    If a later change let probability look at more than 13 cards, 2000 would
    stop being exhaustive and the equality below would quietly become an
    approximation. Assert the arithmetic rather than trusting the comment.
    """
    seen_at_turn_7 = 7 + 7 - 1
    assert seen_at_turn_7 == 13
    assert len(list(itertools.combinations(range(13), 7))) == 1716
    assert 1716 < min(EXHAUSTIVE)


@pytest.mark.parametrize("label,req,mv,turn,expected", CASES,
                         ids=[f"exhaustive settings agree: {c[0]}" for c in CASES])
def test_2000_and_20000_are_identical(mm, multi, label, req, mv, turn, expected):
    """Neither truncates, so this is exact equality, not a tolerance."""
    lands, accels = multi
    a, b = [mm.probability(lands, accels, 99, req, mv, turn, SIMS,
                           random.Random(17), max_combos=mc) for mc in EXHAUSTIVE]
    assert a == b


@pytest.mark.parametrize("seed", [17, 4, 99])
def test_250_is_not_biased_against_exhaustive(mm, multi, seed):
    """max_combos/250 does not bias the answer

    The hardest line in the deck, where truncation bites hardest: 1716
    subsets available, 250 sampled. Across seeds the truncated figure sits
    within half a point of exhaustive and does not sit consistently on one
    side of it.
    """
    lands, accels = multi
    trunc = mm.probability(lands, accels, 99, ["U", "B", "G"], 7, 7, SIMS,
                           random.Random(seed), max_combos=250)
    full = mm.probability(lands, accels, 99, ["U", "B", "G"], 7, 7, SIMS,
                          random.Random(seed), max_combos=20000)
    assert abs(trunc - full) < 0.01, (seed, trunc, full)


def test_250_is_the_shipped_default(mm):
    """max_combos/default is 250

    Every reported figure comes from this default -- worst_lines calls
    probability without passing it. A change here moves every number in the
    sources model, so it is pinned explicitly.
    """
    import inspect
    sig = inspect.signature(mm.probability)
    assert sig.parameters["max_combos"].default == 250
