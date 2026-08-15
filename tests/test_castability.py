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
