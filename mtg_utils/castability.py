"""Can these sources pay these pips, and do you have N mana on turn N."""
import bisect
import itertools
import math
import re

from mtg_utils.cards import COLOURS, MANA_SYMBOLS, front

# ============================================================ pip solving
def pips_from_cost(cost):
    """Coloured AND colourless pip requirements from a mana cost.

    {C} is a REQUIREMENT, not generic: Thought-Knot Seer {3}{C} cannot be cast
    off four Forests. Dropping it made every Eldrazi line look trivially
    castable, which overstated a whole colourless deck.

    {W/P} is Phyrexian and is always payable with 2 life, so it is never a
    colour requirement -- treating it as a hard {W} understated Mental Misstep
    and Dismember. {2/W} is two-brid and payable with generic, same reasoning.
    """
    req = []
    for sym in (cost or "").replace("}", "} ").split():
        s = sym.strip("{}")
        if s in COLOURS or s == "C":
            req.append(s)
        elif "/" in s and s != "//":
            parts = s.split("/")
            if "P" in parts:                      # Phyrexian: pay 2 life
                continue
            if any(p.isdigit() for p in parts):   # two-brid: pay generic
                continue
            cols = [p for p in parts if p in COLOURS]
            if cols:
                req.append("".join(cols))
    return req


def castable_faces(card):
    """Split and aftermath cards have a top-level cmc equal to the SUM of both
    halves, right for the stack and wrong for 'can I cast this on curve'."""
    layout = card.get("layout", "")
    if layout in ("split", "aftermath") and card.get("card_faces"):
        for f in card["card_faces"]:
            cost = f.get("mana_cost", "")
            mv = sum(int(t) if t.isdigit() else (0 if t == "X" else 1)
                     for t in re.findall(r"\{([^}]+)\}", cost))
            yield f["name"], cost, mv
    else:
        yield card["name"], front(card, "mana_cost", "") or "", int(
            front(card, "cmc", card.get("cmc", 0)) or 0)


# ------------------------------------------------------------ colour masks
#
# A colour is one bit of a six-bit universe (WUBRG plus C). Every question
# below -- "does this source make a pip this cost wants", "do these two lands
# share a colour" -- is then a single `&` instead of building and intersecting
# two sets, and the Monte Carlo loops ask it tens of millions of times.
#
# _mask is the ONLY place a colour string becomes a number, so the mapping
# cannot drift between the solver and the profiles it reads.
_BIT = {c: 1 << i for i, c in enumerate(MANA_SYMBOLS)}
_C_BIT = _BIT["C"]


def _mask(cols):
    """Bitmask of an iterable of colour letters. Unknown letters contribute
    nothing, which is what `set(x) & u` did with them."""
    m = 0
    for c in cols:
        b = _BIT.get(c)
        if b:
            m |= b
    return m


def _hall(units, subsets, nreq):
    """Can every pip be paid by a distinct unit?

    `units` is {colour mask: how many units carry it}; `subsets` is the
    precomputed Hall constraints for the pips (see _req_constraints).

    This replaces an augmenting-path search with Hall's marriage condition:
    a perfect matching of the pips into distinct units exists exactly when
    no set of pips outruns the units that can pay any of them. Pips of the
    SAME colour mask are interchangeable, so only whole groups need testing
    -- taking half a group leaves the same units reachable while asking for
    less -- which is why the constraint list is 2^(distinct masks) and not
    2^(pips), and in practice that is four or eight entries.
    """
    have = 0
    for c in units.values():
        have += c
    if nreq > have:
        return False
    for m, need in subsets:
        got = 0
        for um, uc in units.items():
            if um & m:
                got += uc
        if need > got:
            return False
    return True


def _req_constraints(req_masks):
    """(union mask, pips demanded) for every subset of the distinct pip masks."""
    groups = {}
    for m in req_masks:
        groups[m] = groups.get(m, 0) + 1
    items = list(groups.items())
    n = len(items)
    out = []
    for sub in range(1, 1 << n):
        um = need = 0
        for i in range(n):
            if sub >> i & 1:
                m, c = items[i]
                um |= m
                need += c
        out.append((um, need))
    return out


# A whole deck asks about a few dozen distinct costs, so the constraints get
# built a few dozen times over rather than once per solve.
_REQ_CACHE = {}


def _constraints(req_key):
    c = _REQ_CACHE.get(req_key)
    if c is None:
        masks = [_mask(r) for r in req_key]
        c = _REQ_CACHE[req_key] = (_req_constraints(masks), len(masks))
    return c


