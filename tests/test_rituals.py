"""One-shot rituals: the single-turn burst, and everything it must not become.

A ritual is the one kind of mana in this repo that is never on the
battlefield. `KNOWN_ISSUES.md` #2 records what happened the last time one was
modelled: Dark Ritual was read as a permanent producing three mana every turn
from the moment it was drawn. So the cases here are mostly about the boundary
rather than about the burst -- four of the five near misses are cards sitting
in the committed fixtures, and each of them would be counted by a gate one
character looser:

    Warping Wail    an ability a TOKEN has, in quotes rather than parentheses
    Jeska's Will    an amount that depends on an opponent's hand
    Mana Geyser     an amount that depends on an opponent's board
    Mana Drain      deferred to a later phase, conditional on countering
    Big Score etc.  "Add one mana of any color" inside a Treasure's reminder

Every oracle string asserted against here is read out of a frozen cache rather
than typed into the test, for the reason `CLAUDE.md` gives: a case for the MDFC
land backs once used wording no printed card uses, and passed while the real
cards were misclassified.
"""
import json
import os
import random

import pytest

from conftest import FIXTURES


@pytest.fixture(scope="module")
def scry():
    """All four caches merged. The near misses are spread across three decks
    and the point of the gate is that it treats them alike."""
    out = {}
    for deck in ("mono", "multi", "colourless", "partner"):
        with open(os.path.join(FIXTURES, f"{deck}.scry.json"), encoding="utf-8") as f:
            out.update(json.load(f))
    return out


def _profiles(mm, scry, *names):
    return {p["name"]: p for p in mm.build_ritual_profiles(list(names), scry)}


def _land(colour):
    """An untapped basic producing one mana of `colour`."""
    return {"name": f"{colour.lower()} land", "kind": "land",
            "colours": frozenset(colour), "filter": None, "omni": None,
            "amount": 1, "tapped": False, "cond_tap": None,
            "restricted": False, "mdfc": False}


def _rock(cost):
    return {"name": f"{cost}-cost rock", "kind": "accel", "colours": frozenset("C"),
            "filter": None, "omni": None, "amount": 1, "cost": cost,
            "tapped": False, "cond_tap": None, "restricted": False,
            "trigger": None, "creature": False, "mdfc": False}


def _totals(rounds, turn):
    return [sum(p.get("amount", 1) for p in s) for s in rounds[turn]]


# --- the gate ---------------------------------------------------------
def test_dark_ritual_is_a_ritual_and_nets_two(mm, scry):
    """ritual/Dark Ritual nets 2, not 3

    {B} for {B}{B}{B}. The gross is what #2 counted, every turn.
    """
    p = _profiles(mm, scry, "Dark Ritual")["dark ritual"]
    assert scry["dark ritual"]["oracle_text"] == "Add {B}{B}{B}."
    assert (p["kind"], p["cost"], p["gross"], p["amount"]) == ("ritual", 1, 3, 2)
    assert p["colours"] == frozenset("B")


def test_seething_song_is_a_ritual_and_nets_two(mm, scry):
    """ritual/Seething Song nets 2, not 5

    The mono fixture's ritual, and the reason the mono snapshot moves in the
    commit that added this file. It is a ritual by exactly the same reading as
    Dark Ritual and costs three rather than one, which is the whole difference
    between netting 2 off five mana and netting 2 off three.
    """
    p = _profiles(mm, scry, "Seething Song")["seething song"]
    assert scry["seething song"]["oracle_text"] == "Add {R}{R}{R}{R}{R}."
    assert (p["cost"], p["gross"], p["amount"]) == (3, 5, 2)


def test_a_tokens_granted_ability_is_not_a_ritual(mm, scry):
    """ritual/Warping Wail makes a token, not mana

    The colourless fixture's near miss, and the sharpest one: the mana clause
    is inside DOUBLE QUOTES rather than parentheses, so stripping reminder
    text does not touch it. This case is why the colourless snapshot does not
    move.

    Asserted at BOTH levels on purpose. Two independent rules refuse this card
    and each hides the other: the clause reader will not start a clause after
    a colon, and even if it did, one mana off a two-mana instant nets less
    than nothing and the profile builder drops it. Testing only the built
    profile would leave the clause rule unguarded -- loosen the anchor and
    every assertion here still passes.
    """
    txt = scry["warping wail"]["oracle_text"]
    assert '"Sacrifice this token: Add {C}."' in txt
    assert mm.ritual_add(txt.lower()) == (set(), 0)
    assert _profiles(mm, scry, "Warping Wail") == {}


