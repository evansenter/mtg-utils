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

# The non-bias check gets its own, larger budget, and it is not a preference.
# At SIMS=4000 the PAIRED difference between the truncated and the exhaustive
# figure has an sd of about 0.0066 across seeds, so a per-seed tolerance of
# 0.01 is roughly 1.5 sd -- it is a coin flip on noise, not a measurement of
# bias, and it passed only because these three seeds happened to land inside
# it. Counting Delighted Halfling put one more source in the turn-7 hand, the
# gap at seed 17 came out at exactly 0.0100, and the test failed with nothing
# actually wrong. At 20000 the sd is 0.0034 and the three seeds sit at 0.0033,
# 0.0010 and 0.0005, so the same tolerance is a real guard: half a point of
# genuine bias would trip it.
#
# Cost, measured rather than estimated, because it is easy to multiply wrong:
# 2.1s for the WHOLE case -- three seeds, two probability() calls each, so six
# 20000-sim runs -- up from 0.4s. That is the total added to the suite, not a
# per-seed or per-call figure.
BIAS_SIMS = 20000


@pytest.fixture(scope="module")
def multi(mm):
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "multi.txt"))
    with open(os.path.join(FIXTURES, "multi.scry.json"), encoding="utf-8") as f:
        scry = json.load(f)
    names = mm.flat(cmdr, entries)[1:]
    return (mm.build_land_profiles(names, scry),
            mm.build_accel_profiles(names, scry))


# (label, req, mv, turn, {max_combos: expected})
# These have moved twice, deliberately, both times because the multicolour
# deck's accelerant COUNT changed:
#
#   18 -> 14  the accelerant gate was tightened to permanents with a mana
#             ability, dropping Dark Ritual and three Treasure-makers.
#             Values were 0.758 / 0.86075 / 0.73375 at max_combos=250.
#   13 -> 14  restricted mana was read per LINE rather than per card, so
#             Delighted Halfling stopped being excluded outright and started
#             counting as the {C} dork it is. (The 14 above is a different
#             14: that pass also counted a card this one does not.)
#             Values were 0.73275 / 0.7865 / 0.61825 at max_combos=250.
#
# They are output-invariance guards, so they are expected to fail on any
# accidental change and to be updated only alongside an intended one.
CASES = [
    ("T2 {U}{U} never truncates at all", ["U", "U"], 2, 2,
     {250: 0.73675, 2000: 0.73675, 20000: 0.73675}),
    ("T5 {B}{B}{G}", ["B", "B", "G"], 5, 5,
     {250: 0.80425, 2000: 0.8045, 20000: 0.8045}),
    ("T7 {U}{B}{G} truncates hardest", ["U", "B", "G"], 7, 7,
     {250: 0.6525, 2000: 0.6425, 20000: 0.6425}),
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
    subsets available, 250 sampled. Over 30 seeds at BIAS_SIMS the truncated
    figure lands on either side of exhaustive 15 times each, which is the
    part that makes it non-bias rather than merely small. Three seeds cannot
    assert that, so it is measured and written down rather than claimed by a
    test that could not fail on it.

    The measured gap and the tolerance are deliberately different numbers.
    OBSERVED at these three seeds: 0.0033, 0.0010, 0.0005 -- comfortably
    inside half a point. The GUARD trips at one point, which is looser on
    purpose: a per-seed figure moves whenever an unrelated change shifts what
    the shared rng stream deals, as adding one accelerant to this deck did,
    and a tolerance pinned to the observation would fail on that without any
    bias existing. One point is wide enough to survive a stream shift and
    still narrow enough that real truncation bias -- which would be a
    consistent half point or more, in one direction -- trips it.
    """
    lands, accels = multi
    trunc = mm.probability(lands, accels, 99, ["U", "B", "G"], 7, 7, BIAS_SIMS,
                           random.Random(seed), max_combos=250)
    full = mm.probability(lands, accels, 99, ["U", "B", "G"], 7, 7, BIAS_SIMS,
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
