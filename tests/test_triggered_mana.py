"""Triggered mana abilities: the third category of accelerant.

`MANA_ABILITY` requires a colon, because it was written for activated
abilities. A card whose mana arrives off a TRIGGER therefore matched nothing
and was dropped from the accelerant list entirely -- not misclassified,
invisible. Lotus Cobra and Nissa, Resurgent Animist are both MV<=3, both make
mana, and neither was counted as a source.

The two trigger shapes are not equally reliable, and treating them alike would
be the whole mistake:

    phase   "At the beginning of your first main phase, add {G}{G}."
            Fires on its own, every turn. As reliable as a rock, and counted.
    event   "Landfall -- Whenever a land you control enters, add one mana of
            any color."
            Fires only when something neither model simulates happens, so it
            is flagged and excluded from generic totals -- exactly what
            `restricted` mana already does, for the same reason.

Every oracle string in this file is VERBATIM Scryfall text. A previous case in
this repo for the MDFC land backs used invented wording no printed card uses,
and it passed while the real cards were misclassified.

On the MV window: two of the three cards that prompted this work are OUTSIDE
it. Hulking Raptor is MV 4 and Regal Behemoth is MV 6, against a default
max_mv of 3, so recognising the shape does not by itself surface either --
`test_the_default_mv_window_still_excludes_them` pins that, because it is the
surprising half.
"""
import random

import pytest


def _card(name, cmc, oracle, produced, type_line="Creature — Snake"):
    return {"name": name, "cmc": cmc, "oracle_text": oracle,
            "produced_mana": produced, "type_line": type_line}


# Verbatim Scryfall oracle text, fetched 2026-08-15.
LOTUS_COBRA = _card(
    "Lotus Cobra", 2.0,
    "Landfall — Whenever a land you control enters, add one mana of any color.",
    ["B", "G", "R", "U", "W"])
NISSA = _card(
    "Nissa, Resurgent Animist", 3.0,
    "Landfall — Whenever a land you control enters, add one mana of any color. "
    "Then if this is the second time this ability has resolved this turn, "
    "reveal cards from the top of your library until you reveal an Elf or "
    "Elemental card. Put that card into your hand and the rest on the bottom "
    "of your library in a random order.",
    ["B", "G", "R", "U", "W"], "Legendary Creature — Elf Scout")
PAINTMAGE = _card(
    "Abstract Paintmage", 3.0,
    "At the beginning of your first main phase, add {U}{R}. Spend this mana "
    "only to cast instant and sorcery spells.",
    ["R", "U"], "Creature — Djinn Sorcerer")
HULKING_RAPTOR = _card(
    "Hulking Raptor", 4.0,
    "Ward {2}\nAt the beginning of your first main phase, add {G}{G}.",
    ["G"], "Creature — Dinosaur")
REGAL_BEHEMOTH = _card(
    "Regal Behemoth", 6.0,
    "Trample\nWhen this creature enters, you become the monarch.\nWhenever you "
    "tap a land for mana while you're the monarch, add an additional one mana "
    "of any color.",
    ["B", "G", "R", "U", "W"], "Creature — Dinosaur")
SWORD_OF_THE_ANIMIST = _card(
    "Sword of the Animist", 2.0,
    "Equipped creature gets +1/+1.\nWhenever equipped creature attacks, you "
    "may search your library for a basic land card, put it onto the "
    "battlefield tapped, then shuffle.\nEquip {2}",
    None, "Legendary Artifact — Equipment")
SOL_RING = _card("Sol Ring", 1.0, "{T}: Add {C}{C}.", ["C"],
                 "Artifact")


def _profiles(mm, cards, max_mv=3):
    scry = {c["name"].lower(): c for c in cards}
    return mm.build_accel_profiles([c["name"] for c in cards], scry, max_mv)


# --- classifying the text ---------------------------------------------
@pytest.mark.parametrize("oracle,want", [
    (LOTUS_COBRA["oracle_text"], "event"),
    (NISSA["oracle_text"], "event"),
    (PAINTMAGE["oracle_text"], "phase"),
    (HULKING_RAPTOR["oracle_text"], "phase"),
    (REGAL_BEHEMOTH["oracle_text"], "event"),
    (SOL_RING["oracle_text"], None),
    (SWORD_OF_THE_ANIMIST["oracle_text"], None),
], ids=["trigger/landfall is an event",
        "trigger/landfall with a rider is still an event",
        "trigger/first main phase is a phase",
        "trigger/first main phase after another ability",
        "trigger/whenever you tap a land is an event",
        "trigger/an activated ability is not triggered at all",
        "trigger/fetching a land is not adding mana"])
def test_the_trigger_shape_is_classified(mm, oracle, want):
    """Sword of the Animist is the one to get right in the negative
    direction. It is a two-mana permanent that ramps, and it does not ADD
    mana -- it searches out a land. Counting it here would put a source in
    the pool that produces nothing the model can spend.
    """
    assert mm.triggered_mana(oracle.lower()) == want


def test_a_triggered_source_is_recognised_at_all(mm):
    """THE bug. Lotus Cobra has no colon anywhere in its oracle text, so the
    activated-ability pattern never matched and it was dropped from the
    accelerant list -- not counted wrongly, not counted at all."""
    got = _profiles(mm, [LOTUS_COBRA])
    assert [p["name"] for p in got] == ["lotus cobra"]
    assert got[0]["trigger"] == "event"
    assert got[0]["colours"] == frozenset("WUBRG")