@pytest.mark.parametrize("name", ["Jeska's Will", "Mana Geyser"])
def test_an_amount_that_depends_on_an_opponent_is_not_a_ritual(mm, scry, name):
    """ritual/an opponent-dependent amount is not counted

    "Add {R} for each card in target opponent's hand" is real mana and an
    unknown quantity. Pricing it would repeat the hard-coded-tap-probability
    failure KNOWN_ISSUES #13 records, so the clause has to be nothing but mana
    symbols to count at all.

    At the clause level as well as the profile level, for the reason the
    Warping Wail case gives: Jeska's Will is a three-drop and Mana Geyser a
    five-drop, so the arithmetic and the mana-value cap would each drop them
    anyway even if the clause reader started counting "{R} for each".
    """
    txt = scry[name.lower()]["oracle_text"]
    assert "for each" in txt.lower()
    assert mm.ritual_add(txt.lower()) == (set(), 0)
    assert _profiles(mm, scry, name) == {}


def test_mana_drain_is_deferred_not_a_burst(mm, scry):
    """ritual/Mana Drain is not a ritual

    Wrong on three counts at once: the mana arrives in a later phase this
    model does not simulate, the amount is whatever it countered, and it
    arrives only if it countered something.

    Refused three times over for those three reasons, so no single-line
    mutation flips this case -- it pins an OUTCOME the whole gate owes, not
    one rule. It is here because the shape a naive gate would take ("MV <= 3,
    non-permanent, produced_mana is non-empty, 'add' appears") admits it, and
    Mana Drain's mana is the most tempting wrong answer on the list.
    """
    assert "at the beginning of your next main phase" in \
        scry["mana drain"]["oracle_text"].lower()
    assert scry["mana drain"]["produced_mana"] == ["C"]
    assert _profiles(mm, scry, "Mana Drain") == {}


@pytest.mark.parametrize("name", ["An Offer You Can't Refuse", "Deadly Dispute",
                                  "Big Score", "Unexpected Windfall"])
def test_a_treasures_reminder_text_is_not_a_ritual(mm, scry, name):
    """ritual/a Treasure maker is not a ritual

    The same trap build_accel_profiles already carries a comment about, from
    the other side: there it made a counterspell a permanent source, here it
    would make one a burst.

    What actually refuses these four is the clause shape -- "Add one mana of
    any color" is words, and only mana SYMBOLS count -- so the reminder-text
    strip above it is the second line rather than the first. The strip is
    still load-bearing for a token whose granted ability is written in
    symbols, which is a card this fixture set does not happen to hold.
    """
    txt = scry[name.lower()]["oracle_text"]
    assert "add one mana of any color" in txt.lower()
    assert mm.ritual_add(txt.lower()) == (set(), 0)
    assert _profiles(mm, scry, name) == {}


def test_an_additional_cost_is_not_priced(mm, scry):
    """ritual/Culling the Weak is not counted

    Verbatim from Scryfall; the card is in no fixture decklist, which is why
    it is built as a cache entry here rather than looked up. A ritual whose
    additional cost is a creature you may not have is a board state, and
    KNOWN_ISSUES #13 is the record of this repo declining to invent rates for
    board states.
    """
    card = {"name": "Culling the Weak", "type_line": "Instant", "cmc": 1.0,
            "mana_cost": "{B}",
            "oracle_text": ("As an additional cost to cast this spell, "
                            "sacrifice a creature.\nAdd {B}{B}{B}{B}.")}
    assert _profiles(mm, {"culling the weak": card}, "Culling the Weak") == {}
    # ... and it is the additional cost doing it, not the clause: the same
    # text without that line is a ritual netting three.
    plain = dict(card, oracle_text="Add {B}{B}{B}{B}.")
    got = _profiles(mm, {"culling the weak": plain}, "Culling the Weak")
    assert got["culling the weak"]["amount"] == 3