def _match(units, req):
    """Public name, kept: `units` is a list of colour SETS, `req` a list of
    pip strings. Now a thin front for the masked solver -- one implementation,
    so the exported entry point cannot answer differently from the one the
    models use."""
    req_masks = [_mask(r) for r in req]
    counts = {}
    for u in units:
        m = _mask(u)
        counts[m] = counts.get(m, 0) + 1
    return _hall(counts, _req_constraints(req_masks), len(req_masks))


# ------------------------------------------------------------ memo plumbing
#
# `castable` is a pure function of the source profiles and the pips, and the
# Monte Carlo loops ask it the same question over and over: a 99-card deck
# holds maybe two dozen DISTINCT source profiles, so twenty thousand trials
# keep drawing the same handful of hands out of them. Twenty Mountains are
# twenty separate dicts with identical contents and the solver cannot see
# that. Interning each profile down to a small int makes it visible, and the
# memo then answers four calls in five without solving anything.
#
# Keyed on CONTENT, not on id(): profile dicts are built once and never
# mutated, but keying on identity would make that an unstated requirement a
# future caller could break silently, and a stale answer here moves numbers.
_SIG_IDS = {}
# Parallel to _SIG_IDS by value: everything the solver reads, pre-masked.
#   (colour mask, filter mask, is a filter, amount, omni mask, is a land)
_SIG_DATA = []

# A HAND is a multiset of signatures, and every cache below is keyed on one.
# It is carried as a single integer, six bits per signature holding how many
# of it are in play, so a source coming online is one addition and comparing
# two hands is one integer compare -- where a sorted tuple meant an insertion,
# a rebuild, and a hash proportional to the hand at every lookup.
#
# Six bits counts to 63. Nothing either model builds comes near that -- a hand
# is a dozen sources -- and `castable` refuses to pack a list that could,
# rather than let one signature's count carry into the next one's bits.
_SIG_STRIDE = 6
_SIG_LIMIT = (1 << _SIG_STRIDE) - 1
_SIG_POW = []


def _sig_id(p):
    """Intern the fields `castable` actually reads, as a small int.

    Everything the solver consults is here and nothing else is: `tapped` is
    resolved by `playable_set` before we are called, and `mv` has already
    done its only job by the time the key is built.
    """
    cols = p["colours"]
    filt = p.get("filter")
    sig = (cols if type(cols) is frozenset else frozenset(cols),
           filt, p.get("amount", 1), p.get("omni"), p.get("kind", "land"))
    sid = _SIG_IDS.get(sig)
    if sid is None:
        sid = _SIG_IDS[sig] = len(_SIG_DATA)
        _SIG_POW.append(1 << (_SIG_STRIDE * sid))
        _SIG_DATA.append((_mask(sig[0]), _mask(filt) if filt else 0, bool(filt),
                          sig[2], _mask(sig[3]) if sig[3] else 0,
                          sig[4] == "land"))
    return sid


_CASTABLE_MEMO = {}


def _unpack(hand):
    """A packed hand back into its signature ids. Only ever on a cache miss."""
    sids = []
    sid = 0
    while hand:
        n = hand & _SIG_LIMIT
        if n:
            sids += [sid] * n
        hand >>= _SIG_STRIDE
        sid += 1
    return sids


def _ask(hand, req_key):
    """Memoised feasibility for a packed hand."""
    key = (hand, req_key)
    hit = _CASTABLE_MEMO.get(key)
    if hit is None:
        hit = _CASTABLE_MEMO[key] = _solve(hand, req_key)
    return hit


def castable(sources, req, mv):
    """sources: profiles in play and available. Multi-mana sources count their
    full amount toward mv and contribute that many coloured units."""
    total = 0
    for p in sources:
        total += p.get("amount", 1)
    if total < mv:
        return False
    if not req:
        return True
    # `mv` is deliberately absent from the key. It is spent entirely on the
    # total check above and is never consulted again -- leaving it in would
    # split the memo into buckets that always agree.
    #
    # `req` is sorted because the answer is a bipartite matching, which does
    # not care what order the pips arrive in. {W}{U} and {U}{W} are the same
    # question and now share an entry.
    sids = [_sig_id(p) for p in sources]
    req_key = tuple(sorted(req))
    if len(sids) > _SIG_LIMIT:
        # More sources than a packed hand can count. Neither model builds a
        # hand this size, so rather than widen the packing for a case that
        # cannot arise, this one is solved directly and not cached: a hand
        # that overflowed its field would collide with a different hand and
        # then answer for it.
        return _search(_derive(sids), *_constraints(req_key))
    hand = 0
    for sid in sids:
        hand += _SIG_POW[sid]
    return _ask(hand, req_key)


