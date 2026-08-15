"""Ported from `selftest`: build_land_profiles, build_accel_profiles, playsim sanity."""
import random

import pytest

from conftest import card


@pytest.fixture
def scry():
    return {
        "taiga": card(name="Taiga", type_line="Land — Mountain Forest",
                      oracle_text="({T}: Add {R} or {G}.)", produced_mana=["R", "G"]),
        "ancient tomb": card(name="Ancient Tomb", type_line="Land",
                             oracle_text="{T}: Add {C}{C}. Ancient Tomb deals 2 "
                                         "damage to you.", produced_mana=["C"]),
        "mystic gate": card(name="Mystic Gate", type_line="Land",
                            oracle_text="{T}: Add {C}. {W/U}, {T}: Add {W}{W}, "
                                        "{W}{U}, or {U}{U}.", produced_mana=["C", "W", "U"]),
        "wooded foothills": card(name="Wooded Foothills", type_line="Land",
                                 oracle_text="{T}, Pay 1 life, Sacrifice this land: "
                                             "Search your library for a Mountain or "
                                             "Forest card, put it onto the battlefield, "
                                             "then shuffle.", produced_mana=[]),
        "jetmir's garden": card(name="Jetmir's Garden",
                                type_line="Land — Mountain Forest Plains",
                                oracle_text="Jetmir's Garden enters tapped. "
                                            "({T}: Add {R}, {G}, or {W}.) Cycling {3}",
                                produced_mana=["R", "G", "W"]),
    }


@pytest.fixture
def profs(mm, scry):
    return {p["name"]: p for p in mm.build_land_profiles(list(scry), scry)}


def test_profiles_count(profs):
    """profiles/count"""
    assert len(profs) == 5


def test_dual_amount_is_1(profs):
    """profiles/dual amount is 1"""
    assert profs["taiga"]["amount"] == 1


def test_triome_amount_is_1(profs):
    """profiles/triome amount is 1"""
    assert profs["jetmir's garden"]["amount"] == 1


def test_ancient_tomb_amount_is_2(profs):
    """profiles/ancient tomb amount is 2"""
    assert profs["ancient tomb"]["amount"] == 2


def test_filter_flagged(profs):
    """profiles/filter flagged"""
    assert profs["mystic gate"]["filter"] == "WU"


def test_filter_amount_is_1(profs):
    """profiles/filter amount is 1"""
    assert profs["mystic gate"]["amount"] == 1


def test_fetch_reaches_typed_lands(profs):
    """profiles/fetch reaches typed lands"""
    assert profs["wooded foothills"]["colours"] == frozenset("RGW")


def test_fetch_never_tapped(profs):
    """profiles/fetch never tapped"""
    assert profs["wooded foothills"]["tapped"] is False


def test_triome_truly_tapped(profs):
    """profiles/triome truly tapped"""
    assert profs["jetmir's garden"]["tapped"] is True


# --- playsim sanity ---------------------------------------------------
def test_playsim_no_lands_means_no_mana(mm):
    """playsim/no lands means no mana"""
    rounds = mm.playsim([], [], 99, 3, False, 200, random.Random(17))
    assert max(sum(p.get("amount", 1) for p in s) for s in rounds[3]) == 0


def test_playsim_all_lands_means_n_mana_on_turn_n(mm, profs):
    """playsim/all lands means N mana on turn N"""
    one = dict(profs["taiga"])
    rounds = mm.playsim([one] * 99, [], 99, 3, False, 200, random.Random(17))
    assert min(sum(p.get("amount", 1) for p in s) for s in rounds[3]) == 3


# --- profiles carry colourless production -----------------------------
@pytest.fixture
def pscry():
    return {
        "ancient tomb": card(name="Ancient Tomb", type_line="Land",
                             oracle_text="{T}: Add {C}{C}.", produced_mana=["C"]),
        "sol ring": card(name="Sol Ring", type_line="Artifact", cmc=1,
                         oracle_text="{T}: Add {C}{C}.", produced_mana=["C"]),
    }


def test_land_keeps_colourless(mm, pscry):
    """profiles/land keeps colourless"""
    lp = {p["name"]: p for p in mm.build_land_profiles(list(pscry), pscry)}
    assert ("C" in lp["ancient tomb"]["colours"]) is True


def test_accel_keeps_colourless(mm, pscry):
    """profiles/accel keeps colourless"""
    ap_ = {p["name"]: p for p in mm.build_accel_profiles(list(pscry), pscry)}
    assert ("C" in ap_["sol ring"]["colours"]) is True


# --- what counts as an accelerant -------------------------------------
# A mana source is a PERMANENT with an activated ability that adds mana.
# Oracle text below comes from the frozen caches, never from memory.
@pytest.fixture(scope="module")
def caches():
    import json
    import os

    from conftest import FIXTURES
    out = {}
    for deck in ("mono", "multi", "colourless"):
        with open(os.path.join(FIXTURES, f"{deck}.scry.json"), encoding="utf-8") as f:
            out.update(json.load(f))
    return out


@pytest.mark.parametrize("name,counted", [
    # permanents that tap for mana: the ordinary case
    ("Sol Ring", True),
    ("Birds of Paradise", True),
    ("Mind Stone", True),
    # a permanent whose mana ability costs a SACRIFICE, not {T}. Requiring
    # {T} looks like the obvious rule and silently drops these two; they are
    # real, repeatable sources. Found by surveying the fixtures, not by
    # reading the code.
    ("Ashnod's Altar", True),
    ("Phyrexian Altar", True),
    # one-shots. Dark Ritual is an Instant of mana value 1 that was counted
    # as a permanent producing THREE mana every turn from the moment it was
    # drawn; Seething Song was counted as five.
    ("Dark Ritual", False),
    ("Seething Song", False),
    ("Jeska's Will", False),
    # the "add" is inside a Treasure token's parenthetical reminder text.
    # An Offer You Can't Refuse is a counterspell, and its Treasures go to
    # the OPPONENT -- it was counted as a source of yours.
    ("An Offer You Can't Refuse", False),
    ("Deadly Dispute", False),
    ("Warping Wail", False),
    # deferred and conditional: mana at your next main phase, if it countered
    ("Mana Drain", False),
], ids=lambda v: v if isinstance(v, str) else ("counted" if v else "not counted"))
def test_only_permanents_with_a_mana_ability_count(mm, caches, name, counted):
    assert name.lower() in caches, f"{name} missing from the fixture caches"
    got = mm.build_accel_profiles([name], caches)
    assert bool(got) is counted, (name, got)


def test_reminder_text_strip_is_not_applied_to_lands(mm, caches):
    """accel/stripping reminder text would break a dual land

    An ABUR dual's entire oracle text is reminder text -- Bayou's is exactly
    "({T}: Add {B} or {G}.)". The strip belongs to the accelerant gate only;
    applying it in build_land_profiles would leave every dual producing
    nothing at all.
    """
    bayou = caches["bayou"]
    assert bayou["oracle_text"] == "({T}: Add {B} or {G}.)"   # the whole ability
    prof = mm.build_land_profiles(["Bayou"], caches)
    assert prof and prof[0]["colours"] == frozenset("BG")
    assert prof[0]["amount"] == 1
