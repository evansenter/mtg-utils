"""The fifth "enters tapped" class: untapped EARLY, tapped LATE.

    Starting Town  "This land enters tapped unless it's your first, second,
                    or third turn of the game."

Nothing in CONDITIONAL_TAP_MARKERS matches that, so it fell through to TRULY
TAPPED -- understating the deck, and understating it hardest on the early
turns where a tapped land actually costs something. It also cannot be fixed by
adding the string to the marker tuple: that reports the land as never tapped,
which is wrong in the other direction from turn four onward. Both readings are
wrong, in opposite directions, which is why the class carries a TURN.

Every oracle string here is verbatim Scryfall text. A case for the MDFC land
backs once used invented wording no printed card uses, and passed while the
real cards were misclassified.
"""
import json
import os
import random

import pytest

from conftest import FIXTURES

# Verbatim, from the Scryfall record frozen in brawl.scry.json.
STARTING_TOWN = ("This land enters tapped unless it's your first, second, or "
                 "third turn of the game.\n{T}: Add {C}.\n{T}, Pay 1 life: "
                 "Add one mana of any color.")
# Verbatim: a truly tapped land, and a conditional one, for the two buckets
# this class must not be confused with.
TRULY = "This land enters tapped.\n{T}: Add {B} or {G}."
CHECK = ("This land enters tapped unless you control a Swamp or a Forest.\n"
         "{T}: Add {B} or {G}.")


def _face(txt):
    return {"oracle_text": txt, "type_line": "Land"}


# --- the classifier ----------------------------------------------------
@pytest.mark.parametrize("txt,want", [
    (STARTING_TOWN, (True, None, 4)),
    (TRULY, (True, None, None)),
    (CHECK, (False, "unless you control a", None)),
    ("{T}: Add {G}.", (False, None, None)),
], ids=["tap/turn-conditional carries its turn",
        "tap/truly tapped is unchanged",
        "tap/conditional is unchanged",
        "tap/never tapped is unchanged"])
def test_enters_tapped_turn(mm, txt, want):
    assert mm.enters_tapped_turn(_face(txt)) == want


@pytest.mark.parametrize("clause,want", [
    ("unless it's your first, second, or third turn of the game", 4),
    ("unless it's your first or second turn of the game", 3),
    ("unless it's your first turn of the game", 2),
], ids=["tap/three named turns is a 4", "tap/two named turns is a 3",
        "tap/one named turn is a 2"])
def test_the_threshold_is_one_past_the_last_ordinal(mm, clause, want):
    """The clause names the turns it enters UNTAPPED, so the answer is one
    past the LAST of them -- not the first, and not how many were listed.
    Counting the words answers 3 for 'unless it's your third turn', which is
    a card nothing prints today and would be a 4."""
    assert mm.tapped_from_turn(f"this land enters tapped {clause}.") == want


def test_an_ordinal_outside_a_turn_clause_is_not_a_threshold(mm):
    """tap/an ordinal elsewhere is not a threshold

    Anchored on "turn of the game", so a land that merely mentions "your
    first main phase" or "unless it's your turn" is not silently given one.
    """
    assert mm.tapped_from_turn("this land enters tapped unless it's your turn.") is None
    assert mm.tapped_from_turn("at the beginning of your first main phase, "
                               "this land enters tapped.") is None


def test_the_two_value_form_still_answers_tapped(mm):
    """tap/enters_tapped is unchanged for a caller that never knew the class

    A caller reading the old two-value form must be told the land IS
    sometimes tapped rather than that it never is -- the reading that would
    be wrong from turn four onward.
    """
    assert mm.enters_tapped(_face(STARTING_TOWN)) == (True, None)


# --- what the models do with it ----------------------------------------
def _land(tapped_from=None, tapped=True):
    return {"name": "town", "kind": "land", "colours": frozenset("R"),
            "filter": None, "omni": None, "amount": 1, "tapped": tapped,
            "cond_tap": None, "tapped_from": tapped_from, "mdfc": False}


