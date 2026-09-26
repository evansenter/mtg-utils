"""Ported from `selftest`: load_collection and parse_moxfield."""
import pytest


# --- load_collection --------------------------------------------------
# The obvious hand-rolled loader double-counts every non-DFC because both
# keys are the same string. That shipped a contention report claiming two
# copies of Deflecting Swat when one is owned.
@pytest.fixture
def coll(mm, tmp_path):
    p = tmp_path / "coll.csv"
    p.write_text("Name,Quantity\n"
                 "Sol Ring,2\n"
                 "Sol Ring,1\n"
                 "Mana Crypt,1\n"
                 "Agadeem's Awakening // Agadeem the Undercrypt,1\n",
                 encoding="utf-8-sig")
    return mm.load_collection(str(p))


def test_collection_sums_quantities_across_printings(coll):
    """collection/sums quantities across printings

    Kept separate from the case below on purpose: this one asserts the
    quantities of two rows are ADDED.
    """
    assert coll["sol ring"] == 3


def test_collection_no_double_count(coll):
    """collection/no double count

    The front-face key must only be added when it DIFFERS from the full
    name, or every non-DFC is counted twice. Asserted on a card with ONE row,
    so this fails on its own: on Sol Ring's two rows the sibling case above
    fails too, and a pair that can only fail together tests one thing.
    """
    assert coll["mana crypt"] == 1


def test_a_missing_collection_says_how_to_supply_one(mm, tmp_path):
    """collection/missing file is a message, not a traceback"""
    with pytest.raises(SystemExit, match="--collection PATH or set MTG_COLLECTION"):
        mm.load_collection(str(tmp_path / "nope.csv"))


def test_collection_dfc_full_name(coll):
    """collection/dfc full name"""
    assert coll["agadeem's awakening // agadeem the undercrypt"] == 1


def test_collection_dfc_front_face(coll):
    """collection/dfc front face"""
    assert coll["agadeem's awakening"] == 1


# --- parse_moxfield ----------------------------------------------------
# Highest blast radius in the file: a v3 shape change would yield a
# plausible partial deck and nothing else would notice.
FIXTURE = {"name": "Test Deck", "boards": {
    "commanders": {"cards": {"aa1": {"quantity": 1, "card": {"name": "Tymna the Weaver"}}}},
    "partners": {"cards": {"bb2": {"quantity": 1, "card": {"name": "Thrasios, Triton Hero"}}}},
    "mainboard": {"cards": {"cc3": {"quantity": 1, "card": {"name": "Sol Ring"}},
                            "dd4": {"quantity": 9, "card": {"name": "Island"}}}},
    "sideboard": {"cards": {"ee5": {"quantity": 1, "card": {"name": "Ignore Me"}}}}}}


def test_moxfield_name(mm):
    """moxfield/name"""
    nm, cm, mn = mm.parse_moxfield(FIXTURE)
    assert nm == "Test Deck"


def test_moxfield_commanders_and_partners(mm):
    """moxfield/commanders and partners"""
    nm, cm, mn = mm.parse_moxfield(FIXTURE)
    assert cm == ["Tymna the Weaver", "Thrasios, Triton Hero"]


def test_moxfield_quantity_not_row_count(mm):
    """moxfield/quantity not row count"""
    nm, cm, mn = mm.parse_moxfield(FIXTURE)
    assert mn["Island"] == 9


def test_moxfield_sideboard_excluded(mm):
    """moxfield/sideboard excluded"""
    nm, cm, mn = mm.parse_moxfield(FIXTURE)
    assert ("Ignore Me" in mn) is False


def test_moxfield_no_boards_raises(mm):
    """moxfield/no boards raises

    Guards against a bad upstream response must FAIL LOUDLY, not warn: a 403
    from the UA fingerprint returns a body with no boards, and a warning
    would let a plausible empty deck through.
    """
    with pytest.raises(SystemExit):
        mm.parse_moxfield({"name": "x"})
