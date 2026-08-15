"""Ported from `selftest`: verify on a synthetic 100, and the Temp collapse."""
from collections import Counter

import pytest


# --- verify on a synthetic 100 ----------------------------------------
# "24 lands plus 75 non-land" in a 100-card deck is missing the commander,
# and that arithmetic has shipped in a primer header.
def _real(name, tl, ci, cmc=1, **kw):
    d = {"name": name, "type_line": tl, "color_identity": list(ci),
         "cmc": cmc, "oracle_text": "", "legalities": {"commander": "legal"}}
    d.update(kw)
    return d


@pytest.fixture
def vscry():
    s = {
        "tymna the weaver": _real("Tymna the Weaver", "Legendary Creature", "WB", 3),
        "thrasios, triton hero": _real("Thrasios, Triton Hero", "Legendary Creature", "GU", 2),
        "island": _real("Island", "Basic Land — Island", "", 0),
        "sol ring": _real("Sol Ring", "Artifact", "", 1),
        "agadeem's awakening": _real(
            "Agadeem's Awakening // Agadeem, the Undercrypt", "Sorcery // Land", "B", 3,
            card_faces=[{"type_line": "Sorcery", "mana_cost": "{X}{B}{B}{B}"},
                        {"type_line": "Land", "oracle_text": "As this land enters, you may pay 3 life. If you don't, it enters tapped."}]),
    }
    # A BASIC LAND has an EMPTY colour identity, so a Forest cannot test this.
    # Use a green spell: it is legal here only because Thrasios contributes G.
    # Truncating the commander list to the first entry makes it a violation --
    # exactly the silent failure a partner deck would hit.
    s["llanowar elves"] = _real("Llanowar Elves", "Creature — Elf", "G", 1)
    return s


@pytest.fixture
def vv(mm, vscry):
    ventries = Counter({"Island": 90, "Sol Ring": 6, "Llanowar Elves": 1,
                        "Agadeem's Awakening": 1})
    return mm.verify(["Tymna the Weaver", "Thrasios, Triton Hero"], ventries, vscry)


def test_verify_partners_counted_in_total(vv):
    """verify/partners counted in total"""
    assert vv["total"] == 100


def test_verify_front_face_lands(vv):
    """verify/front-face lands"""
    assert vv["lands"] == 90


def test_verify_identity_is_the_union_of_both_commanders(vv):
    """verify/identity is the UNION of both commanders"""
    assert [n for n, _ in vv["ci_violations"]] == []


def test_verify_mdfc_land_backs_separate(vv):
    """verify/mdfc land-backs separate"""
    assert vv["mdfc_land_backs"] == 1


def test_verify_nonland_excludes_both_commanders(vv):
    """verify/nonland excludes both commanders"""
    assert vv["nonland"] == 8


def test_verify_green_card_legal_under_the_union(vscry):
    """verify/green card legal under the union"""
    assert ("G" in {c for cn in ("tymna the weaver", "thrasios, triton hero")
                    for c in vscry[cn]["color_identity"]}) is True


def test_verify_arithmetic_closes(vv):
    """verify/arithmetic closes"""
    assert vv["total"] == 2 + vv["lands"] + vv["nonland"]


def test_verify_partner_identity_is_the_union(vv):
    """verify/partner identity is the union"""
    assert vv["ci_violations"] == []


# --- contention: a Temp is not a separate physical deck ---------------
def test_temp_base_name_strips_tag(mm):
    """temp/base name strips tag"""
    assert mm.deck_base_name("Muldrotha [Bracket 3 Temp]") == "muldrotha"


def test_temp_collapses_into_its_main(mm):
    """temp/collapses into its main"""
    use = {"Muldrotha [Bracket 3]": {"x"}, "Muldrotha [Bracket 3 Temp]": {"x"},
           "Teval [B4]": {"x"}}
    assert sorted(mm.collapse_temps(use)) == ["Muldrotha [Bracket 3]", "Teval [B4]"]


def test_temp_orphan_temp_stands_alone(mm):
    """temp/orphan temp stands alone"""
    assert sorted(mm.collapse_temps({"Sauron [Temp]": {"x"}})) == ["Sauron [Temp]"]


# --- the library is the deck minus its commanders ----------------------
@pytest.mark.parametrize("deck,want", [("mono", 99), ("multi", 99),
                                       ("colourless", 99), ("partner", 98)],
                         ids=["deck_size/mono is 99", "deck_size/multi is 99",
                              "deck_size/colourless is 99",
                              "deck_size/partner pair is 98"])
def test_analyse_mana_draws_from_the_real_library(mm, deck, want, monkeypatch):
    """A partner deck has 98 cards behind its two commanders, not 99.

    Simulating a library one card too large dilutes it with an extra
    non-source, which biases every figure in the same direction. Asserted by
    capturing what analyse_mana actually passes down rather than by reading
    the number off the output, because the effect on any individual line is
    a few tenths and would be indistinguishable from Monte Carlo noise.
    """
    import json
    import os

    import mtg_utils.analysis as an
    from conftest import FIXTURES

    seen = []
    real = an.playsim_report
    monkeypatch.setattr(an, "playsim_report",
                        lambda l, a, ds, *args, **kw: seen.append(ds) or real(l, a, ds, *args, **kw))
    real_prob = an.probability
    monkeypatch.setattr(an, "probability",
                        lambda l, a, ds, *args, **kw: seen.append(ds) or real_prob(l, a, ds, *args, **kw))

    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, f"{deck}.txt"))
    with open(os.path.join(FIXTURES, f"{deck}.scry.json"), encoding="utf-8") as f:
        scry = json.load(f)
    an.analyse_mana(cmdr, entries, scry, sims=20, trials=20)

    assert seen, "neither model was called"
    assert set(seen) == {want}, sorted(set(seen))
    assert want == sum(entries.values())