def test_a_conditional_second_clause_is_not_counted(mm):
    """ritual/Cabal Ritual is 3, not 8 and not 5

    Verbatim from Scryfall; in no fixture decklist, so it is built as a cache
    entry. Threshold mana is real and conditional on a graveyard this model
    does not track, and the clause reader refuses it for the same reason it
    refuses "for each": the sentence has to BE the Add.

    Both anchors refuse the Threshold clause independently -- it opens behind
    a dash and it does not end at the symbols -- so dropping either one alone
    still reads 3, and this case pins the OUTCOME rather than either rule.
    The rules themselves are pinned separately: the opening anchor by Warping
    Wail above, the closing one by Jeska's Will.
    """
    card = {"name": "Cabal Ritual", "type_line": "Instant", "cmc": 2.0,
            "mana_cost": "{1}{B}",
            "oracle_text": ("Add {B}{B}{B}.\nThreshold — Add {B}{B}{B}{B}{B} "
                            "instead if there are seven or more cards in your "
                            "graveyard.")}
    p = _profiles(mm, {"cabal ritual": card}, "Cabal Ritual")["cabal ritual"]
    assert (p["gross"], p["amount"]) == (3, 1)


def test_a_ritual_is_never_an_accelerant(mm, scry):
    """ritual/kind is ritual, and the two lists are disjoint

    The `accelerants counted:` line, `skeleton` and the `variants --accel`
    sweep all COUNT accelerants. A ritual arriving in that list would change
    what the count means without changing what the sweep varies.
    """
    for deck in ("mono", "multi", "colourless", "partner"):
        with open(os.path.join(FIXTURES, f"{deck}.scry.json"), encoding="utf-8") as f:
            cache = json.load(f)
        names = list(cache)
        rituals = mm.build_ritual_profiles(names, cache)
        accels = mm.build_accel_profiles(names, cache)
        assert all(r["kind"] == "ritual" for r in rituals), deck
        assert not ({r["name"] for r in rituals} & {a["name"] for a in accels}), deck


# --- the burst --------------------------------------------------------
def test_the_burst_is_net_not_gross(mm, scry):
    """ritual/burst is net, not gross

    One Swamp and a Dark Ritual is three mana on turn one, not four.
    """
    rits = list(_profiles(mm, scry, "Dark Ritual").values()) * 20
    rounds = mm.playsim([_land("B")] * 60, [], 99, 1, False, 400,
                        random.Random(17), rituals=rits)
    assert max(_totals(rounds, 1)) == 3


def test_a_ritual_with_no_source_of_its_colour_adds_nothing(mm, scry):
    """ritual/an unpayable ritual contributes zero

    Forests only, holding Dark Ritual. Every turn must read exactly what it
    reads with no ritual in the deck at all -- not "usually", exactly: the
    ritual entries sit after the lands in the deck list, so the same seed puts
    the same lands in the same places and the two runs are comparable trial by
    trial.

    This is the part of the model that is more than a flat bonus, and the part
    most likely to be got subtly wrong.
    """
    rits = list(_profiles(mm, scry, "Dark Ritual").values()) * 20
    forests = [_land("G")] * 60
    with_rit = mm.playsim(forests, [], 99, 4, False, 300, random.Random(17),
                          rituals=rits)
    without = mm.playsim(forests, [], 99, 4, False, 300, random.Random(17))
    for t in range(1, 5):
        assert _totals(with_rit, t) == _totals(without, t), t


def test_only_one_ritual_fires_per_turn(mm, scry):
    """ritual/one per turn

    Three Swamps pay for two Dark Rituals independently, and in real play the
    second is cast off the first's mana. Both readings compound mana this
    model invented for one turn; the cap refuses both. Three lands plus one
    net burst is 5, and 5 is the most any turn-three board here may read.
    """
    rits = list(_profiles(mm, scry, "Dark Ritual").values()) * 25
    rounds = mm.playsim([_land("B")] * 60, [], 99, 3, False, 400,
                        random.Random(17), rituals=rits)
    assert max(_totals(rounds, 3)) == 5
    # Not vacuous: hands holding two rituals are common at this density.
    assert sum(1 for s in rounds[3] if any(p["kind"] == "ritual" for p in s)) > 100