@pytest.mark.parametrize("turn,want", [(3, False), (4, True)],
                         ids=["tap/untapped before the threshold",
                              "tap/tapped from the threshold"])
def test_tapped_at_reads_the_turn(mm, turn, want):
    assert mm.tapped_at(_land(4), turn) is want


def test_tapped_at_is_unchanged_without_a_threshold(mm):
    """tap/a profile with no threshold answers `tapped` unchanged

    Every accelerant profile and every land in the four Commander fixtures.
    This is what makes the class free: nothing moves on a deck without one.
    """
    assert mm.tapped_at(_land(None), 1) is True
    assert mm.tapped_at(_land(None, tapped=False), 9) is False
    assert mm.tapped_at({"tapped": False}, 1) is False


@pytest.mark.parametrize("profile,turn,want", [
    (_land(4), 3, 100.0),     # untapped early: three lands, three mana
    (_land(4), 4, 0.0),       # tapped late: the fourth enters tapped
    (_land(None), 3, 0.0),    # truly tapped: only two of three are online
    (_land(None, tapped=False), 4, 100.0),
], ids=["playsim/turn-conditional is untapped on turn three",
        "playsim/turn-conditional is tapped on turn four",
        "playsim/truly tapped is short on turn three",
        "playsim/never tapped is not short on turn four"])
def test_the_play_simulation_reads_the_threshold(mm, profile, turn, want):
    """A library of nothing but this land, so a land drop is certain and the
    only thing that can move the generic figure is when the land is usable.

    Two-sided deliberately. Asserting only the early turns would pass for a
    land read as never tapped, which is the other wrong answer.
    """
    lands = [dict(profile) for _ in range(59)]
    res = mm.playsim_report(lands, [], 59, [], 400, random.Random(17),
                            turns=turn)
    assert res["play"]["generic"][turn] == want


def test_the_sources_model_reads_the_threshold(mm):
    """sources/a turn-conditional land is untapped early

    The sources model asks about one turn at a time, so it can read the
    threshold exactly where it matters: on turn one a single land in hand is
    playable if and only if it enters untapped.
    """
    early = mm.probability([_land(4)] * 59, [], 59, ["R"], 1, 1, 400,
                           random.Random(17))
    late = mm.probability([_land(None)] * 59, [], 59, ["R"], 1, 1, 400,
                          random.Random(17))
    assert early == 1.0
    assert late == 0.0


# --- what verify says --------------------------------------------------
def test_verify_files_starting_town_in_its_own_bucket(mm):
    """verify/a turn-conditional land is neither truly nor conditionally tapped

    Read against the frozen brawl fixture rather than a hand-built card, so
    the case rests on the real printed wording.
    """
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "brawl.txt"))
    with open(os.path.join(FIXTURES, "brawl.scry.json"), encoding="utf-8") as f:
        scry = json.load(f)
    v = mm.verify(cmdr, entries, scry, "standardbrawl")
    assert v["turn_tapped"] == [("Starting Town", 4)]
    assert v["turn_tapped_copies"] == 1
    assert "Starting Town" not in v["truly_tapped"]
    assert v["truly_tapped_copies"] == 0


def test_the_land_played_is_chosen_at_the_turns_own_reading(mm):
    """playsim/an untapped-this-turn land is preferred while it is untapped

    The hand is kept sorted on a STATIC key -- untapped first, then most
    colours -- and that order is wrong on one side of the threshold. Here the
    only turn-conditional land in the deck is untapped on turn one and every
    other land is a truly tapped dual, which the static key ranks ABOVE it
    (more colours, both nominally tapped). Sorted statically the simulation
    plays a dual and reads zero mana on turn one every time.
    """
    town = _land(2)                       # untapped on turn one only
    dual = dict(_land(None), name="dual", colours=frozenset("BG"))
    lands = [town] + [dict(dual) for _ in range(58)]
    res = mm.playsim_report(lands, [], 59, [], 2000, random.Random(17),
                            turns=1)
    # ~12%: the share of opening sevens holding the one town. The claim is
    # that it is not zero -- a static sort makes it exactly zero.
    assert res["play"]["generic"][1] > 5.0
