"""Mana that is NOT free: restricted, gated on a board state, or costed.

Three spellings of one rule, all of them per LINE, because Scryfall puts one
ability per line and every string attached to a mana ability rides on the line
of the ability it attaches to:

    Spend this mana only to cast ...        the mana buys only certain spells
    {T}: Add {R}. Activate only if ...      the ability needs a board state
    {1}, {T}: Add one mana of any color.    the ability costs mana to use

The first was already modelled. The other two were not, and both INFLATE:
Blazemire Verge was an unconditional {B}{R} dual, Hidden Grotto a free
five-colour source with the {1} nowhere, and Mox Opal an any-colour source
with metalcraft nowhere.

Every oracle string here is verbatim Scryfall text, taken from the frozen
fixture caches.
"""
import json
import os

import pytest

from conftest import FIXTURES

VERGE = ("{T}: Add {B}.\n"
         "{T}: Add {R}. Activate only if you control a Swamp or a Mountain.")
GROTTO = ("When this land enters, surveil 1. (Look at the top card of your "
          "library. You may put it into your graveyard.)\n"
          "{T}: Add {C}.\n"
          "{1}, {T}: Add one mana of any color.")
TOWN = ("This land enters tapped unless it's your first, second, or third "
        "turn of the game.\n{T}: Add {C}.\n"
        "{T}, Pay 1 life: Add one mana of any color.")
MOX_OPAL = ("Metalcraft — {T}: Add one mana of any color. Activate only if "
            "you control three or more artifacts.")
TEMPLE = ("{T}: Add {C}.\n{T}: Add {C}{C}. Spend this mana only to cast "
          "colorless Eldrazi spells or activate abilities of colorless "
          "Eldrazi.")
MIND_STONE = "{T}: Add {C}.\n{1}, {T}, Sacrifice this artifact: Draw a card."
BASIC = "({T}: Add {G}.)"


# --- the filter --------------------------------------------------------
@pytest.mark.parametrize("txt,dropped", [
    (VERGE, ["{t}: add {r}. activate only if you control a swamp or a mountain."]),
    (GROTTO, ["{1}, {t}: add one mana of any color."]),
    (MOX_OPAL, [MOX_OPAL.lower()]),
    (TEMPLE, ["{t}: add {c}{c}. spend this mana only to cast colorless "
              "eldrazi spells or activate abilities of colorless eldrazi."]),
    (TOWN, []),
    (BASIC, []),
], ids=["gate/a board condition is not free mana",
        "gate/a mana cost is not free mana",
        "gate/an all-gated card keeps nothing",
        "gate/a spend-only line is still dropped",
        "gate/a life payment is still free",
        "gate/an unconditional line is untouched"])
def test_free_mana_text_drops_exactly_the_gated_lines(mm, txt, dropped):
    low = txt.lower()
    kept = mm.free_mana_text(low).split("\n")
    assert [l for l in low.split("\n") if l not in kept] == dropped


def test_a_timing_restriction_is_not_a_gate(mm):
    """gate/'activate only as a sorcery' is not a board condition

    A timing restriction says WHEN the mana can be made, not whether. Both
    models ask what mana is available on your own turn, so dropping those
    lines would understate a land that is not conditional at all.
    """
    txt = "{t}: add {r}. activate only as a sorcery."
    assert mm.free_mana_text(txt) == txt


# --- what the two shapes are worth -------------------------------------
@pytest.mark.parametrize("txt,cols,amount", [
    (VERGE, {"B"}, 1),
    (GROTTO, {"C"}, 1),
    (TOWN, set("WUBRGC"), 1),
    (MIND_STONE, {"C"}, 1),
], ids=["gate/a Verge is a mono-colour source",
        "gate/a taxed any-colour land is a {C} source",
        "gate/Starting Town keeps its any-colour half",
        "gate/a costed NON-mana line changes nothing"])
def test_unrestricted_mana(mm, txt, cols, amount):
    assert mm.unrestricted_mana(txt.lower()) == (cols, amount)


def test_an_all_gated_card_is_flagged_rather_than_zeroed(mm):
    """gate/a card whose every mana line is gated comes back restricted

    Same contract a fully restricted rock already had: the flag excludes the
    card from generic totals, it does not pretend the card taps for less than
    it does.
    """
    pm, amount, restricted = mm.drop_restricted(MOX_OPAL.lower(),
                                                set("WUBRGC"), 1)
    assert restricted is True
    assert pm == set("WUBRGC")


# --- the profiles the models actually read -----------------------------
def _profiles(mm, deck):
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, f"{deck}.txt"))
    with open(os.path.join(FIXTURES, f"{deck}.scry.json"), encoding="utf-8") as f:
        scry = json.load(f)
    names = mm.flat(cmdr, entries)[len(mm.as_cmdrs(cmdr)):]
    return ({p["name"]: p for p in mm.build_land_profiles(names, scry)},
            {p["name"]: p for p in mm.build_accel_profiles(names, scry)})