def test_a_ritual_never_funds_an_accelerant(mm, scry):
    """ritual/the burst cannot deploy a rock

    One land on turn one cannot cast a three-drop rock. With the burst read
    before the deployment loop instead of after it, the board reads three and
    the rock lands -- and unlike the burst, the rock is still there on turn
    two. That is the difference between a one-turn burst and #2's permanent
    source, arriving by the back door.
    """
    rits = list(_profiles(mm, scry, "Dark Ritual").values()) * 20
    rounds = mm.playsim([_land("B")] * 40, [_rock(3)] * 30, 99, 3, False, 400,
                        random.Random(17), rituals=rits)
    assert not any(p["kind"] == "accel" for s in rounds[1] for p in s)
    # The rock is deployable at all -- otherwise the assertion above holds for
    # a reason that has nothing to do with rituals.
    assert any(p["kind"] == "accel" for s in rounds[3] for p in s)


def test_a_held_ritual_is_still_available_later(mm, scry):
    """ritual/held in hand, not spent on the first turn it is castable

    The burst is re-read from hand every turn, so a ritual drawn on turn one
    is still a burst on turn five. That is deliberate: each turn's reading is
    its own question, and a real player holds a ritual until it pays for
    something. Firing it the moment it becomes castable would model someone
    casting Dark Ritual into an empty hand and would understate every later
    turn.

    Measured as a RATE rather than as a possibility, because "it can still
    happen" is also true of a model that spends it on sight -- the ritual just
    has to be drawn on that exact turn. One copy in 99 cards is seen by turn
    five about 11% of the time on the play, and spent-on-sight would show
    about 1%.
    """
    rits = list(_profiles(mm, scry, "Dark Ritual").values())
    rounds = mm.playsim([_land("B")] * 60, [], 99, 5, False, 3000,
                        random.Random(17), rituals=rits)
    rate = sum(1 for s in rounds[5] if any(p["kind"] == "ritual" for p in s)) / 3000
    assert 0.07 < rate < 0.15, rate


def test_the_burst_pays_pips_in_its_own_colour(mm, scry):
    """ritual/the burst is black mana, not two generic

    A single Swamp cannot cast a {B}{B}{B} spell; a Swamp and a Dark Ritual
    can. If the burst were counted as a colourless total the line would still
    read three mana and would still fail the pips.
    """
    rits = list(_profiles(mm, scry, "Dark Ritual").values()) * 20
    rounds = mm.playsim([_land("B")] * 60, [], 99, 1, False, 400,
                        random.Random(17), rituals=rits)
    assert any(mm.castable(s, ["B", "B", "B"], 3) for s in rounds[1])


# --- the report -------------------------------------------------------
def test_the_report_names_the_ritual_and_its_net(mm, capsys):
    """ritual/mana prints the burst it counted

    A moved number with nothing in the report to explain it is the failure
    this repo exists to avoid. The line says the net and says which model
    used it.
    """
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "multi.txt"))
    with open(os.path.join(FIXTURES, "multi.scry.json"), encoding="utf-8") as f:
        cache = json.load(f)
    mm.report_mana(cmdr, entries, cache, 200, 200, reps=1)
    out = capsys.readouterr().out
    assert "rituals counted, play simulation only (net burst): dark ritual +2" in out
    # The accelerant count is the number the sweep varies and must not have
    # grown by one.
    assert "accelerants counted: 13" in out


def test_a_deck_with_no_ritual_prints_no_ritual_line(mm, capsys):
    """ritual/no line when there is nothing to say

    Not cosmetic. A ritual-free deck printing byte-identical output to before
    this feature existed is what keeps the colourless fixture a live control
    on the gate: if that snapshot ever moves, something was admitted, and the
    diff is the finding rather than a header line everywhere.
    """
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "colourless.txt"))
    with open(os.path.join(FIXTURES, "colourless.scry.json"), encoding="utf-8") as f:
        cache = json.load(f)
    mm.report_mana(cmdr, entries, cache, 200, 200, reps=1)
    assert "rituals counted" not in capsys.readouterr().out
