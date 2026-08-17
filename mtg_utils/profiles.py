"""Source profiles: what each land and cheap accelerant actually produces.

Plus one shape that is NOT a source and is built separately for that reason:
a ritual, which produces mana on exactly one turn and never again.
"""
import re

from mtg_utils.cards import (COLOURS, MANA_SYMBOLS, BASIC_TYPE_COLOUR, enters_tapped,
                             fetch_targets, front, has_land_back, is_front_land,
                             is_tapped_fetcher, land_face, mana_amount)

FILTER_LANDS = {
    "mystic gate": "WU", "sunken ruins": "UB", "graven cairns": "BR",
    "fire-lit thicket": "RG", "wooded bastion": "GW", "fetid heath": "WB",
    "cascade bluffs": "UR", "twilight mire": "BG", "rugged prairie": "RW",
    "flooded grove": "GU",
}


OMNI_TYPE = {"urborg, tomb of yawgmoth": "B", "yavimaya, cradle of growth": "G"}


# ============================================================ profiles
RESTRICTED_MANA = "spend this mana only"


def unrestricted_mana(txt):
    """(colours, amount) a land offers with NO strings attached.

    Scryfall puts one ability per line, and the restriction rides on the same
    line as the ability it restricts:

        {T}: Add {C}.
        {T}: Add {C}{C}. Spend this mana only to cast colorless Eldrazi spells.

    so dropping the restricted lines leaves exactly the mana that pays for
    anything. Eldrazi Temple is a 1, not a 2. Cavern of Souls and Unclaimed
    Territory produce {C} and nothing else -- their any-colour mana casts one
    creature type, and counting it as free colour made a mono-red deck look
    like it had five.

    Returns (set(), 0) when every ability is restricted, which flags the card
    for exclusion the same way build_accel_profiles flags a restricted rock.
    """
    free = "\n".join(l for l in txt.split("\n") if RESTRICTED_MANA not in l)
    cols, amount = set(), 0
    for match in re.finditer(r"add ([^.;\n]*)", free):
        clause = match.group(1)
        cols |= {c.upper() for c in re.findall(r"\{([wubrgc])\}", clause)}
        if "any color" in clause:
            cols |= set(COLOURS)
        amount = max(amount, 1)
    return cols, (mana_amount(free) if amount else 0)


def drop_restricted(txt, pm, amount):
    """(colours, amount, restricted) with every restricted line taken out.

    Lands and accelerants must answer this the same way, and for a while they
    did not. Lands recomputed per line through unrestricted_mana; accelerants
    set the flag from a substring search over the WHOLE oracle text, so one
    restricted line anywhere condemned the card entire.

    That is not a cosmetic difference, because the two-line shape

        {T}: Add {C}.
        {T}: Add one mana of any color. Spend this mana only to cast a
             legendary spell...

    is printed on both. On a LAND (Cavern of Souls, Unclaimed Territory,
    Plaza of Heroes) it was read correctly as a {C} source. On a CREATURE
    (Delighted Halfling) the substring read dropped a turn-one dork out of
    the accelerant count altogether -- and the free half of its ability, the
    {C}, is exactly the half a generic on-curve figure is allowed to spend.

    Cards whose mana is restricted end to end still come back restricted:
    Fíli and Kíli, Joyous taps for {R}{R} for Dwarf, Equipment and Saga
    spells and for nothing else, and unrestricted_mana finds no free line.

    `amount` is returned unchanged when there is no restriction to drop, and
    also when EVERY line is restricted -- the flag excludes the card from the
    totals, it does not pretend the card taps for less than it does. See
    test_restricted_amount_is_still_read. (`pm` is not: it is narrowed on
    every path, per the paragraph below.)

    Every colour set returned is narrowed to MANA_SYMBOLS here rather than at
    the call sites. Both builders happen to pre-filter `pm` already, so this
    changes nothing today -- but the function is exported, and a postcondition
    that holds because of caller discipline is one an outside caller can
    break.
    """
    pm = {x for x in pm if x in MANA_SYMBOLS}
    if RESTRICTED_MANA not in txt:
        return pm, amount, False
    free_cols, free_amount = unrestricted_mana(txt)
    if not free_amount:
        return pm, amount, True
    # unrestricted_mana reads colours off {w..c} symbols and the literal
    # "any color", and real cards are worded past both: Gilded Lotus taps for
    # "three mana of any one color" and Reflecting Pool for "one mana of any
    # type that a land you control could produce". Neither matches, so a free
    # line worded that way returns NO colours with a non-zero amount -- a
    # source that counts toward the generic total and can pay no pip.
    #
    # produced_mana is Scryfall's own answer to what the card can make, so it
    # is the honest fallback: over-broad on colour, right on quantity, and
    # never that empty inconsistency. Neither of those two cards carries a
    # restricted line, so nothing in the fixtures reaches this -- it is
    # closed because the accelerant path only started coming through here in
    # this commit, and `if not pm: continue` used to make an empty set
    # impossible there. Widening unrestricted_mana instead would move land
    # numbers and belongs in its own commit.
    if not free_cols:
        return pm, free_amount, False
    return {x for x in free_cols if x in MANA_SYMBOLS}, free_amount, False


