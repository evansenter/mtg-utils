"""Ported from `selftest`: castable, playable_set, hypergeometric, determinism."""
import random

import pytest

from conftest import src


# --- castable / filter lands -----------------------------------------
# A filter paired with a partner yields two pips OF ITS OWN TWO COLOURS,
# not of whatever colour you happen to be measuring. Mystic Gate is W/U
# and produces NO BLACK. On the Esper list this bug and the excluded-
# accelerants bug nearly cancelled and hid each other.
@pytest.fixture
def gate():
    return src(filt="WU")


@pytest.fixture
def plains():
    return src("W")


@pytest.fixture
def swamp():
    return src("B")


def test_filter_makes_own_pair(mm, gate, plains):
    """castable/filter makes own pair"""
    assert mm.castable([gate, plains], ["W", "W"], 2) is True


def test_filter_makes_no_black(mm, gate, plains):
    """castable/filter makes no black"""
    assert mm.castable([gate, plains], ["B", "B"], 2) is False


def test_lone_filter_taps_for_c(mm, gate):
    """castable/lone filter taps for C"""
    assert mm.castable([gate], [], 1) is True


def test_lone_filter_makes_no_pip(mm, gate):
    """castable/lone filter makes no pip"""
    assert mm.castable([gate], ["W"], 1) is False


def test_no_partner_of_its_colours(mm, gate, swamp):
    """castable/no partner of its colours"""
    assert mm.castable([gate, swamp], ["W", "W"], 2) is False


def test_omni(mm):
    """castable/omni -- Yavimaya/Urborg omni-typing applies to every land in play."""
    assert mm.castable([src("R"), src("G", omni="G")], ["G", "G"], 2) is True


def test_amount_counts_toward_mv(mm):
    """castable/amount counts toward mv -- multi-mana sources count their full amount."""
    assert mm.castable([src("C", amount=2)], [], 2) is True


def test_insufficient_total(mm):
    """castable/insufficient total"""
    assert mm.castable([src("R")], ["R"], 3) is False


def test_forests_cannot_pay_c(mm):
    """castable/forests cannot pay {C}"""
    forests = [src("G")] * 4
    assert mm.castable(forests, mm.pips_from_cost("{3}{C}"), 4) is False


def test_colourless_source_pays_c(mm):
    """castable/colourless source pays {C}"""
    assert mm.castable([src("C", amount=2), src("G"), src("G")],
                       mm.pips_from_cost("{3}{C}"), 4) is True


def test_phyrexian_off_any_source(mm):
    """castable/phyrexian off any source"""
    assert mm.castable([src("G")], mm.pips_from_cost("{U/P}"), 1) is True


def test_lone_filter_pays_c(mm):
    """castable/lone filter pays {C}

    A lone filter taps for {C} unaided -- it makes no coloured pip but it
    does make colourless, which is what lets it cast Sol Ring on turn one.
    """
    assert mm.castable([src(filt="WU"), src("G")], ["C"], 2) is True


# --- hypergeometric --------------------------------------------------
def test_hypergeom_impossible(mm):
    """hypergeom/impossible"""
    assert mm.hypergeometric(3, 2, 7) == 0.0


def test_hypergeom_certain(mm):
    """hypergeom/certain"""
    assert round(mm.hypergeometric(1, 99, 7, 99), 9) == 1.0


# --- playable_set ------------------------------------------------------
# You sequence tapped lands onto EARLIER turns, so one is only stuck if
# every land you hold is tapped.
TAP = {"tapped": True, "colours": frozenset("G"), "amount": 1,
       "filter": None, "omni": None}
UNS = {"tapped": False, "colours": frozenset("G"), "amount": 1,
       "filter": None, "omni": None}


def test_playable_all_tapped_loses_one(mm):
    """playable/all tapped loses one"""
    assert len(mm.playable_set([TAP, TAP])) == 1


def test_playable_one_untapped_keeps_all(mm):
    """playable/one untapped keeps all"""
    assert len(mm.playable_set([TAP, UNS])) == 2


def test_playable_empty(mm):
    """playable/empty"""
    assert mm.playable_set([]) == []


# --- determinism -------------------------------------------------------
# Without this a refactor silently moves every reported number.
@pytest.fixture
def taiga_profile(mm):
    scry = {"taiga": {"name": "Taiga", "type_line": "Land — Mountain Forest",
                      "oracle_text": "({T}: Add {R} or {G}.)",
                      "produced_mana": ["R", "G"]}}
    return mm.build_land_profiles(["taiga"], scry)[0]


def test_determinism_probability(mm, taiga_profile):
    """determinism/probability"""
    dl = [dict(taiga_profile) for _ in range(20)]
    p1 = mm.probability(dl, [], 99, ["R", "G"], 3, 3, 500, random.Random(4))
    p2 = mm.probability(dl, [], 99, ["R", "G"], 3, 3, 500, random.Random(4))
    assert p1 == p2


