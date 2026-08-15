"""The rewritten pip solver must answer what the old one answered.

`castable` was an augmenting-path search over colour SETS, called afresh every
time. It is now Hall's condition over colour BITMASKS, behind a memo keyed on
an interned, packed hand. That is three separate rewrites of the one function
every reported castability figure runs through, and the golden snapshots only
exercise the hands four particular decks happen to deal.

So the old implementation is kept here, verbatim from the commit before the
rewrite (4db2aa5, `mtg_utils/castability.py`), and the two are compared over
hands generated on purpose to be awkward: filter lands that must be paired,
omni lands that colour other lands but not rocks, multi-mana sources,
colourless sources, and costs with hybrid pips. A disagreement on any of them
is a moved number that no snapshot would have caught.

It is not a slow test -- a few thousand comparisons of a function built to be
called millions of times.
"""
import random

import pytest

from mtg_utils.castability import _match, castable


# --------------------------------------------------------------------------
# The pre-rewrite implementation, verbatim. Do not "tidy" it: its value is
# that it was not written with the new one in view.
# --------------------------------------------------------------------------
def ref_match(units, req):
    matched = [-1] * len(units)

    def try_assign(i, seen):
        for j, u in enumerate(units):
            if j in seen or not (set(req[i]) & u):
                continue
            seen.add(j)
            if matched[j] == -1 or try_assign(matched[j], seen):
                matched[j] = i
                return True
        return False

    for i in range(len(req)):
        if not try_assign(i, set()):
            return False
    return True


def ref_castable(sources, req, mv):
    total = sum(p.get("amount", 1) for p in sources)
    if total < mv:
        return False
    if not req:
        return True

    omni = set(p["omni"] for p in sources if p.get("omni")) - {None}

    def cols(p):
        if omni and p.get("kind", "land") == "land":
            return set(p["colours"]) | omni
        return set(p["colours"])

    filters = [p for p in sources if p.get("filter")]
    others = [p for p in sources if not p.get("filter")]
    activated = set()

    def recurse(idx, used):
        if idx == len(filters):
            units = []
            for j, p in enumerate(others):
                if j in used:
                    continue
                for _ in range(p.get("amount", 1)):
                    units.append(cols(p))
            for k, f in enumerate(filters):
                pair = set(f["filter"])
                if k in activated:
                    units.append(pair); units.append(pair)
                else:
                    units.append({"C"})
            return ref_match(units, req)
        f = filters[idx]
        pair = set(f["filter"])
        activated.discard(idx)
        if recurse(idx + 1, used):
            return True
        for j, p in enumerate(others):
            if j in used or not (cols(p) & pair):
                continue
            activated.add(idx)
            if recurse(idx + 1, used | {j}):
                return True
            activated.discard(idx)
        return False

    return recurse(0, frozenset())


# --------------------------------------------------------------------------
COLOURS = "WUBRG"
FILTER_PAIRS = ("WU", "UB", "BR", "RG", "GW", "WB", "UR", "BG", "RW", "GU")


def _source(rng, tag):
    """One profile. `tag` keeps signatures apart from other tests' hands.

    The mix is deliberate, not uniform. Filter lands and omni lands are each
    about one source in six, and rocks are usually COLOURLESS -- because the
    shape that has actually shipped a wrong number here is Urborg beside a Sol
    Ring, where the omni colour must reach every land and no rock at all. A
    generator that made that hand once in a thousand would agree with the old
    solver about everything except the bug.
    """
    roll = rng.random()
    if roll < 0.16:                                   # filter land
        return {"colours": frozenset(rng.choice(FILTER_PAIRS)),
                "filter": rng.choice(FILTER_PAIRS), "omni": None,
                "amount": 1, "kind": "land", "tapped": False, "tag": tag}
    if roll < 0.32:                                   # Urborg / Yavimaya
        return {"colours": frozenset(rng.choice(COLOURS)), "filter": None,
                "omni": rng.choice(COLOURS), "amount": 1, "kind": "land",
                "tapped": False, "tag": tag}
    if roll < 0.56:                                   # a rock, usually {C}
        cols = "" if rng.random() < 0.6 else rng.sample(list(COLOURS + "C"), 1)
        return {"colours": frozenset(cols), "filter": None, "omni": None,
                "amount": rng.randint(1, 3), "kind": "accel",
                "tapped": False, "tag": tag}
    return {"colours": frozenset(rng.sample(list(COLOURS + "C"),
                                            rng.randint(0, 3))),
            "filter": None, "omni": None, "amount": rng.randint(1, 2),
            "kind": "land", "tapped": False, "tag": tag}


