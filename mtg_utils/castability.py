"""Can these sources pay these pips, and do you have N mana on turn N."""
import itertools
import math
import re

from mtg_utils.cards import COLOURS, front

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


def _match(units, req):
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


def castable(sources, req, mv):
    """sources: profiles in play and available. Multi-mana sources count their
    full amount toward mv and contribute that many coloured units."""
    total = sum(p.get("amount", 1) for p in sources)
    if total < mv:
        return False
    if not req:
        return True

    omni = set(p["omni"] for p in sources if p.get("omni")) - {None}

    def cols(p):
        # Urborg makes every LAND a Swamp; Yavimaya every land a Forest.
        # Neither says anything about a mana rock, and applying the omni
        # colour to every source had a colourless rock producing black.
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
                    # Unaided a filter land reads "{T}: Add {C}" as a separate
                    # first ability -- a lone Mystic Gate casts Sol Ring on
                    # turn one. It makes no coloured pip, but it does make {C}.
                    units.append({"C"})
            return _match(units, req)
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


def playable_set(chosen):
    if chosen and all(p["tapped"] for p in chosen):
        for i, p in enumerate(chosen):
            if p["tapped"]:
                return chosen[:i] + chosen[i + 1:]
    return chosen


# ============================================================ sources model
def probability(lands, accels, deck_size, req, mv, turn, sims, rng,
                max_combos=250, count_restricted=False, count_triggered=False):
    """P(can pay req for a spell of value mv on turn `turn`).

    Requires at least one land and at least `turn` mana sources present.
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
    pool_idx = list(range(len(lands) + len(accels)))
    allp = lands + accels
    pool = pool_idx + [None] * (deck_size - len(pool_idx))
    seen = 7 + turn - 1
    hits = 0
    for _ in range(sims):
        draw = rng.sample(pool, seen)
        got = [allp[i] for i in draw if i is not None]
        if not any(p["kind"] == "land" for p in got):
            continue
        if len(got) < turn:
            continue
        if len(got) == turn:
            combos = [got]
        else:
            allc = list(itertools.combinations(got, turn))
            combos = allc if len(allc) <= max_combos else rng.sample(allc, max_combos)
        for c in combos:
            c = list(c)
            if not any(p["kind"] == "land" for p in c):
                continue
            if castable(playable_set(c), req, mv):
                hits += 1
                break
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
def ritual_burst(srcs, cands):
    """The best single ritual castable off `srcs` this turn, or None.

    `cands` are hand entries -- {"p": profile, "pips": [...]} -- and the
    profile that comes back IS the burst: `amount` is the net, so appending it
    to `srcs` leaves the board at total + net, which is what the turn actually
    has after the ritual resolves.

    The gate is `castable` against the ritual's OWN cost, so a Dark Ritual
    with no untapped black source contributes nothing. That is the whole
    difference between this and a flat bonus, and the reason a ritual is worth
    less in a deck that cannot reliably make its colour -- which is exactly
    the question the play simulation exists to answer.

    ONE per turn, best first. Two rituals really do chain in play, and the
    second is paid for out of the first's mana -- a burst funding a burst,
    which is the shape of every overstatement this model has already had. The
    cap costs a line that needs two rituals in one hand and can only ever
    lower a figure, which is the safe direction.

    Ordered by net then name so the choice is deterministic: the same board
    and the same hand pick the same ritual on every run and every seed. That
    is determinism, which is NOT the same property as best. The choice is made
    once per turn, here, before any line is evaluated, so it is blind to the
    pips the reading will ask for: holding Dark Ritual and Pyretic Ritual on a
    Swamp-Mountain-Mountain board, the larger net wins and yields two black
    for a line wanting {R}{R}{R} that the smaller one would have paid. It errs
    DOWNWARD, which is the safe direction, and picking per line would mean
    moving this decision into playsim_report and searching inside the trial
    loop. Priced and kept -- KNOWN_ISSUES.md #15.
    """
    for c in sorted(cands, key=lambda c: (-c["p"]["amount"], c["p"]["name"])):
        if castable(srcs, list(c["pips"]), c["p"]["cost"]):
            return c["p"]
    return None


def playsim(lands, accels, deck_size, turns, on_draw, trials, rng,
            count_restricted=False, count_triggered=False, rituals=None):
    """Draw seven (+1 on the draw), draw one per turn, play a land if you have
    one, deploy the cheapest affordable accelerant, then read off available
    mana. Returns per-turn lists of (available source profiles, total mana).

    `rituals` are one-shot spells (build_ritual_profiles), and they are handled
    nothing like accelerants. A ritual is never deployed to the battlefield and
    never becomes a source: it is read out of HAND, once, at the end of the
    turn, as a burst of its net mana, and only if the board can pay its cost.

    It stays in hand across turns on purpose. Each turn's reading is a separate
    question -- "if I am holding this on turn five, do I have five mana on turn
    five" -- and a real player holds a ritual until the turn it pays for
    something. Firing it on the first turn it is castable would model a player
    who casts Dark Ritual into an empty hand, and would understate every later
    turn. What must not happen, and does not, is the mana COMPOUNDING: it is
    recomputed from scratch each turn, never lands on the battlefield, and
    never funds an accelerant.
    """
    accels = [a for a in accels
              if (count_restricted or not a.get("restricted"))
              and (count_triggered or a.get("trigger") != "event")]
    lands = [l for l in lands if count_restricted or not l.get("restricted")]
    # The pips are solved ONCE here rather than per turn per trial: the cost of
    # a card does not change, and pips_from_cost inside the trial loop is the
    # kind of work that turns a 20,000-trial run into a coffee break.
    entries = ([{"t": "land", "p": p} for p in lands] +
               [{"t": "accel", "p": a} for a in accels] +
               [{"t": "ritual", "p": r, "pips": pips_from_cost(r["mana_cost"])}
                for r in (rituals or [])])
    deck = entries + [{"t": "spell"}] * (deck_size - len(entries))
    assert len(deck) == deck_size, (len(deck), deck_size)

    out = [[] for _ in range(turns + 1)]
    for _ in range(trials):
        lib = deck[:]
        rng.shuffle(lib)
        hand = [lib.pop() for _ in range(7)]
        if on_draw:
            hand.append(lib.pop())
        bf_lands, rocks = [], []
        for t in range(1, turns + 1):
            if t > 1:
                hand.append(lib.pop())
            avail_lands = [c for c in hand if c["t"] == "land"]
            if avail_lands:
                avail_lands.sort(key=lambda c: (c["p"]["tapped"],
                                                -len(c["p"]["colours"]),
                                                -c["p"].get("amount", 1)))
                pick = avail_lands[0]
                hand.remove(pick)
                bf_lands.append({"p": pick["p"], "entered": t})

            def online():
                srcs = []
                for L in bf_lands:
                    if L["entered"] == t and L["p"]["tapped"]:
                        continue
                    srcs.append(L["p"])
                for R in rocks:
                    p = R["p"]
                    # A phase trigger is offline the turn it enters, for the
                    # same reason a mana creature is: "at the beginning of
                    # your first main phase" has already happened by the time
                    # you cast it. Both Hulking Raptor and Abstract Paintmage
                    # are creatures and were covered by the clause beside
                    # this one, but a phase-triggered ARTIFACT would otherwise
                    # come online a turn early -- the one direction this model
                    # must never err in.
                    if R["entered"] == t and (p["tapped"] or p.get("creature")
                                              or p.get("trigger") == "phase"):
                        continue
                    srcs.append(p)
                return srcs

            # Deploying an accelerant COSTS the mana it costs. Without
            # `spent`, each pass re-read the full total and two lands could
            # deploy Sol Ring and a two-drop rock in the same turn -- and the
            # Sol Ring's own mana then funded a third. Every play-simulation
            # figure was inflated by it, most in the decks that lean on rocks.
            #
            # The rock's mana is still available the moment it lands (an
            # untapped, non-creature source is online the turn it enters), so
            # a turn-two Sol Ring off two lands correctly leaves 1 + 2 = 3.
            spent = 0
            for _pass in range(4):
                srcs = online()
                available = sum(p.get("amount", 1) for p in srcs) - spent
                cands = [c for c in hand
                         if c["t"] == "accel" and c["p"]["cost"] <= available]
                if not cands:
                    break
                cands.sort(key=lambda c: c["p"]["cost"])
                c = cands[0]
                hand.remove(c)
                spent += c["p"]["cost"]
                rocks.append({"p": c["p"], "entered": t})
            srcs = online()
            # AFTER the deployment loop, so a ritual can never pay for an
            # accelerant. The burst is one turn of mana; a rock it bought
            # would be on the battlefield for the rest of the game.
            if rituals:
                held = [c for c in hand if c["t"] == "ritual"]
                burst = ritual_burst(srcs, held) if held else None
                if burst:
                    srcs = srcs + [burst]
            out[t].append(srcs)
    return out


def playsim_report(lands, accels, deck_size, lines, trials, rng, turns=7,
                   rituals=None):
    """lines: list of (label, mana_value, pip_string like '{R}{R}')."""
    res = {}
    for on_draw in (False, True):
        rounds = playsim(lands, accels, deck_size, turns, on_draw, trials, rng,
                         rituals=rituals)
        key = "draw" if on_draw else "play"
        res[key] = {"generic": {}, "lines": {}}
        for t in range(1, turns + 1):
            hits = sum(1 for s in rounds[t]
                       if sum(p.get("amount", 1) for p in s) >= t)
            res[key]["generic"][t] = 100.0 * hits / trials
        for label, mv, pipstr in lines:
            req = pips_from_cost(pipstr)
            turn = max(mv, len(req), 1)
            if turn > turns:
                continue
            hits = sum(1 for s in rounds[turn] if castable(s, req, mv))
            res[key]["lines"][label] = (100.0 * hits / trials, turn)
    return res