def test_determinism_playsim(mm, taiga_profile):
    """determinism/playsim"""
    dl = [dict(taiga_profile) for _ in range(20)]
    s1 = mm.playsim(dl, [], 99, 3, False, 100, random.Random(4))
    s2 = mm.playsim(dl, [], 99, 3, False, 100, random.Random(4))
    assert [len(x) for x in s1] == [len(x) for x in s2]


# --- deploying an accelerant costs mana --------------------------------
def _land1():
    return {"name": "land", "kind": "land", "colours": frozenset("G"), "filter": None,
            "omni": None, "amount": 1, "tapped": False, "cond_tap": None, "mdfc": False}


def _rock(cost, amount=1):
    return {"name": f"rock{cost}", "kind": "accel", "colours": frozenset("G"),
            "filter": None, "omni": None, "amount": amount, "cost": cost,
            "tapped": False, "cond_tap": None, "restricted": False,
            "creature": False, "mdfc": False}


def test_playsim_cannot_deploy_more_than_it_can_pay_for(mm):
    """playsim/deployment is paid for

    Two lands on turn two is two mana, so exactly ONE two-cost rock can be
    deployed. The rock then taps for one, which is not enough for a second.
    Ceiling: 2 lands + 1 rock = 3.

    Before the fix each pass re-read the full board total without deducting
    what had already been spent, so the first rock's own mana funded the
    next, and the next -- up to the four-pass cap. Same board, ceiling of 6.

    Constructed so the ceiling is exact rather than statistical: every card in
    the deck is either an untapped one-mana land or a two-cost rock, so the
    maximum over trials is reached whenever a trial has two lands by turn two.
    """
    lands = [_land1() for _ in range(40)]
    accels = [_rock(2) for _ in range(59)]
    rounds = mm.playsim(lands, accels, 99, 2, False, 500, random.Random(17))
    totals = [sum(p.get("amount", 1) for p in s) for s in rounds[2]]
    assert max(totals) == 3, max(totals)


def test_playsim_deploys_nothing_it_cannot_pay_for(mm):
    """playsim/an unaffordable rock stays in hand

    Three-cost rocks on two lands: nothing is deployable, so turn two reads
    exactly the two lands. Guards the other direction from the case above --
    a fix that simply stopped deploying would pass that one and fail this.
    """
    lands = [_land1() for _ in range(40)]
    accels = [_rock(3) for _ in range(59)]
    rounds = mm.playsim(lands, accels, 99, 2, False, 800, random.Random(17))
    totals = [sum(p.get("amount", 1) for p in s) for s in rounds[2]]
    assert max(totals) == 2, max(totals)


def test_playsim_still_chains_when_each_rock_pays_for_the_next(mm):
    """playsim/a real chain is preserved

    One-cost rocks that tap for one are mana-neutral, so each genuinely pays
    for the next: land -> rock -> rock -> rock -> rock, stopping at the
    four-pass cap. Turn one reads 1 land + 4 rocks = 5.

    This is the case that makes "just deduct the cost" insufficient as a
    description: the deduction is right, and the chain is still real, because
    the rock is online the turn it enters. My first draft of this test
    asserted 2, on the assumption that spending the land's mana ended the
    turn. It does not, and the code was right.
    """
    lands = [_land1() for _ in range(40)]
    accels = [_rock(1) for _ in range(59)]
    rounds = mm.playsim(lands, accels, 99, 1, False, 500, random.Random(17))
    totals = [sum(p.get("amount", 1) for p in s) for s in rounds[1]]
    assert max(totals) == 5, max(totals)


# --- omni-typing is a LAND effect --------------------------------------
def test_omni_does_not_reach_a_mana_rock(mm):
    """castable/omni does not colour a rock

    Urborg, Tomb of Yawgmoth makes every LAND a Swamp. It says nothing about
    Sol Ring. Applying the omni colour to every source let a colourless rock
    pay a black pip.

    Not visible in any fixture's output -- the four committed decks show no
    measurable difference at 8000 sims -- so it is asserted directly. A real
    bug that the golden suite happens not to exercise is exactly the case
    that needs its own test.
    """
    urborg = src("B", omni="B")
    rock = src("", kind="accel")            # colourless: Sol Ring, Mind Stone
    swamp = src("B")
    # the rock cannot be the second black source
    assert mm.castable([urborg, rock], ["B", "B"], 2) is False
    # a real land can
    assert mm.castable([urborg, swamp], ["B", "B"], 2) is True


def test_omni_still_reaches_every_land(mm):
    """castable/omni reaches all lands

    The other direction: Urborg genuinely turns a Mountain into a black
    source, and narrowing it to lands must not narrow it to the omni land
    itself.
    """
    assert mm.castable([src("R"), src("G", omni="G")], ["G", "G"], 2) is True
    assert mm.castable([src("R"), src("R"), src("B", omni="B")],
                       ["B", "B", "B"], 3) is True
