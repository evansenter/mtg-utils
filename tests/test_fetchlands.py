"""The fetch family: which of them give you mana on the turn you play one.

`kind == "fetch"` is set for any land producing no mana of its own whose text
searches the library for a land, and that is three different cards wearing one
label:

    Prismatic Vista     "...put it onto the battlefield, then shuffle."
    Evolving Wilds      "...put it onto the battlefield TAPPED, then shuffle."
    Bad River           "This land enters tapped." + an untapped fetch

Only the first is untapped, and `build_land_profiles` scored all three as
untapped any-colour sources -- see KNOWN_ISSUES.md #20. Oracle text here comes
from `fetchland.scry.json`, captured from Scryfall and frozen; nothing in this
file is typed from memory, because an invented wording has passed a case in
this repo before while the real card was misclassified.
"""
import json
import os
import random

import pytest

from conftest import FIXTURES

CACHE = os.path.join(FIXTURES, "fetchland.scry.json")

# Every land in the fixture. The basics are targets rather than subjects: a
# fetch's colours are read off the basic types present in the same deck.
LANDS = ["Evolving Wilds", "Terramorphic Expanse", "Fabled Passage", "Bad River",
         "Prismatic Vista", "Wooded Foothills", "Terminal Moraine",
         "Plains", "Island", "Swamp", "Mountain", "Forest"]


@pytest.fixture(scope="module")
def scry():
    with open(CACHE, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def profs(mm, scry):
    return {p["name"]: p for p in mm.build_land_profiles(LANDS, scry)}


# --- the family, one row per reason ------------------------------------
@pytest.mark.parametrize("name,tapped", [
    # produces nothing, hands you a TAPPED basic: what you have on the turn
    # you play it is what an unconditionally tapped land gives you, nothing
    ("Evolving Wilds", True),
    ("Terramorphic Expanse", True),
    # same, plus an untap clause conditional on a board state neither model
    # prices -- read at its unconditional value, which is tapped
    ("Fabled Passage", True),
    # the OTHER half of the bug: this one enters tapped itself, and the
    # hard-coded "a fetch is never tapped" overrode enters_tapped's correct
    # verdict on it
    ("Bad River", True),
    # fetches UNTAPPED: the class the universal claim was true of, and the
    # rows that must not move
    ("Prismatic Vista", False),
    ("Wooded Foothills", False),
    # carries the tapped-fetch wording AND taps for {C} the turn it lands,
    # its fetch sitting behind a {2} activation: an ordinary untapped land
    ("Terminal Moraine", False),
], ids=["fetch-tapped/Evolving Wilds is tapped",
        "fetch-tapped/Terramorphic Expanse is tapped",
        "fetch-tapped/Fabled Passage is tapped",
        "fetch-tapped/Bad River enters tapped before it fetches",
        "fetch-tapped/untapped fetch is not tapped",
        "fetch-tapped/typed untapped fetch is not tapped",
        "fetch-tapped/Terminal Moraine taps for mana itself"])
def test_fetch_tapped_verdict(profs, name, tapped):
    assert profs[name.lower()]["tapped"] is tapped


def test_the_fixture_wording_is_the_whole_distinction(scry):
    """fetch-tapped/the two wordings differ by one word

    Verbatim, from the frozen capture. The two cards are the same effect at a
    different rate and the oracle text is the only thing that says which is
    which -- so if this ever fails, the fixture was edited and every verdict
    above is measuring something else.
    """
    assert scry["evolving wilds"]["oracle_text"] == (
        "{T}, Sacrifice this land: Search your library for a basic land card, "
        "put it onto the battlefield tapped, then shuffle.")
    assert scry["prismatic vista"]["oracle_text"] == (
        "{T}, Pay 1 life, Sacrifice this land: Search your library for a basic "
        "land card, put it onto the battlefield, then shuffle.")


def test_which_half_of_the_gate_does_the_work(mm, scry):
    """fetch-tapped/Terminal Moraine is refused by the mana gate, not the wording

    Terminal Moraine passes `fetches_tapped` -- it really does put its basic
    in tapped, and in the other of the two printed phrasings ("put THAT CARD
    onto the battlefield tapped"), so this pins the wording match as well. It
    is excluded because it makes mana itself, which is the same gate
    build_land_profiles uses to call a land a fetch at all. A case that only
    asserted the final verdict would pass just as happily with the wording
    match broken.
    """
    txt = scry["terminal moraine"]["oracle_text"].lower()
    assert mm.fetches_tapped(txt) is True
    assert mm.is_tapped_fetcher(scry["terminal moraine"]) is False


def test_terminal_moraine_stays_off_the_fetch_path(profs):
    """fetch-tapped/Terminal Moraine keeps its own {C}

    The colours say which path it took: read as a fetch it would produce the
    five basics' colours off the rest of the deck, and it produces {C}.
    """
    assert profs["terminal moraine"]["colours"] == frozenset("C")


# --- the header has to agree with the models ---------------------------
def test_verify_counts_a_tapped_fetcher(mm, scry):
    """fetch-tapped/verify counts them as truly tapped

    `mana` prints "N truly tapped" over the same page as the figures the
    models produce. Evolving Wilds does not enter tapped -- the basic does --
    so enters_tapped alone left the header calling a land untapped while the
    simulation beside it scored the land tapped.
    """
    v = mm.verify("Kenrith, the Returned King", {n: 1 for n in LANDS}, scry)
    assert "Evolving Wilds" in v["truly_tapped"]
    assert "Prismatic Vista" not in v["truly_tapped"]
    assert v["truly_tapped_copies"] == 4      # the four tapped rows above


def test_verify_and_the_profiles_agree_on_every_land(mm, scry, profs):
    """fetch-tapped/one predicate, both call sites

    The invariant rather than the instance: whatever the models score tapped,
    the header says is tapped. Two places deciding the same thing from
    different reads is how the land and accelerant restriction rules drifted
    apart (KNOWN_ISSUES.md #16).
    """
    v = mm.verify("Kenrith, the Returned King", {n: 1 for n in LANDS}, scry)
    header = {n.lower() for n in v["truly_tapped"]}
    model = {n for n, p in profs.items() if p["tapped"]}
    assert header == model


# --- and it reaches a reported number -----------------------------------
def _line(mm, scry, fetch, seed=17):
    """The sources model on turn one, off a manabase of one fetch repeated."""
    lands = [p for p in mm.build_land_profiles([fetch] * 24 + ["Plains"] * 12, scry)]
    return mm.probability(lands, [], 99, ["W"], 1, 1, 4000, random.Random(seed))


def test_a_tapped_fetch_costs_a_reported_figure(mm, scry):
    """fetch-tapped/the figure moves

    The verdict is only worth pinning if it reaches the number. Same seed,
    same 36 lands, same turn-one {W} line; the only difference is which fetch
    fills 24 of the slots. Scored untapped, the two were indistinguishable.
    """
    untapped = _line(mm, scry, "Prismatic Vista")
    tapped = _line(mm, scry, "Evolving Wilds")
    assert untapped - tapped > 0.20, (untapped, tapped)