def build_land_profiles(deck_names, scry):
    profiles = []
    for n in deck_names:
        c = scry.get(n.lower())
        if not c:
            continue
        lf = land_face(c)
        if not lf:
            continue
        name = c["name"].lower()
        txt = (lf.get("oracle_text") or "").lower()
        pm = set(x for x in (lf.get("produced_mana") or c.get("produced_mana") or [])
                 if x in MANA_SYMBOLS)
        kind = "normal"
        if name in FILTER_LANDS:
            kind = "filter"
            pm = set(FILTER_LANDS[name])
        elif not pm:
            ft = fetch_targets(txt)
            if ft:
                kind = "fetch"
                pm = set()
                for n2 in deck_names:
                    c2 = scry.get(n2.lower())
                    if not c2:
                        continue
                    lf2 = land_face(c2)
                    if not lf2:
                        continue
                    tl = lf2.get("type_line", "").lower()
                    if any(t in tl for t, col in BASIC_TYPE_COLOUR.items() if col in ft):
                        pm.update(x for x in (lf2.get("produced_mana") or []) if x in COLOURS)
        tapped, cond = enters_tapped(lf, c)
        amount = 1 if kind in ("filter", "fetch") else mana_amount(txt)
        restricted = False
        # "Spend this mana only to cast..." is not mana for a generic total,
        # on a land exactly as on a rock. Recomputed only for lands that
        # carry the clause, so every other land is untouched -- and a filter
        # or fetch land is skipped outright, since its `pm` was rebuilt above
        # from the pairing or the fetch targets rather than read off the text.
        if kind == "normal":
            pm, amount, restricted = drop_restricted(txt, pm, amount)
        profiles.append({
            "name": name, "kind": "land",
            "colours": frozenset(pm),
            "filter": FILTER_LANDS.get(name),
            # `False if kind == "fetch"` used to stand here, and it was a
            # universal claim that three different cards fall under. It is
            # true of a fetch that puts its land in untapped and of nothing
            # else: Evolving Wilds hands you a TAPPED basic, and Bad River
            # enters tapped itself before it ever fetches -- the hard-coded
            # False overrode enters_tapped's correct verdict on that one.
            # Both were scored as untapped any-colour sources.
            "tapped": tapped or is_tapped_fetcher(lf, c),
            "cond_tap": cond,
            "amount": amount,
            "omni": OMNI_TYPE.get(name),
            "restricted": restricted,
            "mdfc": has_land_back(c),
        })
    return profiles


# A mana source is a PERMANENT with an activated ability that adds mana.
# "Battle" and "Planeswalker" are here for completeness; front-face lands are
# already filtered out before this is consulted.
PERMANENT_TYPES = ("Artifact", "Creature", "Enchantment", "Land",
                   "Planeswalker", "Battle")