# What a hand of sources offers before any cost is named: the mana it makes,
# and the filter lands whose pairing has to be searched. Derived once per
# distinct hand rather than once per (hand, cost) -- the same seven sources
# get asked about several different spells.
_HAND_CACHE = {}


def _derive(sids):
    """(units, ocols, oamt, fpair) for a hand of interned signature ids.

    `units` is the finished mana when no filter land is present -- the
    ordinary case, which then skips the search entirely. It is None when
    there is one, and the other three feed the search.
    """
    data = [_SIG_DATA[s] for s in sids]
    omni = 0
    for d in data:
        omni |= d[4]
    others, filters = [], []
    for d in data:
        (filters if d[2] else others).append(d)
    # Urborg makes every LAND a Swamp; Yavimaya every land a Forest. Neither
    # says anything about a mana rock, and applying the omni colour to every
    # source had a colourless rock producing black.
    if omni:
        ocols = [(d[0] | omni) if d[5] else d[0] for d in others]
    else:
        ocols = [d[0] for d in others]
    oamt = [d[3] for d in others]
    if filters:
        return None, ocols, oamt, [d[1] for d in filters]
    units = {}
    for j, m in enumerate(ocols):
        units[m] = units.get(m, 0) + oamt[j]
    return units, None, None, None


def _hand(hand):
    h = _HAND_CACHE.get(hand)
    if h is None:
        h = _HAND_CACHE[hand] = _derive(_unpack(hand))
    return h


def _solve(hand, req_key):
    """Feasibility for a packed hand against the SORTED pips.

    Sorted rather than raw: a matching does not care what order the pips
    arrive in, and this is the tuple the memo is keyed on anyway.
    """
    return _search(_hand(hand), *_constraints(req_key))


def _search(derived, subsets, nreq):
    """Same search as before -- try each filter land unpaired, then paired
    with each source that shares one of its colours -- with the units carried
    as bitmasks rather than sets. The pairing search is exponential in the
    number of filter lands in hand, which is why it sits behind the memo.
    """
    units, ocols, oamt, fpair = derived
    if units is not None:
        return _hall(units, subsets, nreq)
    nf, no = len(fpair), len(ocols)
    activated = set()

    def recurse(idx, used):
        if idx == nf:
            units = {}
            for j in range(no):
                if j in used:
                    continue
                m = ocols[j]
                units[m] = units.get(m, 0) + oamt[j]
            for k in range(nf):
                if k in activated:
                    m = fpair[k]
                    units[m] = units.get(m, 0) + 2
                else:
                    # Unaided a filter land reads "{T}: Add {C}" as a separate
                    # first ability -- a lone Mystic Gate casts Sol Ring on
                    # turn one. It makes no coloured pip, but it does make {C}.
                    units[_C_BIT] = units.get(_C_BIT, 0) + 1
            return _hall(units, subsets, nreq)
        pair = fpair[idx]
        activated.discard(idx)
        if recurse(idx + 1, used):
            return True
        for j in range(no):
            if j in used or not (ocols[j] & pair):
                continue
            activated.add(idx)
            if recurse(idx + 1, used | {j}):
                return True
            activated.discard(idx)
        return False

    return recurse(0, frozenset())


def playable_set(chosen):
    if chosen and all(p["tapped"] for p in chosen):
        for i, p in enumerate(chosen):
            if p["tapped"]:
                return chosen[:i] + chosen[i + 1:]
    return chosen


# ------------------------------------------------------------ drawing cards
#
# `random.sample` and `random.shuffle` are reimplemented below, bit for bit,
# because every figure this tool prints is a Monte Carlo mean and the exact
# stream of random bits IS the answer: draw one bit differently and every
# snapshot in tests/fixtures/expected/ moves. What the copies buy is the
# freedom to skip work the stdlib cannot know is dead -- the 85 cards of a
# 99-card shuffle that are never looked at, the sample result list that is
# thrown away a line later -- while consuming the identical bits.
#
# `tests/test_rng_equivalence.py` asserts, against the stdlib, that they do.
# That test is the whole licence for this section: if a future interpreter
# changes either algorithm it fails there, naming the cause, instead of
# quietly moving four decks' worth of probabilities.
# `sample`'s strategy threshold depends only on k, so it is worked out once
# per distinct draw size rather than once per draw -- a log, a ceil and a
# power were being recomputed twenty thousand times a line to reach the same
# answer. The value is the stdlib's, unchanged; only how often it is derived.
_SETSIZE = {}


