"""`own --arena`: what a list costs in WILDCARDS, not in dollars.

`own` and `contention` read a ManaBox export, which is paper. Arena has no
per-card ownership file to diff a list against, so the paper question -- what
is still missing -- has no Arena answer. What survives the translation is what
the list COSTS, and Arena grants wildcards by rarity without converting between
them, so that is four numbers rather than one price.

`contention` has no Arena analogue at all and declines rather than printing a
page of reassurance about a constraint that does not exist.
"""
import json
import os
from collections import Counter

import pytest

from conftest import FIXTURES, card, run_cli

BRAWL = [os.path.join(FIXTURES, "brawl.txt"),
         f"--cache={os.path.join(FIXTURES, 'brawl.scry.json')}"]


def _deck(mm):
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "brawl.txt"))
    with open(os.path.join(FIXTURES, "brawl.scry.json"), encoding="utf-8") as f:
        return cmdr, entries, json.load(f)


def _scry(**rarities):
    out = {}
    for name, (rarity, tl) in rarities.items():
        out[name.lower()] = card(name=name, type_line=tl, rarity=rarity)
    return out


# --- the measurement ---------------------------------------------------
def test_the_counts_are_by_quantity_and_by_rarity(mm):
    """arena/wildcards are counted per copy, per rarity

    Per COPY, not per name: four Mountains are four cards and one basic-land
    line, and a list running two copies of an uncommon needs two wildcards.
    """
    scry = _scry(Cmdr=("mythic", "Legendary Creature"),
                 Bolt=("common", "Instant"),
                 Mountain=("common", "Basic Land — Mountain"))
    w = mm.wildcard_cost("Cmdr", Counter({"Bolt": 2, "Mountain": 20}), scry)
    assert w["counts"] == {"mythic": 1, "rare": 0, "uncommon": 0, "common": 2}
    assert w["basics"] == 20
    assert w["total"] == 3


def test_basics_are_excluded_and_counted_separately(mm):
    """arena/a basic land costs no wildcard

    Arena grants them without limit, so a list is never short of them. The
    same exclusion the paper buy list makes, reached from the other
    direction: there, because ManaBox does not track them.
    """
    cmdr, entries, scry = _deck(mm)
    w = mm.wildcard_cost(cmdr, entries, scry)
    assert w["basics"] == 17
    assert w["total"] + w["basics"] == 60


def test_an_unresolved_name_is_named_not_dropped(mm):
    """arena/a card Scryfall does not know is in no bucket, and says so

    A card in no bucket is a card the total does not cover, and a total that
    silently omits one is the shape of failure this repo keeps catching.
    """
    scry = _scry(Cmdr=("rare", "Legendary Creature"))
    w = mm.wildcard_cost("Cmdr", Counter({"Nonesuch": 3}), scry)
    assert w["unresolved"] == [("Nonesuch", 3)]
    assert w["total"] == 1


def test_a_rarity_that_buys_no_wildcard_is_bucketed_by_name(mm):
    """arena/'special' is not folded into one of the four

    Scryfall has `special` and `bonus` rarities and Arena has no wildcard for
    either. Folded into rare they would overstate the cost; dropped, the
    total would not add up and nothing would say why.
    """
    scry = _scry(Cmdr=("rare", "Legendary Creature"),
                 Oddity=("special", "Artifact"))
    w = mm.wildcard_cost("Cmdr", Counter({"Oddity": 1}), scry)
    assert w["other"] == {"special": 1}
    assert w["counts"]["rare"] == 1
    assert w["total"] == 2


# --- what it prints ----------------------------------------------------
def test_own_arena_prints_the_four_rarities(mm, tmp_path):
    """arena/own --arena reports wildcards, not a buy list"""
    out = run_cli(mm, ["own"] + BRAWL + ["--format=standardbrawl", "--arena"],
                  str(tmp_path))
    assert "=== ARENA WILDCARDS ===" in out
    assert "BUY LIST" not in out
    for rarity in ("mythic", "rare", "uncommon", "common"):
        assert f"  {rarity:10s}" in out
    assert "43 cards need a wildcard; 17 basic lands do not" in out


def test_own_arena_carries_its_caveat(mm, tmp_path):
    """arena/the rarity read is qualified

    Rarity varies by PRINTING, and `scry_fetch` stores whichever one Scryfall
    returned for the name. An unqualified count would be a confident wrong
    number for any card reprinted at a different rarity.
    """
    out = run_cli(mm, ["own"] + BRAWL + ["--arena"], str(tmp_path))
    assert "Rarity is the CACHED printing's" in out


def test_own_without_arena_is_the_paper_buy_list(mm, tmp_path):
    """arena/the default is unchanged"""
    out = run_cli(mm, ["own"] + BRAWL, str(tmp_path))
    assert "BUY LIST (absent from ManaBox_Collection.csv)" in out
    assert "ARENA WILDCARDS" not in out


def test_contention_declines_on_arena(mm, tmp_path):
    """arena/contention has no Arena analogue and says so

    On Arena a card in your collection is in every deck that wants it, so
    every row would read "no contention". An empty table and an inapplicable
    question look identical, and only one of them is worth printing.
    """
    out = run_cli(mm, ["contention"] + BRAWL + ["--arena"], str(tmp_path))
    assert "Not applicable on Arena" in out
    assert "owned copies vs physical decks" not in out.lower()
