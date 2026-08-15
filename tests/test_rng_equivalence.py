"""The reimplemented draws must consume the stdlib's bits, exactly.

`castability` deals cards without calling `random.shuffle` or `random.sample`,
because both do work the models throw away: a 99-card shuffle to look at
fourteen cards, a `sample` result list that is filtered on the next line. The
copies skip that work and nothing else.

"Nothing else" is the entire claim, and it is not a claim you can check by
reading -- every figure this tool reports is a Monte Carlo mean, so one bit
drawn out of turn moves every snapshot in tests/fixtures/expected/ by a
fraction of a point that still looks like a probability. So it is measured
here, against the stdlib, two ways at once:

  * the cards dealt are the cards the stdlib would have dealt, and
  * the generator is left in the same state, which is what makes the NEXT
    trial agree as well. The state check is the one that matters and the one
    a reimplementation gets wrong: a partial shuffle that stops early deals
    the right opening hand and then quietly desynchronises every trial after
    it.

If a future interpreter changes either algorithm this fails here, naming the
cause, instead of moving four decks' worth of probabilities under a green
suite.
"""
import random

import pytest

from mtg_utils.castability import _sample_hits, _shuffle_plan


def _deal(rng, deck, m):
    """The top `m` of `deck`, as playsim deals them, plus the RNG state."""
    n = len(deck)
    head, tail = _shuffle_plan(n, m)
    getrandbits = rng.getrandbits
    x = deck[:]
    for i, k, b in head:
        j = getrandbits(b)
        while j >= k:
            j = getrandbits(b)
        x[i], x[j] = x[j], x[i]
    for k, b in tail:
        j = getrandbits(b)
        while j >= k:
            j = getrandbits(b)
    return [x[n - 1 - i] for i in range(m)], rng.getstate()


def _stdlib_deal(rng, deck, m):
    lib = deck[:]
    rng.shuffle(lib)
    return [lib.pop() for _ in range(m)], rng.getstate()


# 99 and 98 are the real library sizes (one commander, and a partner pair);
# the rest bracket them, including the powers of two where `getrandbits`
# never has to reject a draw and the sizes either side where it usually does.
@pytest.mark.parametrize("n", [2, 3, 8, 16, 17, 31, 32, 33, 64, 98, 99, 100])
@pytest.mark.parametrize("m", [1, 7, 14])
def test_partial_shuffle_deals_what_shuffle_deals(n, m):
    if m > n:
        pytest.skip("more cards than deck")
    deck = list(range(n))
    got, got_state = _deal(random.Random(4), deck, m)
    want, want_state = _stdlib_deal(random.Random(4), deck, m)
    assert got == want, (n, m)
    # The generator must also be left where a full shuffle would leave it:
    # playsim runs tens of thousands of trials off one Random.
    assert got_state == want_state, (n, m)


def test_partial_shuffle_stays_in_step_over_many_trials():
    """The per-trial check above passes even for a copy that drains the wrong
    number of bits on ONE size, because each trial restarts from a fresh seed.
    This one shares a generator across trials the way playsim does, which is
    where a desynchronised copy actually shows up."""
    deck = list(range(99))
    a, b = random.Random(11), random.Random(11)
    for trial in range(200):
        got, _ = _deal(a, deck, 13)
        want, _ = _stdlib_deal(b, deck, 13)
        assert got == want, trial


# k spans `sample`'s two strategies, which consume different bits: it builds a
# set above a size threshold and shuffles a pool below it. A copy of only one
# of them is right until a deck size crosses the line.
@pytest.mark.parametrize("n,k", [(99, 7), (99, 13), (98, 10), (40, 5),
                                 (20, 20), (12, 3), (85, 7), (86, 7),
                                 (60, 6), (60, 30), (5, 5), (2, 1)])
def test_sample_hits_matches_random_sample(n, k):
    limit = max(1, n // 2)
    a, b = random.Random(7), random.Random(7)
    got = _sample_hits(a.getrandbits, n, k, limit)
    want = [v for v in b.sample(range(n), k) if v < limit]
    assert got == want, (n, k)
    assert a.getstate() == b.getstate(), (n, k)


def test_sample_hits_stays_in_step_over_many_draws():
    """Same reason as the shuffle case: one generator, many draws."""
    a, b = random.Random(3), random.Random(3)
    for draw in range(300):
        got = _sample_hits(a.getrandbits, 99, 13, 45)
        want = [v for v in b.sample(range(99), 13) if v < 45]
        assert got == want, draw


def test_sample_hits_keeps_every_value_when_nothing_is_filtered():
    """`limit` is the only thing that distinguishes this from `sample`, so the
    unfiltered case has to reproduce the whole draw and its order -- a copy
    that returned a set, or sorted, would pass every test above."""
    a, b = random.Random(21), random.Random(21)
    assert _sample_hits(a.getrandbits, 99, 13, 99) == b.sample(range(99), 13)
