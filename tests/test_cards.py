"""Ported from `selftest`: mana_amount, enters_tapped, fetch_targets, DFC plumbing.

Every case below encodes a bug that ACTUALLY SHIPPED a wrong number. The case
names are the changelog and are kept verbatim.
"""
import pytest

from conftest import card

# --- mana_amount -----------------------------------------------------
# An "Add" clause lists ALTERNATIVES. Counting symbols across the whole
# clause credited every dual with 2 mana and Jetmir's Garden with 3, which
# inflated every play-simulation figure in a multicolour deck by ~15-25pts.
MANA_AMOUNT = [
    ("{T}: Add {R} or {G}.", 1),                       # any dual/shock/check
    ("{T}: Add {R}, {G}, or {W}.", 1),                 # Jetmir's Garden
    ("{T}: Add {C}{C}.", 2),                           # Ancient Tomb, Sol Ring
    ("{T}: Add {W}{U}.", 2),                           # Azorius Chancery (karoo)
    ("{T}: Add one mana of any color.", 1),            # Command Tower
    ("{T}: Add two mana of any one color.", 2),
    ("{T}: Add {G}.", 1),                              # basic
    ("{T}: Add {C}. {R/W}, {T}: Add {R}{R}, {R}{W}, or {W}{W}.", 2),  # filter
    ("", 1),
]


@pytest.mark.parametrize("txt,want", MANA_AMOUNT,
                         ids=[f"mana_amount({t[:28]!r})" for t, _ in MANA_AMOUNT])
def test_mana_amount(mm, txt, want):
    assert mm.mana_amount(txt.lower()) == want


# --- enters_tapped ---------------------------------------------------
# Three classes, only one is a real cost. A classifier that greps
# "enters tapped" flags all three; one that greps only "unless you control
# a" flagged all six shocklands as unconditionally tapped. Note the
# ORIGINAL-CASE text below: the function must lowercase before matching.
TAPPED = [
    ("shock is conditional", "As Sacred Foundry enters, you may pay 2 life. If you "
                  "don't, it enters tapped.", (False, "you may pay 2 life")),
    ("battlebond", "Spire Garden enters tapped unless you have two or more "
                   "opponents.", (False, "unless you have two or more opponents")),
    ("checkland", "Rootbound Crag enters tapped unless you control a "
                  "Mountain or a Forest.", (False, "unless you control a")),
    ("lonely mountain (an)", "The Lonely Mountain enters tapped unless you "
                             "control an Equipment.", (False, "unless you control an")),
    ("triome still truly tapped", "Jetmir's Garden enters tapped. Cycling {3}", (True, None)),
    ("basic", "{T}: Add {G}.", (False, None)),
]


@pytest.mark.parametrize("label,txt,want", TAPPED,
                         ids=[f"tapped/{lbl}" for lbl, _, _ in TAPPED])
def test_enters_tapped(mm, label, txt, want):
    assert mm.enters_tapped(card(oracle_text=txt), None) == want


# The life figure VARIES. Hard-coding the shockland's 2 sent The Black Gate
# to TRULY TAPPED, a wrong verdict that looked right and shipped in a
# calibration table. VERBATIM Scryfall text below -- an earlier version of
# this test fed the parser invented wording ("enters tapped unless you pay
# 3 life"), which no printed card actually uses, so it proved nothing.
BLACK_GATE = ("As The Black Gate enters, you may pay 3 life. If you don't, "
              "it enters tapped.\n{T}: Add {B}.")

# The whole Zendikar MDFC land-back cycle uses the same wording.
MDFC_BACK = ("As this land enters, you may pay 3 life. If you don't, it "
             "enters tapped.\n{T}: Add {B}.")


def test_black_gate_pays_3_still_conditional(mm):
    """tapped/Black Gate pays 3, still conditional"""
    assert mm.enters_tapped(card(oracle_text=BLACK_GATE), None)[0] is False


def test_black_gate_marker_is_the_matched_text(mm):
    """tapped/Black Gate marker is the matched text"""
    assert mm.enters_tapped(card(oracle_text=BLACK_GATE), None)[1] == "you may pay 3 life"


@pytest.mark.parametrize("nm", ["Agadeem the Undercrypt", "Sea Gate Reborn",
                                "Shatterskull the Hammer Pass", "Boggart Bog",
                                "Soporific Springs"],
                         ids=[f"tapped/{n} is conditional" for n in
                              ("Agadeem the Undercrypt", "Sea Gate Reborn",
                               "Shatterskull the Hammer Pass", "Boggart Bog",
                               "Soporific Springs")])
def test_mdfc_land_back_is_conditional(mm, nm):
    assert mm.enters_tapped(card(oracle_text=MDFC_BACK), None)[0] is False


def test_original_case_still_matches(mm):
    """tapped/original case still matches -- the function lowercases before matching."""
    assert mm.enters_tapped(card(oracle_text=BLACK_GATE.upper()), None)[0] is False


# --- fetch_targets ---------------------------------------------------
# produced_mana is EMPTY on a fetchland; a naive source count drops six.
def test_fetch_foothills(mm):
    """fetch/foothills"""
    assert mm.fetch_targets("search your library for a mountain or forest card") == {"R", "G"}


def test_fetch_prismatic_vista(mm):
    """fetch/prismatic vista"""
    assert mm.fetch_targets("search your library for a basic land card") == {
        "W", "U", "B", "R", "G"}


def test_fetch_not_a_fetch(mm):
    """fetch/not a fetch"""
    assert mm.fetch_targets("{t}: add {g}.") == set()


# --- DFC plumbing ----------------------------------------------------
# power/toughness/mana_cost are ABSENT at top level on a DFC. A filter like
# card.get('power','').isdigit() silently DROPS the card: Pantlaza's
# creature power was reported as 148 when it is 155.
@pytest.fixture
def mdfc():
    return card(type_line="Sorcery // Land",
                card_faces=[{"type_line": "Sorcery", "power": None,
                             "mana_cost": "{X}{B}{B}{B}", "name": "Agadeem's Awakening"},
                            {"type_line": "Land", "oracle_text": "enters tapped "
                             "As this land enters, you may pay 3 life. If you don't, it enters tapped.", "name": "Agadeem, the Undercrypt"}])


@pytest.fixture
def tdfc():
    return card(type_line="Creature — Dinosaur",
                card_faces=[{"type_line": "Creature — Dinosaur", "power": "4",
                             "toughness": "4"},
                            {"type_line": "Creature — Phyrexian", "power": "7",
                             "toughness": "7"}])


def test_is_front_land_mdfc_spell_side(mm, mdfc):
    """is_front_land/mdfc spell side"""
    assert mm.is_front_land(mdfc) is False


def test_has_land_back_mdfc(mm, mdfc):
    """has_land_back/mdfc"""
    assert mm.has_land_back(mdfc) is True


def test_front_mana_cost_off_face(mm, mdfc):
    """front/mana_cost off face"""
    assert mm.front(mdfc, "mana_cost", "") == "{X}{B}{B}{B}"


def test_front_power_off_face(mm, tdfc):
    """front/power off face"""
    assert mm.front(tdfc, "power") == "4"


def test_is_front_land_plain_land(mm):
    """is_front_land/plain land"""
    assert mm.is_front_land(card(type_line="Land — Forest")) is True


def test_has_land_back_plain_land(mm):
    """has_land_back/plain land"""
    assert mm.has_land_back(card(type_line="Land — Forest")) is False