# Reminder text is parenthetical, and a Treasure token's reminder text reads
# '{T}, Sacrifice this token: Add one mana of any color'. Matching it made
# every Treasure-maker a mana source. Strip parentheticals before deciding
# whether THIS card makes mana -- but never for a land, where a dual's whole
# ability is reminder text: Taiga's oracle text is exactly "({T}: Add {R} or
# {G}.)" and stripping it would leave nothing.
REMINDER_TEXT = re.compile(r"\([^)]*\)")
# An activated ability that adds mana: a cost, a colon, then "add" before the
# clause ends. The cost deliberately does NOT have to be {T} -- Ashnod's Altar
# and Phyrexian Altar add mana off a sacrifice and are real, repeatable
# sources.
MANA_ABILITY = re.compile(r":[^.]*\badd\b")


# A TRIGGERED mana ability is the third category, and until now it was the
# invisible one: MANA_ABILITY requires a colon, so a card whose mana arrives
# off a trigger matched nothing and was dropped from the accelerant list
# entirely. Lotus Cobra and Nissa, Resurgent Animist are both MV<=3, both
# make mana, and neither was counted.
#
# The two shapes are NOT equally reliable, and collapsing them would be the
# whole mistake:
#
#   phase  "At the beginning of your first main phase, add {G}{G}."
#          Fires on its own, every turn, once it is on the battlefield. As
#          reliable as a rock.
#   event  "Landfall -- Whenever a land you control enters, add one mana of
#          any color."
#          Fires only when something happens that neither model simulates.
#
# Anchored on the trigger word so the clause has to BE the trigger: a card
# that merely mentions adding mana in a later sentence does not qualify, and
# the produced_mana gate below still has the final say either way.
TRIGGERED_PHASE = re.compile(r"at the beginning of [^.]*?,\s*add\b")
TRIGGERED_EVENT = re.compile(r"whenever [^.]*?,\s*add\b")


def triggered_mana(txt):
    """"phase", "event", or None for oracle text with no triggered mana.

    Phase is tested first, but that order is a TIE-BREAK NO PRINTED CARD
    CURRENTLY EXERCISES -- a Scryfall search for oracle text carrying both
    shapes returns nothing. It is written down rather than left implicit so
    that if such a card is ever printed the tool picks the reliable reading
    instead of whichever branch happened to be first, but there is no test
    for it, because there is no card to write one against.
    """
    if TRIGGERED_PHASE.search(txt):
        return "phase"
    if TRIGGERED_EVENT.search(txt):
        return "event"
    return None


