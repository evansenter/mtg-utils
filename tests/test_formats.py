"""Deck size and legality are FORMAT facts, not constants.

`write` asserted `total == 100` and `verify` warned against 100 and read
`legalities["commander"]`. On a 60-card Standard Brawl list that made `write`
unusable -- so the list was assembled by hand, losing both the read-back
assertion and --adds/--cuts verification -- and made a correct deck look
broken. Everything else `verify` printed for that deck was already right.
"""
from collections import Counter

import pytest

from conftest import card


@pytest.mark.parametrize("fmt,size", [
    ("commander", 100), ("brawl", 100), ("standardbrawl", 60), (None, 100)],
    ids=["format/commander is 100", "format/brawl is 100",
         "format/standard brawl is 60", "format/no format is commander"])
def test_deck_size_comes_from_the_format(mm, fmt, size):
    assert mm.deck_size(fmt) == size


def test_an_unknown_format_fails_by_name(mm):
    """format/an unknown format raises

    Falling back to Commander would run the whole report against the wrong
    size and the wrong legality key while printing the format that was asked
    for at the top of it.
    """
    with pytest.raises(SystemExit) as e:
        mm.format_spec("pauper")
    assert "unknown format" in str(e.value)
    assert "standardbrawl" in str(e.value)


def test_legality_reads_the_formats_own_key(mm):
    """format/legality is read per format

    Sol Ring is Commander-legal and NOT Standard Brawl legal, which is the
    pair that makes reading one key for the other useless in both directions.
    """
    sol_ring = {"legalities": {"commander": "legal",
                               "standardbrawl": "not_legal"}}
    assert mm.is_legal(sol_ring, "commander")
    assert not mm.is_legal(sol_ring, "standardbrawl")


def test_a_card_the_cache_never_saw_is_not_legal(mm):
    """format/an unknown card is not legal

    Nothing says it is. `verify` reports NOT FOUND separately, which is the
    distinction that matters when a name is simply misspelled.
    """
    assert not mm.is_legal(None, "commander")
    assert not mm.is_legal({}, "commander")


# --- write -------------------------------------------------------------
def _write(mm, tmp_path, n, **kw):
    entries = Counter({f"Card {i}": 1 for i in range(n)})
    return mm.write_deck("Cmdr", entries, str(tmp_path / "out.txt"), **kw)


def test_write_accepts_a_60_card_brawl_list(mm, tmp_path, capsys):
    """write/a 60-card list writes under standardbrawl"""
    assert _write(mm, tmp_path, 59, fmt="standardbrawl") == 60
    assert "read back: 59 entries, 60 cards" in capsys.readouterr().out


def test_write_still_refuses_a_60_card_list_as_commander(mm, tmp_path):
    """write/the assertion itself is right and stays

    The constant was wrong, not the check. A `write` that accepted any total
    would lose the one thing it exists to provide.
    """
    with pytest.raises(AssertionError) as e:
        _write(mm, tmp_path, 59)
    assert str(e.value).startswith("deck is 60 cards, Commander is 100")


def test_write_names_the_format_it_measured_against(mm, tmp_path):
    """write/the failure names the format, not just a number

    'deck is 99 cards, Standard Brawl is 60' says which rule was applied;
    'deck is 99 cards, Commander is 100' under --format=standardbrawl would
    send the reader to fix the wrong thing.
    """
    with pytest.raises(AssertionError) as e:
        _write(mm, tmp_path, 98, fmt="standardbrawl")
    assert "Standard Brawl is 60" in str(e.value)


def test_write_size_overrides_the_format(mm, tmp_path):
    """write/--size wins over the format's own size"""
    assert _write(mm, tmp_path, 39, size=40) == 40


# --- verify ------------------------------------------------------------
def test_verify_reads_the_formats_legality_key(mm):
    """verify/illegal is measured against the format asked for

    The same list, the same card, two formats: Sol Ring is illegal in
    Standard Brawl and legal in Commander, and reading the Commander key for
    a Brawl deck reports a clean list that cannot be registered.
    """
    scry = {
        "cmdr": card(name="Cmdr", type_line="Legendary Creature", cmc=3,
                     mana_cost="{1}{R}{G}", color_identity=["R", "G"],
                     legalities={"commander": "legal",
                                 "standardbrawl": "legal"}),
        "sol ring": card(name="Sol Ring", type_line="Artifact", cmc=1,
                         mana_cost="{1}", color_identity=[],
                         legalities={"commander": "legal",
                                     "standardbrawl": "not_legal"}),
    }
    entries = Counter({"Sol Ring": 1})
    assert mm.verify("Cmdr", entries, scry, "commander")["illegal"] == []
    assert mm.verify("Cmdr", entries, scry, "standardbrawl")["illegal"] == [
        ("Sol Ring", "not_legal")]