@pytest.mark.parametrize("name,cols", [
    ("blazemire verge", {"B"}),
    ("wastewood verge", {"G"}),
    ("thornspire verge", {"R"}),
    ("training compound", {"C"}),
    ("hidden grotto", {"C"}),
    ("conduit pylons", {"C"}),
    ("crystal grotto", {"C"}),
], ids=["gate/Blazemire Verge is B", "gate/Wastewood Verge is G",
        "gate/Thornspire Verge is R", "gate/Training Compound is C",
        "gate/Hidden Grotto is C", "gate/Conduit Pylons is C",
        "gate/Crystal Grotto is C"])
def test_the_land_profile_drops_the_gated_half(mm, name, cols):
    lands, _accels = _profiles(mm, "brawl")
    assert lands[name]["colours"] == frozenset(cols)
    # Not flagged out of the totals: the FREE half is real mana and the land
    # is still a source, just a narrower one than it was scored as.
    assert lands[name]["restricted"] is False


def test_a_gated_accelerant_is_excluded(mm):
    """gate/Mox Opal is not a free any-colour source

    Its mana is behind metalcraft, a board state neither model simulates --
    the same reason an event-triggered source is excluded. Found in the
    Commander fixtures, not the Brawl one: this class is not a Standard
    problem, it was simply never modelled.
    """
    _lands, accels = _profiles(mm, "mono")
    assert accels["mox opal"]["restricted"] is True


def test_a_filter_land_is_untouched(mm):
    """gate/a filter land still pairs

    Every filter land's ability reads `{U/B}, {T}: Add {U}{U}, {U}{B}, or
    {B}{B}` -- an activation cost carrying a mana symbol, which is exactly
    what the costed-line rule matches. Their colours come from the pairing
    table rather than from the text, and build_land_profiles skips the whole
    drop for them; if that ever stops being true, every filter land in the
    repo silently becomes a zero-colour source.
    """
    lands, _accels = _profiles(mm, "multi")
    assert lands["sunken ruins"]["colours"] == frozenset("UB")
    assert lands["sunken ruins"]["filter"] == "UB"
    assert lands["twilight mire"]["colours"] == frozenset("BG")


# --- a costed line is priced at its NET, not dropped --------------------
# The first version of the costed-line rule dropped every one, and no fixture
# could show what that did: the Signet cycle's ONLY mana ability is costed, so
# every colour-pair Signet was flagged restricted and fell out of the
# accelerant count. Arcane Signet, the only Signet in any fixture, costs
# nothing to activate. Both strings verbatim from Scryfall, 2026-09-24.
SIGNET = "{1}, {T}: Add {W}{U}."            # Azorius Signet
SKYCLOUD = "{1}, {T}: Add {W}{U}."          # Skycloud Expanse, a land


@pytest.mark.parametrize("txt,cols,amount", [
    (SIGNET, {"W", "U"}, 1),
    (GROTTO, {"C"}, 1),
    ("{x}, {t}: add {c}{c}.", set(), 0),
], ids=["gate/a Signet nets one mana of its colours",
        "gate/a taxed any-colour line nets zero and is dropped",
        "gate/an {X} cost cannot be priced and is dropped"])
def test_a_costed_line_counts_its_net(mm, txt, cols, amount):
    assert mm.unrestricted_mana(txt.lower()) == (cols, amount)


def test_a_signet_is_still_an_accelerant(mm):
    """gate/a colour-pair Signet is counted, not excluded

    The regression this guards is the whole reason `costed_net` exists: the
    most common rock in Commander silently stopped being a source.
    """
    scry = {"azorius signet": {"name": "Azorius Signet", "type_line": "Artifact",
                               "cmc": 2.0, "oracle_text": SIGNET,
                               "produced_mana": ["U", "W"]}}
    [p] = mm.build_accel_profiles(["Azorius Signet"], scry)
    assert p["restricted"] is False
    assert p["colours"] == frozenset("WU")
    assert p["amount"] == 1


def test_an_odyssey_filter_land_is_a_source(mm):
    """gate/Skycloud Expanse keeps its colours at its net amount

    It is not in FILTER_LANDS -- that table is the Shadowmoor cycle -- so it
    goes through the costed-line rule like any other land.
    """
    scry = {"skycloud expanse": {"name": "Skycloud Expanse", "type_line": "Land",
                                 "oracle_text": SKYCLOUD,
                                 "produced_mana": ["U", "W"]}}
    [p] = mm.build_land_profiles(["Skycloud Expanse"], scry)
    assert p["restricted"] is False
    assert p["colours"] == frozenset("WU")