def build_accel_profiles(deck_names, scry, max_mv=3):
    """Cheap accelerants: non-land, MV <= max_mv, taps for mana.

    Restricted mana ("spend this mana only to cast Dwarf spells") is flagged
    and excluded from generic totals by default -- counting it as free mana is
    how a restricted rock silently inflates an on-curve number.
    """
    out = []
    for n in deck_names:
        c = scry.get(n.lower())
        if not c or is_front_land(c):
            continue
        mv = float(front(c, "cmc", c.get("cmc", 0)) or 0)
        if mv > max_mv:
            continue
        txt = (front(c, "oracle_text", "") or "").lower()
        # Both halves are load-bearing. The permanent check drops one-shots:
        # Dark Ritual (Instant, MV 1, "Add {B}{B}{B}") was counted as a
        # permanent producing three mana EVERY turn from the moment it was
        # drawn. The reminder-text strip drops spells that merely make a
        # mana-producing token: An Offer You Can't Refuse is a counterspell
        # whose Treasures go to the OPPONENT, and it counted as a source.
        if not any(t in c["type_line"].split("//")[0] for t in PERMANENT_TYPES):
            continue
        # Reminder text is stripped for the triggered check too, and for the
        # same reason: a Treasure token's reminder text describes an ability
        # the TOKEN has, not one this card has.
        stripped = REMINDER_TEXT.sub(" ", txt)
        trigger = None
        if not MANA_ABILITY.search(stripped):
            trigger = triggered_mana(stripped)
            if not trigger:
                continue
        pm = set(x for x in (c.get("produced_mana") or []) if x in MANA_SYMBOLS)
        if not pm and re.search(r"add \{c\}", txt):
            pm = {"C"}
        if not pm:
            continue
        # Per LINE, not per card -- see drop_restricted. `pm` comes off
        # produced_mana, which lists what the card can make without saying
        # what it may be spent on, so a card with one free line and one
        # restricted line has to have the restricted colours taken back out
        # as well as the flag left down: Delighted Halfling's produced_mana
        # is all five colours plus {C}, and only the {C} is free.
        pm, amount, restricted = drop_restricted(txt, pm, mana_amount(txt))
        tapped, cond = enters_tapped(c, c)
        out.append({
            "name": c["name"].lower(), "kind": "accel",
            "colours": frozenset(pm), "filter": None, "omni": None,
            "amount": amount,
            "cost": int(mv),
            "tapped": tapped, "cond_tap": cond,
            "restricted": restricted,
            # None for an ordinary activated ability. "phase" and "event"
            # are consumed differently by both models -- see castability.
            "trigger": trigger,
            "creature": "Creature" in c["type_line"].split("//")[0],
            "mdfc": False,
        })
    return out


# A RITUAL is the fourth shape of mana, and the only one that is never on the
# battlefield to be read: a one-shot spell whose whole effect is "Add {..}".
# It is NOT an accelerant and must never be counted as one -- see
# KNOWN_ISSUES.md #2 for what happened when it was. The play simulation
# consumes these as a single-turn burst; the sources model does not consume
# them at all, because it has no turn ordering to attach "available on exactly
# this turn" to.
#
# The clause has to BE a sentence of its own that is nothing but mana symbols.
# Every near miss in the four fixtures fails on one of those two halves, and
# each of them is a card that would otherwise be counted:
#
#   Warping Wail    '... token. It has "Sacrifice this token: Add {C}."'
#                   an ability the TOKEN has, and in quotes rather than
#                   parentheses, so stripping reminder text does not reach it
#                   -- the colon disqualifies it, the way MANA_ABILITY's colon
#                   qualifies a rock
#   Jeska's Will    '• Add {R} for each card in target opponent's hand.'
#   Mana Geyser     'Add {R} for each tapped land your opponents control.'
#                   an amount that depends on an opponent's board
#   Mana Drain      'At the beginning of your next main phase, add an amount
#                   of {C} equal to that spell's mana value.'
#                   deferred to a phase this model does not simulate, an
#                   amount it cannot know, and conditional on countering
#                   something
#
# Most of them are refused two or three times over -- by an anchor, by the
# net arithmetic below, or by the mana-value cap -- so no single loosening
# here admits one. tests/test_rituals.py says per card which rule is load
# bearing and which case pins only the outcome, because a case that passes for
# a reason other than the one it names is a case this repo has already been
# bitten by.
#
# The bullet is in the prefix class so that a MODE of a modal spell can be a
# ritual: you choose the mode, so a fixed-amount one is real mana.
RITUAL_ADD = re.compile(r"(?:^|[.\n•]\s*)add ((?:\{[wubrgc]\})+)(?=[.\n]|$)")
# "Sacrifice a creature" as an additional cost is a board state the model does
# not track, exactly like the conditional accelerants KNOWN_ISSUES.md #13
# declines to price. Culling the Weak ("As an additional cost to cast this
# spell, sacrifice a creature. Add {B}{B}{B}{B}.") is a ritual on paper and an
# empty board away from producing nothing.
ADDITIONAL_COST = "as an additional cost to cast this spell"


