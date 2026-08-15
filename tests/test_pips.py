"""Ported from `selftest`: pips_from_cost and castable_faces.

A parser's symbol set is a claim, and needs a test per symbol. Four shipped
wrong at once -- {C}, {W/P}, {2/W} and, by omission, {S}.
"""
import pytest

from conftest import card

PIPS = [
    ("pips/naya", "{2}{R}{G}{W}", ["R", "G", "W"]),
    ("pips/X ignored", "{X}{B}{B}{B}", ["B", "B", "B"]),
    ("pips/hybrid", "{2}{R/W}", ["RW"]),
    ("pips/colourless", "{4}", []),
    # {C} parsed to NOTHING, so four Forests "cast" Thought-Knot Seer and every
    # Eldrazi line in a colourless deck read as trivially castable.
    ("pips/colourless pip", "{3}{C}", ["C"]),
    ("pips/double colourless", "{C}{C}", ["C", "C"]),
    # {W/P} is payable with 2 life and is never a colour requirement; parsing
    # it as a hard pip understated Mental Misstep and Dismember.
    ("pips/phyrexian is free", "{U/P}", []),
    ("pips/phyrexian mixed", "{1}{B/P}{B/P}", []),
    # {2/W} is two-brid, payable with generic.
    ("pips/twobrid is generic", "{2/W}{2/W}", []),
    ("pips/snow is generic", "{2}{S}", []),
]


@pytest.mark.parametrize("label,cost,want", PIPS, ids=[p[0] for p in PIPS])
def test_pips_from_cost(mm, label, cost, want):
    assert mm.pips_from_cost(cost) == want


# --- castable_faces --------------------------------------------------
# Split cards carry a top-level cmc equal to the SUM of both halves --
# right for the stack, wrong for "can I cast this on curve".
def test_castable_faces_split(mm):
    """castable_faces/split"""
    split = card(type_line="Instant // Sorcery", layout="split", cmc=10,
                 card_faces=[{"name": "Commit", "mana_cost": "{3}{U}"},
                             {"name": "Memory", "mana_cost": "{4}{U}{U}"}])
    assert sorted((n, mv) for n, _c, mv in mm.castable_faces(split)) == [
        ("Commit", 4), ("Memory", 6)]


def test_castable_faces_normal(mm):
    """castable_faces/normal"""
    assert list(mm.castable_faces(card(type_line="Creature", cmc=5,
                                       mana_cost="{2}{R}{G}{W}", name="Pantlaza"))) == [
        ("Pantlaza", "{2}{R}{G}{W}", 5)]