def _cost(rng):
    pips = []
    for _ in range(rng.randint(1, 5)):
        r = rng.random()
        if r < 0.12:
            pips.append("C")
        elif r < 0.24:                                # a hybrid pip
            pips.append("".join(rng.sample(list(COLOURS), 2)))
        else:
            pips.append(rng.choice(COLOURS))
    return pips


@pytest.mark.parametrize("seed", range(12))
def test_castable_matches_the_pre_rewrite_solver(seed):
    rng = random.Random(seed)
    disagreements = []
    for case in range(220):
        sources = [_source(rng, "eq") for _ in range(rng.randint(0, 8))]
        req = _cost(rng)
        mv = rng.randint(0, 8)
        got = castable(sources, req, mv)
        want = ref_castable(sources, req, mv)
        if got != want:
            disagreements.append((case, sources, req, mv, got, want))
    assert not disagreements, disagreements[:3]


@pytest.mark.parametrize("seed", range(6))
def test_match_matches_the_pre_rewrite_matcher(seed):
    """The exported `_match` too: it is re-exported for `import mana_model`,
    so it is reachable without going through `castable` at all."""
    rng = random.Random(1000 + seed)
    for _ in range(300):
        units = [set(rng.sample(list(COLOURS + "C"), rng.randint(0, 3)))
                 for _ in range(rng.randint(0, 7))]
        req = _cost(rng)
        assert _match(units, req) == ref_match(units, req), (units, req)


def test_the_answer_does_not_depend_on_the_order_of_the_sources():
    """The memo sorts the hand and the pips into its key, which is only sound
    because a matching does not care about either order. Asserted rather than
    assumed: if it were false, the memo would answer one hand with another's
    result, and every figure would move by a little."""
    rng = random.Random(99)
    for _ in range(400):
        sources = [_source(rng, "order") for _ in range(rng.randint(1, 7))]
        req = _cost(rng)
        mv = rng.randint(0, 6)
        want = castable(sources, req, mv)
        for _shuffle in range(3):
            rng.shuffle(sources)
            rng.shuffle(req)
            assert castable(sources, req, mv) is want, (sources, req, mv)


def test_a_hand_too_big_to_pack_is_still_answered_correctly():
    """A hand is carried as one integer, six bits per signature counting how
    many are in play. Sixty-four of one signature would carry into the next
    signature's field and key as a completely different hand -- so `castable`
    refuses to pack a list that large and solves it directly.

    Constructed so the collision is exact and its answer is wrong: A and B are
    interned back to back, so 64 of A packs to precisely one B, and one blue
    source cannot pay {G}{G} however many greens were really there.
    """
    from mtg_utils.castability import _SIG_LIMIT, _sig_id

    # Amounts nothing else uses, so these two signatures are new and adjacent.
    a = {"colours": frozenset("G"), "filter": None, "omni": None,
         "amount": 61, "kind": "land", "tapped": False}
    b = {"colours": frozenset("U"), "filter": None, "omni": None,
         "amount": 62, "kind": "land", "tapped": False}
    sid_a, sid_b = _sig_id(a), _sig_id(b)
    assert sid_b == sid_a + 1, (
        "this case needs two freshly interned, adjacent signatures; pick "
        f"amounts no other test uses (got {sid_a}, {sid_b})")

    over = _SIG_LIMIT + 1
    assert castable([a] * over, ["G", "G"], 2) is True
    # The neighbour it would have collided with, for contrast.
    assert castable([b], ["G", "G"], 2) is False
    # And just under the limit, where packing is used, is right as well.
    assert castable([a] * _SIG_LIMIT, ["G", "G"], 2) is True