def _setsize(k):
    s = _SETSIZE.get(k)
    if s is None:
        s = 21
        if k > 5:
            s += 4 ** math.ceil(math.log(k * 3, 4))
        _SETSIZE[k] = s
    return s


def _sample_small(getrandbits, n, k, limit):
    """`sample`'s strategy for a population small enough that an n-length list
    beats a k-length set: draw from a pool, backfilling the vacancy."""
    out = []
    pool = list(range(n))
    for i in range(k):
        m = n - i
        b = m.bit_length()
        j = getrandbits(b)
        while j >= m:
            j = getrandbits(b)
        v = pool[j]
        if v < limit:
            out.append(v)
        pool[j] = pool[m - 1]
    return out


def _sample_set(getrandbits, n, k, limit):
    """`sample`'s strategy for a large population: draw and reject repeats.

    The rejection loop is fused: the stdlib calls `_randbelow(n)` (which
    redraws while r >= n) and then redraws while the result is already
    selected, which is the same sequence of draws as one loop that redraws on
    either condition.
    """
    out = []
    selected = set()
    add = selected.add
    b = n.bit_length()
    for _ in range(k):
        j = getrandbits(b)
        while j >= n or j in selected:
            j = getrandbits(b)
        add(j)
        if j < limit:
            out.append(j)
    return out


def _sample_plan(n, k):
    """Which of `sample`'s two strategies it would use for this size.

    They consume different bits, so the choice is part of the bit stream and
    not an implementation detail -- but it is fixed for a given (n, k), so a
    caller drawing in a loop picks the function once.

    The bound is `random.sample`'s own, message included, and dropping it was
    not survivable. `_setsize(k)` is always at least 3k, so k > n always lands
    in `_sample_small`, where the pool runs out at i == n: m becomes 0,
    `(0).bit_length()` is 0, `getrandbits(0)` is 0, and `while j >= m` is
    `0 >= 0` forever. It spins consuming no randomness rather than raising --
    a hang where the stdlib exited immediately, reachable from `mana` on any
    short decklist, which the tool warns about but does not refuse.
    """
    if not 0 <= k <= n:
        raise ValueError("Sample larger than population or is negative")
    return _sample_small if n <= _setsize(k) else _sample_set


def _sample_hits(getrandbits, n, k, limit):
    """The values `random.sample(range(n), k)` would return, keeping only
    those below `limit`, in order."""
    return _sample_plan(n, k)(getrandbits, n, k, limit)


def _shuffle_plan(n, m):
    """Split a Fisher-Yates shuffle of `n` cards into the part that decides
    the top `m` and the part that only advances the generator.

    `random.shuffle` walks i from n-1 down to 1 swapping x[i] with a random
    x[j <= i], and `list.pop()` takes from the end, so the first m steps fix
    exactly the m cards that get drawn -- nothing later can touch an index
    above the current i. The remaining steps still have to draw their bits,
    or every trial after this one would see a different generator, but they
    do not have to move any cards.

    Returns (head, tail): head is [(i, i+1, bits)], tail is [(i+1, bits)].
    """
    stop = max(0, n - 1 - m)
    head = [(i, i + 1, (i + 1).bit_length()) for i in range(n - 1, stop, -1)]
    tail = [(i + 1, (i + 1).bit_length()) for i in range(stop, 0, -1)]
    return head, tail


# ============================================================ sources model
# (turn, mv, pips, cap) -> {what was drawn: could it pay}. See `answered`.
_DRAW_MEMO = {}


# Every cache in this module is pure: dropping one costs time and can never
# cost correctness. Left unbounded they grow with each deck a long-lived run
# touches -- `calibrate` walks a whole collection -- so they are dropped
# wholesale past a watermark set above what one deck's full measurement needs,
# which is where the hits actually are. The interning tables are NOT dropped:
# _SIG_DATA is indexed by the ids every key is built from, and resetting it
# under a live caller would repoint them.
_CACHE_LIMIT = 300_000


def _bound_caches():
    held = len(_CASTABLE_MEMO) + len(_HAND_CACHE)
    for v in _DRAW_MEMO.values():
        held += len(v)
    if held > _CACHE_LIMIT:
        _CASTABLE_MEMO.clear()
        _HAND_CACHE.clear()
        _DRAW_MEMO.clear()