def ritual_add(txt):
    """(colours, gross mana) for a one-shot "Add {..}{..}." clause.

    Returns (set(), 0) when the text has no such clause, which is the common
    case: this is a gate, not a parser.

    The LARGEST qualifying clause wins, and the colours come from that same
    clause rather than from the union of all of them: two Add clauses in one
    text are alternatives you choose between, so summing them would credit a
    card with mana it cannot make in one cast and mixing their colours would
    credit it with a colour it cannot make at all.

    Like triggered_mana's phase-before-event order, that rule is A CHOICE NO
    PRINTED CARD HERE EXERCISES, and it is written down rather than left
    implicit. A second clause has to be a sentence of its own beginning with
    "Add" to match at all, which the real two-clause rituals are not: Cabal
    Ritual's second is behind "Threshold —" and Rite of Flame's is behind
    "Then". Both are correctly read at their unconditional amount, by the
    anchors rather than by this rule. There is no test for max-over-sum
    specifically, because there is no card to write one against.
    """
    best, cols = 0, set()
    for m in RITUAL_ADD.finditer(txt):
        syms = re.findall(r"\{([wubrgc])\}", m.group(1))
        if len(syms) > best:
            best, cols = len(syms), {s.upper() for s in syms}
    return cols, best


def build_ritual_profiles(deck_names, scry, max_mv=3):
    """One-shot rituals: non-permanent, MV <= max_mv, nets mana the turn it is cast.

    `amount` is the NET -- Dark Ritual ({B} for {B}{B}{B}) is 2, not 3, and
    Seething Song ({2}{R} for five red) is 2, not 5. Counting the gross is the
    shape of the #2 bug and would put a one-mana instant three mana ahead.

    `kind` is "ritual" rather than an "accel" carrying a flag, deliberately.
    Anything that COUNTS accelerants -- the `accelerants counted:` line,
    `skeleton`, the `variants --accel` sweep -- must not silently start
    including a card that is not a source, or the number the sweep varies
    stops meaning what the report says it means. The two questions want
    different answers, so they get different lists.

    Disjoint from build_accel_profiles by construction: that one requires a
    permanent type on the front face and this one requires the absence of one.
    No card in the fixtures actually needs that line -- a permanent's mana
    clause sits behind a colon or a trigger and fails the clause reader on its
    own -- so it is a boundary rather than a filter, and it is what makes "a
    card appears in at most one of these two lists" true by construction
    instead of by luck.
    """
    out = []
    for n in deck_names:
        c = scry.get(n.lower())
        if not c or is_front_land(c):
            continue
        if any(t in c["type_line"].split("//")[0] for t in PERMANENT_TYPES):
            continue
        mv = int(float(front(c, "cmc", c.get("cmc", 0)) or 0))
        if mv > max_mv:
            continue
        txt = (front(c, "oracle_text", "") or "").lower()
        if ADDITIONAL_COST in txt or RESTRICTED_MANA in txt:
            continue
        # Reminder text is stripped for the same reason the accelerant gate
        # strips it: a Treasure's parenthetical describes an ability the TOKEN
        # has. An Offer You Can't Refuse and Deadly Dispute are counterspell
        # and cantrip, and both carry "Add one mana of any color" inside one.
        # The land caveat that makes stripping unsafe there cannot apply here
        # -- a land is not a ritual.
        cols, gross = ritual_add(REMINDER_TEXT.sub(" ", txt))
        net = gross - mv
        if net < 1:
            continue
        out.append({
            "name": c["name"].lower(), "kind": "ritual",
            "colours": frozenset(cols), "filter": None, "omni": None,
            # The profile IS the burst the play simulation adds to the board
            # for one turn, so `amount` has to be the net and `colours` the
            # mana it makes. Read as a source it would be a two-mana any-turn
            # rock, which is why nothing may read it as one.
            "amount": net, "gross": gross,
            "cost": mv, "mana_cost": front(c, "mana_cost", "") or "",
            "tapped": False, "cond_tap": None, "restricted": False,
            "trigger": None, "creature": False, "mdfc": False,
        })
    return out