def test_an_activated_accelerant_carries_no_trigger(mm):
    """The mirror: adding a third category must not relabel the first two."""
    got = _profiles(mm, [SOL_RING])
    assert got[0]["trigger"] is None


def test_a_land_fetcher_is_still_not_an_accelerant(mm):
    """Sword of the Animist ramps and makes no mana. It is a change to the
    LAND COUNT partway through a game, which is a different model entirely --
    admitting it here as a source would have it produce mana it cannot.

    Guarded TWICE, and deliberately left that way: the trigger pattern does
    not match ("whenever equipped creature attacks" has no `add` before the
    clause ends) and Scryfall reports no produced_mana. Breaking either alone
    leaves the other catching it; it takes both to fail this case, which was
    checked rather than assumed.
    """
    assert _profiles(mm, [SWORD_OF_THE_ANIMIST]) == []


def test_a_restricted_phase_trigger_is_still_restricted(mm):
    """Abstract Paintmage is both: a phase trigger whose mana casts only
    instants and sorceries. The two flags are independent and both have to
    survive, or a restricted source rejoins the generic pool by way of its
    trigger."""
    got = _profiles(mm, [PAINTMAGE])
    assert got[0]["trigger"] == "phase"
    assert got[0]["restricted"] is True


def test_the_default_mv_window_still_excludes_them(mm):
    """The surprising half, and the reason this is not a bigger change than
    it looks.

    Two of the three cards that prompted this work are outside the MV<=3
    accelerant window: Hulking Raptor is MV 4 and Regal Behemoth is MV 6.
    Recognising the trigger shape does not surface either, and saying so is
    the difference between a fix and a claim of one.
    """
    assert _profiles(mm, [HULKING_RAPTOR, REGAL_BEHEMOTH]) == []
    got = _profiles(mm, [HULKING_RAPTOR, REGAL_BEHEMOTH], max_mv=6)
    assert {p["name"]: p["trigger"] for p in got} == {
        "hulking raptor": "phase", "regal behemoth": "event"}


# --- what the models do with it ---------------------------------------
def _land():
    return {"colours": frozenset("G"), "amount": 1, "filter": None,
            "omni": None, "kind": "land", "tapped": False, "cond_tap": None,
            "restricted": False, "mdfc": False}


def test_an_event_trigger_is_excluded_from_generic_totals(mm):
    """Neither model simulates a land drop as an EVENT, so Lotus Cobra's mana
    is real and unpromisable. Counted flat it inflates every figure it appears
    in -- the same failure a restricted rock causes, which is why it is
    handled the same way."""
    cobra = _profiles(mm, [LOTUS_COBRA])
    lands = [_land()] * 30
    without = mm.probability(lands, cobra, 99, ["G", "G"], 2, 2, 400,
                             random.Random(4))
    none_at_all = mm.probability(lands, [], 99, ["G", "G"], 2, 2, 400,
                                 random.Random(4))
    assert without == none_at_all


def test_count_triggered_puts_it_back(mm):
    """The mirror of the case above: the exclusion has to be a choice the
    model makes, not a source it silently lost. If these two agree, the flag
    is doing nothing and the first case proves nothing either."""
    cobra = _profiles(mm, [LOTUS_COBRA])
    lands = [_land()] * 12
    off = mm.probability(lands, cobra, 99, ["G", "G"], 2, 2, 600,
                         random.Random(4))
    on = mm.probability(lands, cobra, 99, ["G", "G"], 2, 2, 600,
                        random.Random(4), count_triggered=True)
    assert on > off


def test_a_phase_trigger_is_counted(mm):
    """It fires on its own, every turn, once it is on the battlefield. Nothing
    about it is conditional, so excluding it would understate -- and
    understating castability is exactly what counting lands-only does."""
    raptor = _profiles(mm, [HULKING_RAPTOR], max_mv=6)
    lands = [_land()] * 12
    with_it = mm.probability(lands, raptor, 99, ["G", "G"], 2, 2, 600,
                             random.Random(4))
    without = mm.probability(lands, [], 99, ["G", "G"], 2, 2, 600,
                             random.Random(4))
    assert with_it > without


def test_a_phase_trigger_is_offline_the_turn_it_enters(mm):
    """"At the beginning of your first main phase" has already happened by the
    time you cast the thing. A phase-triggered ARTIFACT would otherwise come
    online a turn early -- the direction this model must never err in, and the
    one the creature clause beside it does not cover.
    """
    artifact = _card("Test Phase Rock", 1.0,
                     "At the beginning of your first main phase, add {G}.",
                     ["G"], "Artifact")
    rock = _profiles(mm, [artifact])
    assert rock[0]["trigger"] == "phase" and rock[0]["creature"] is False
    lands = [_land()] * 40
    rounds = mm.playsim(lands, rock * 10, 99, 2, False, 600, random.Random(4))

    def mana(turn):
        return [sum(p.get("amount", 1) for p in trial) for trial in rounds[turn]]

    # Turn one can never reach 2: the land makes one, and the rock -- even
    # when it is cast off that land -- does not fire until the next turn.
    assert max(mana(1)) == 1
    # Turn two must be able to, or the assertion above is satisfied by a rock
    # that never comes online at all and the case proves nothing.
    assert max(mana(2)) >= 3