def probability(lands, accels, deck_size, req, mv, turn, sims, rng,
                max_combos=250, count_restricted=False, count_triggered=False):
    """P(can pay req for a spell of value mv on turn `turn`).

    Requires at least one land and at least `turn` mana sources present.
    """
    _bound_caches()
    # An EVENT-triggered source is excluded from generic totals by default,
    # for the same reason restricted mana is: it is real mana that this model
    # cannot promise. Lotus Cobra makes a mana when a land enters, and neither
    # model simulates land drops as an event -- counting it as a flat source
    # would inflate every figure it appears in. A PHASE-triggered source is
    # kept: it fires on its own, every turn, and is as reliable as a rock.
    accels = [a for a in accels
              if (count_restricted or not a.get("restricted"))
              and (count_triggered or a.get("trigger") != "event")]
    lands = [l for l in lands if count_restricted or not l.get("restricted")]
    allp = lands + accels
    nsrc = len(allp)
    # The pool is the sources followed by one entry per other card; only the
    # sources are ever looked at, so the draw below reports which of them came
    # up and the filler is never built.
    pool_n = nsrc + max(0, deck_size - nsrc)
    # Everything the inner loop asks of a profile, resolved once.
    sids = [_sig_id(p) for p in allp]
    amts = [p.get("amount", 1) for p in allp]
    # Membership tests, so "is there a land here" and "is everything here
    # tapped" are one C call over the combo rather than a Python loop.
    land_idx = frozenset(i for i, p in enumerate(allp) if p["kind"] == "land")
    untapped = frozenset(i for i, p in enumerate(allp) if not p["tapped"])
    # Everything a combo's answer turns on, packed into one int, so two draws
    # that differ only in which particular Mountain came up are recognisable
    # as the same question.
    code = [(sids[i] << 2) | (2 if i in land_idx else 0)
            | (0 if i in untapped else 1) for i in range(nsrc)]
    pow_of = [_SIG_POW[s] for s in sids].__getitem__
    amt_of = amts.__getitem__
    code_of = code.__getitem__
    req_key = tuple(sorted(req))
    memo = _CASTABLE_MEMO
    getrandbits = rng.getrandbits
    seen = 7 + turn - 1
    # A combination holds `turn` sources, so it cannot hold more than `turn`
    # of any one signature -- which is what keeps the packed hand below the
    # field width `castable` guards on its own entry point. `probability` is
    # exported, so `turn` arrives from outside; asserted here, where the
    # precondition is established, rather than tested per combination in the
    # loop below.
    assert turn <= _SIG_LIMIT, (turn, _SIG_LIMIT)
    combinations = itertools.combinations
    ncombos = [math.comb(g, turn) for g in range(seen + 1)]
    # Both are fixed for the whole run of sims, so the strategy is chosen once.
    draw_hits = _sample_plan(pool_n, seen)

    def any_castable(combos):
        for c in combos:
            if land_idx.isdisjoint(c):
                continue
            # playable_set: you sequence tapped lands onto earlier turns, so
            # one is only stuck if every source in hand is tapped.
            if untapped.isdisjoint(c):
                c = c[1:]
            if sum(map(amt_of, c)) < mv:
                continue
            if not req_key:
                return True
            key = (sum(map(pow_of, c)), req_key)
            r = memo.get(key)
            if r is None:
                r = memo[key] = _solve(key[0], req_key)
            if r:
                return True
        return False

    # Whether a draw can pay depends only on what was drawn AND ON THE ORDER
    # IT WAS DRAWN IN, so the same hand coming up again is the same answer --
    # and over thousands of sims the same hand comes up constantly.
    #
    # The order is in the key because `playable_set` reads it: a combination
    # in which every source is tapped loses the one drawn FIRST, so the same
    # multiset dealt in a different order can lose a different source and
    # answer differently. Keyed on the sorted codes, the first of those two
    # draws to arrive answered for both, and on a deck holding a tapped
    # source of two mana -- a karoo, Azorius Chancery -- that moved the
    # reported figure by eleven points. Every cache in this file needs an
    # argument for why its key is complete; this one's is that the loop below
    # reads nothing about a source except its code, and nothing about the
    # draw except the sequence of them.
    #
    # Only sound while no combo is discarded: once the count passes
    # max_combos the answer depends on which 250 the generator picked, which
    # is a different question every time.
    #
    # Kept between calls, because `--reps` asks the identical question three
    # times over at three seeds, and `variants` asks it again of a deck that
    # differs by three cards. The signature ids the draws are keyed on are
    # global, so a hand recognised once is recognised everywhere.
    dm_key = (turn, mv, req_key, max_combos)
    answered = _DRAW_MEMO.get(dm_key)
    if answered is None:
        answered = _DRAW_MEMO[dm_key] = {}
    hits = 0
    for _ in range(sims):
        got = draw_hits(getrandbits, pool_n, seen, nsrc)
        ng = len(got)
        if ng < turn:
            continue
        if land_idx.isdisjoint(got):
            continue
        if ncombos[ng] <= max_combos:
            dkey = tuple(map(code_of, got))
            r = answered.get(dkey)
            if r is None:
                r = answered[dkey] = any_castable(combinations(got, turn))
            if r:
                hits += 1
            continue
        allc = list(combinations(got, turn))
        if any_castable(rng.sample(allc, max_combos)):
            hits += 1
    return hits / sims


def at_least_in_draw(k, sources, cards_seen, deck=99):
    """P(at least `k` of `sources` among the first `cards_seen` cards).

    Renamed from `hypergeometric`. That name described the MATHS and said
    nothing about the question, so its only documented property was "never
    quote this" -- a trap with a docstring, and one short enough to paste
    into a primer as a castability number. This name states the question it
    answers, which is a counting question about the opening draw.

    It is NOT a castability figure and must never be reported as one: it
    counts cards, and knows nothing about pip payment, filter-land pairing,
    sequencing, or the cost of deploying an accelerant. `probability` (the
    sources model) and `playsim` (the play simulation) answer that, and
    every reported figure has to say which of those two produced it.

    What it is legitimately for is a question purely about the draw --
    "how often does an opening seven hold at most one land", which is the
    mulligan rate a real player faces and which neither model measures.
    """
    if sources < k:
        return 0.0
    return sum(math.comb(sources, i) * math.comb(deck - sources, cards_seen - i)
               for i in range(k, min(sources, cards_seen) + 1)) / math.comb(deck, cards_seen)


# ============================================================ play simulation
#
# One implementation, two shapes. `playsim` hands back the source profiles in
# play, which is its published contract and what the unit tests read; the
# report below wants only the two things it ever asks of a trial -- how much
# mana, and which pips it can pay -- and building the profile lists just to
# take them apart again cost more than the simulation did.
#
# Splitting this into two loops instead would mean two copies of the
# accelerant-deployment rule, and that rule is three fixed bugs deep. `shape`
# and `track` pick what gets recorded; nothing else differs.
_MODE_COUNT = 0            # per turn: nothing kept, only the generic tally
_MODE_TOTAL = 1            # per turn: available mana
_MODE_KEYED = 2            # per turn: available mana and the memo key


def _playsim_core(lands, accels, deck_size, turns, on_draw, trials, rng,
                  count_restricted, count_triggered, mode):
    """mode: None for the profile lists, else a per-turn list of _MODE_*.

    Returns (per-turn records, per-turn count of trials with >= t mana).
    """
    # An EVENT-triggered source is excluded from generic totals by default,
    # for the same reason restricted mana is: it is real mana that this model
    # cannot promise. Lotus Cobra makes a mana when a land enters, and neither
    # model simulates land drops as an event -- counting it as a flat source
    # would inflate every figure it appears in. A PHASE-triggered source is
    # kept: it fires on its own, every turn, and is as reliable as a rock.
    accels = [a for a in accels
              if (count_restricted or not a.get("restricted"))
              and (count_triggered or a.get("trigger") != "event")]
    lands = [l for l in lands if count_restricted or not l.get("restricted")]
    nL, nA = len(lands), len(accels)
    # Codes: 0..nL-1 a land, nL..nL+nA-1 an accelerant, -1 anything else. A
    # shuffle permutes POSITIONS and never looks at what it is moving, so
    # standing ints in for the card dicts changes nothing about which card
    # comes up -- it just makes dealing one cheap.
    deck = list(range(nL + nA)) + [-1] * (deck_size - nL - nA)
    assert len(deck) == deck_size, (len(deck), deck_size)

    l_tap = [p["tapped"] for p in lands]
    l_amt = [p.get("amount", 1) for p in lands]
    # The land played is the first minimum of this key, which is exactly what
    # `sort()` then `[0]` chose: untapped first, then most colours, then most
    # mana, ties going to whichever was drawn first.
    l_key = [(p["tapped"], -len(p["colours"]), -p.get("amount", 1))
             for p in lands]
    a_cost = [p["cost"] for p in accels]
    a_amt = [p.get("amount", 1) for p in accels]
    # An untapped non-creature rock is online the turn it enters; anything
    # else waits a turn. This is `online()`'s `entered == t` test, decided
    # once per profile instead of once per pass.
    #
    # A phase trigger waits too, for the same reason a mana creature does:
    # "at the beginning of your first main phase" has already happened by the
    # time you cast it. Both Hulking Raptor and Abstract Paintmage are
    # creatures and are caught by the clause beside this one, but a
    # phase-triggered ARTIFACT would otherwise come online a turn early --
    # the one direction this model must never err in.
    a_late = [bool(p["tapped"] or p.get("creature")
                   or p.get("trigger") == "phase") for p in accels]

    # One land a turn plus at most the four accelerants the deployment loop
    # will place, so nothing can come online often enough to overflow a
    # signature's field in the packed hand. Same precondition as the assert in
    # `probability`, established by a different caller.
    assert 5 * turns <= _SIG_LIMIT, (turns, _SIG_LIMIT)
    out = [[] for _ in range(turns + 1)]
    ghits = [0] * (turns + 1)
    if not trials:
        return out, ghits
    # Seven, plus one on the draw, plus one a turn after the first.
    drawn = 7 + (1 if on_draw else 0) + max(0, turns - 1)
    if drawn > deck_size:
        # `lib.pop()` off an empty library, raised before the first trial
        # rather than partway through it.
        raise IndexError("pop from empty list")
    head, tail = _shuffle_plan(deck_size, drawn)
    getrandbits = rng.getrandbits
    opening = 7 + (1 if on_draw else 0)
    shape = mode is None
    track = (not shape) and _MODE_KEYED in mode
    if track:
        # The packed contribution of each source, so coming online is one add.
        l_sid = [_SIG_POW[_sig_id(p)] for p in lands]
        a_sid = [_SIG_POW[_sig_id(p)] for p in accels]
    insort = bisect.insort
    # The cards this trial ever looks at, taken off the top in one slice
    # rather than one index at a time. `pop()` takes from the end, so the top
    # of the library is the tail of the list, read backwards.
    top = deck_size - 1
    open_sl = slice(top, top - opening if opening < deck_size else None, -1)
    draw_at = [0, 0] + [top - opening - (t - 2) for t in range(2, turns + 1)]
    x = deck[:]
    for _ in range(trials):
        x[:] = deck
        for i, k, b in head:
            j = getrandbits(b)
            while j >= k:
                j = getrandbits(b)
            x[i], x[j] = x[j], x[i]
        for k, b in tail:
            j = getrandbits(b)
            while j >= k:
                j = getrandbits(b)
        # Each hand is kept in the order it would be picked from, so choosing
        # is `[0]` rather than a scan. Entries carry their draw order and
        # `insort` places equals last, so a tie still goes to whichever was
        # drawn first -- which is what the stable sort and its `[0]` did.
        hand_l, hand_a = [], []
        seq = 0
        for c in x[open_sl]:
            if c >= 0:
                if c < nL:
                    insort(hand_l, (l_key[c], seq, c))
                else:
                    c -= nL
                    insort(hand_a, (a_cost[c], seq, c))
                seq += 1
        online_l = []                 # land profiles online, in play order
        rk_p, rk_ready = [], []       # rocks in deploy order, and from when
        live = 0                      # everything online, as a packed hand
        online_total = 0              # mana available right now
        pend_total = 0                # mana that comes online next turn
        pend_land = -1                # at most one: you play one land a turn
        pend_rocks = []
        for t in range(1, turns + 1):
            if t > 1:
                c = x[draw_at[t]]
                if c >= 0:
                    if c < nL:
                        insort(hand_l, (l_key[c], seq, c))
                    else:
                        c -= nL
                        insort(hand_a, (a_cost[c], seq, c))
                    seq += 1
                # Everything that entered last turn is online now.
                if pend_land >= 0:
                    if shape:
                        online_l.append(lands[pend_land])
                    if track:
                        live += l_sid[pend_land]
                    pend_land = -1
                if pend_rocks:
                    if track:
                        for code in pend_rocks:
                            live += a_sid[code]
                    pend_rocks = []
                online_total += pend_total
                pend_total = 0
            if hand_l:
                code = hand_l.pop(0)[2]
                if l_tap[code]:
                    pend_land = code
                    pend_total += l_amt[code]
                else:
                    online_total += l_amt[code]
                    if shape:
                        online_l.append(lands[code])
                    if track:
                        live += l_sid[code]

            # Deploying an accelerant COSTS the mana it costs. Without
            # `spent`, each pass re-read the full total and two lands could
            # deploy Sol Ring and a two-drop rock in the same turn -- and the
            # Sol Ring's own mana then funded a third. Every play-simulation
            # figure was inflated by it, most in the decks that lean on rocks.
            #
            # The rock's mana is still available the moment it lands (an
            # untapped, non-creature source is online the turn it enters), so
            # a turn-two Sol Ring off two lands correctly leaves 1 + 2 = 3.
            # The cheapest rock in hand is the only one worth testing: if it
            # is unaffordable then so is every other, which is what scanning
            # for "affordable, then cheapest" worked out the long way round.
            if hand_a:
                spent = 0
                for _pass in range(4):
                    if hand_a[0][0] > online_total - spent:
                        break
                    pick = hand_a.pop(0)
                    spent += pick[0]
                    code = pick[2]
                    if shape:
                        rk_p.append(accels[code])
                    if a_late[code]:
                        rk_ready.append(t + 1)
                        pend_rocks.append(code)
                        pend_total += a_amt[code]
                    else:
                        rk_ready.append(t)
                        online_total += a_amt[code]
                        if track:
                            live += a_sid[code]
                    if not hand_a:
                        break

            if online_total >= t:
                ghits[t] += 1
            if shape:
                if rk_p:
                    out[t].append(online_l + [p for p, r in zip(rk_p, rk_ready)
                                              if r <= t])
                else:
                    out[t].append(online_l[:])
                continue
            m = mode[t]
            if m == _MODE_KEYED:
                out[t].append((online_total, live))
            elif m == _MODE_TOTAL:
                out[t].append(online_total)
    return out, ghits


def playsim(lands, accels, deck_size, turns, on_draw, trials, rng,
            count_restricted=False, count_triggered=False):
    """Draw seven (+1 on the draw), draw one per turn, play a land if you have
    one, deploy the cheapest affordable accelerant, then read off available
    mana. Returns per-turn lists of (available source profiles, total mana)."""
    return _playsim_core(lands, accels, deck_size, turns, on_draw, trials, rng,
                         count_restricted, count_triggered, None)[0]


# How far the play simulation runs. Seven turns is where a Commander game is
# decided and where every table in this repo stops, but it is also a HARD edge:
# a line whose turn is past it is dropped rather than measured, so a caller
# that reads a line back by label has to know the limit. Defined once here so
# that caller cannot hold a different number.
PLAYSIM_TURNS = 7


def playsim_report(lands, accels, deck_size, lines, trials, rng,
                   turns=PLAYSIM_TURNS):
    """lines: list of (label, mana_value, pip_string like '{R}{R}')."""
    _bound_caches()
    specs = []
    for label, mv, pipstr in lines:
        req = pips_from_cost(pipstr)
        turn = max(mv, len(req), 1)
        if turn > turns:
            continue
        specs.append((label, mv, req, tuple(sorted(req)), turn))
    # What each turn has to record. Most turns are only ever asked "was there
    # t mana", which the simulation counts as it goes and never has to keep.
    mode = [_MODE_COUNT] * (turns + 1)
    for _label, _mv, req, _rk, turn in specs:
        if req:
            mode[turn] = _MODE_KEYED
        elif mode[turn] == _MODE_COUNT:
            mode[turn] = _MODE_TOTAL

    res = {}
    memo = _CASTABLE_MEMO
    for on_draw in (False, True):
        rows, ghits = _playsim_core(lands, accels, deck_size, turns, on_draw,
                                    trials, rng, False, False, mode)
        generic = {t: 100.0 * ghits[t] / trials for t in range(1, turns + 1)}
        labelled = {}
        for label, mv, req, req_key, turn in specs:
            hits = 0
            if req:
                for total, hand in rows[turn]:
                    if total < mv:
                        continue
                    k = (hand, req_key)
                    r = memo.get(k)
                    if r is None:
                        r = memo[k] = _solve(hand, req_key)
                    if r:
                        hits += 1
            elif mode[turn] == _MODE_KEYED:
                # A colourless commander asks only "is there enough mana", on
                # a turn some other line does ask a colour question about.
                for total, _hand in rows[turn]:
                    if total >= mv:
                        hits += 1
            else:
                for total in rows[turn]:
                    if total >= mv:
                        hits += 1
            labelled[label] = (100.0 * hits / trials, turn)
        res["draw" if on_draw else "play"] = {"generic": generic,
                                              "lines": labelled}
    return res
