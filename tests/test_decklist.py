"""Ported from `selftest`: read_decklist, write_deck, diff_multiset."""
import os
import tempfile
from collections import Counter

import pytest

from conftest import deck_args, run_cli


# --- read_decklist -----------------------------------------------------
# The front door for eight subcommands, previously untested. A partner deck
# read as one commander is a silent 99-card deck whose second commander's
# colours report as identity violations.
@pytest.fixture
def dl(tmp_path):
    def _dl(text):
        p = tmp_path / f"deck{abs(hash(text)) % 10**8}.txt"
        p.write_text(text, encoding="utf-8")
        return str(p)
    return _dl


def test_read_skips_hash_header(mm, dl):
    """read/skips # header"""
    c, e = mm.read_decklist(dl("# deck abc, fetched now\nAtraxa\n\n3 Forest\nSol Ring\n"))
    assert c == ["Atraxa"]


def test_read_quantity_parsed(mm, dl):
    """read/quantity parsed"""
    c, e = mm.read_decklist(dl("# deck abc, fetched now\nAtraxa\n\n3 Forest\nSol Ring\n"))
    assert e["Forest"] == 3


def test_read_bare_line_is_one(mm, dl):
    """read/bare line is one"""
    c, e = mm.read_decklist(dl("# deck abc, fetched now\nAtraxa\n\n3 Forest\nSol Ring\n"))
    assert e["Sol Ring"] == 1


def test_read_partner_pair(mm, dl):
    """read/partner pair"""
    c, e = mm.read_decklist(dl("Tymna the Weaver\nThrasios, Triton Hero\n\n1 Sol Ring\n"))
    assert c == ["Tymna the Weaver", "Thrasios, Triton Hero"]


def test_read_partner_body_intact(mm, dl):
    """read/partner body intact"""
    c, e = mm.read_decklist(dl("Tymna the Weaver\nThrasios, Triton Hero\n\n1 Sol Ring\n"))
    assert sum(e.values()) == 1


def test_read_no_blank_line_falls_back(mm, dl):
    """read/no blank line falls back"""
    c, e = mm.read_decklist(dl("Magda, Brazen Outlaw\n1 Sol Ring\n2 Mountain\n"))
    assert c == ["Magda, Brazen Outlaw"]


def test_read_fallback_body(mm, dl):
    """read/fallback body"""
    c, e = mm.read_decklist(dl("Magda, Brazen Outlaw\n1 Sol Ring\n2 Mountain\n"))
    assert sum(e.values()) == 3


# --- write_deck output contract --------------------------------------
# A delivered .txt once did not contain a swap the message described, and
# was imported to Moxfield in good faith. These asserts must RAISE, not warn.
@pytest.fixture
def good():
    return Counter({f"Card {i}": 1 for i in range(99)})


@pytest.fixture
def short():
    return Counter({f"Card {i}": 1 for i in range(98)})


@pytest.fixture
def quiet(capsys):
    def _quiet(fn):
        result = fn()
        capsys.readouterr()
        return result
    return _quiet


def test_write_deck_valid_100(mm, good, quiet, tmp_path):
    """write_deck/valid 100"""
    assert quiet(lambda: mm.write_deck("Cmdr", good, str(tmp_path / "a.txt"))) == 100


def test_write_deck_rejects_99_cards(mm, short, quiet, tmp_path):
    """write_deck/rejects 99 cards"""
    with pytest.raises(AssertionError):
        quiet(lambda: mm.write_deck("Cmdr", short, str(tmp_path / "b.txt")))


def test_write_deck_rejects_missing_add(mm, good, quiet, tmp_path):
    """write_deck/rejects missing add"""
    with pytest.raises(AssertionError):
        quiet(lambda: mm.write_deck("Cmdr", good, str(tmp_path / "c.txt"),
                                    expect_adds=["Nonexistent Card"]))


def test_write_deck_rejects_surviving_cut(mm, good, quiet, tmp_path):
    """write_deck/rejects surviving cut"""
    with pytest.raises(AssertionError):
        quiet(lambda: mm.write_deck("Cmdr", good, str(tmp_path / "d.txt"),
                                    expect_cuts=["Card 0"]))


def test_write_deck_idempotent(mm, good, quiet, tmp_path):
    """write_deck/idempotent

    Writing twice must not duplicate. A swap script run twice silently
    duplicated a card.
    """
    path = str(tmp_path / "e.txt")
    quiet(lambda: mm.write_deck("Cmdr", good, path))
    assert quiet(lambda: mm.write_deck("Cmdr", good, path)) == 100


# --- and the same contract reached through the CLI flag ---------------
@pytest.mark.parametrize("spec", [
    "Urborg, Tomb of Yawgmoth;Sol Ring",
    "Urborg, Tomb of Yawgmoth;",
], ids=["write/--adds with a comma'd name beside another",
        "write/--adds with a comma'd name alone"])
def test_write_adds_accepts_a_card_name_containing_a_comma(mm, tmp_path, spec):
    """End to end, because the two halves were both fine on their own: --adds
    split on ',' in cli.py, write_deck asserted on whatever names it was
    handed, and neither could see that a name had been halved on the way
    through. 'Urborg, Tomb of Yawgmoth' is in the multicolour fixture, so this
    used to die on `MISSING ADD: Urborg` -- a card the user never typed.

    Both forms are pinned because the second is the one that looks wrong. A
    lone name needs a trailing ';' to switch the separator over, since ';'
    only wins when it is PRESENT; the empty segment it leaves is dropped. That
    is the documented idiom and it is easy to "tidy away", so it is a case.

    Asserted on the exit code and the written file rather than on the flag
    parsing, which test_split_names covers: the failure being guarded is the
    CLI wiring, and the wiring is only visible from outside.
    """
    out = str(tmp_path / "written.txt")
    got = run_cli(mm, deck_args("multi", "write",
                                [f"--out={out}", f"--adds={spec}"]),
                  str(tmp_path))
    assert "[exit" not in got, got
    assert "read back: " in got, got
    with open(out, encoding="utf-8") as f:
        assert any(l.strip() == "1 Urborg, Tomb of Yawgmoth"
                   for l in f), "the add is not in the written deck"


def test_write_cuts_still_checks_a_comma_d_name(mm, tmp_path):
    """write/--cuts on a comma'd name still checks

    The mirror of the case above, and the one that matters more. A cut asserts
    ABSENCE, so a mis-split cut passes VACUOUSLY: neither 'Urborg' nor 'Tomb of
    Yawgmoth' is in the deck, write_deck's `assert not any(...)` holds, and the
    check reports success having verified nothing.

    So this asserts the FAILURE. 'Urborg, Tomb of Yawgmoth' IS in the
    multicolour fixture and `write` does not remove anything, so a cut naming
    it must be caught -- and that is precisely the assertion that goes vacuous
    under the old comma-only split. A passing run here would mean the check had
    stopped checking.

    Without this, split_names(a.cuts) could be reverted on its own and every
    other case in this file would still pass: the wiring is per-flag, and the
    --adds case only exercises the --adds half of it.
    """
    out = str(tmp_path / "cut.txt")
    with pytest.raises(AssertionError, match="CUT STILL PRESENT"):
        run_cli(mm, deck_args("multi", "write", [
            f"--out={out}", "--cuts=Urborg, Tomb of Yawgmoth;"]), str(tmp_path))


# --- write_deck with two commanders -----------------------------------
@pytest.fixture
def two():
    return Counter({f"Card {i}": 1 for i in range(98)})


def test_write_deck_partner_pair_is_100(mm, two, quiet, tmp_path):
    """write_deck/partner pair is 100"""
    assert quiet(lambda: mm.write_deck(["Tymna the Weaver", "Thrasios, Triton Hero"],
                                       two, str(tmp_path / "p.txt"))) == 100


def test_write_deck_partner_round_trips(mm, two, quiet, tmp_path):
    """write_deck/partner round-trips"""
    p = str(tmp_path / "p.txt")
    quiet(lambda: mm.write_deck(["Tymna the Weaver", "Thrasios, Triton Hero"], two, p))
    rc, re_ = mm.read_decklist(p)
    assert rc == ["Tymna the Weaver", "Thrasios, Triton Hero"]


def test_write_deck_partner_body_round_trips(mm, two, quiet, tmp_path):
    """write_deck/partner body round-trips"""
    p = str(tmp_path / "p.txt")
    quiet(lambda: mm.write_deck(["Tymna the Weaver", "Thrasios, Triton Hero"], two, p))
    rc, re_ = mm.read_decklist(p)
    assert sum(re_.values()) == 98


# --- diff_multiset -----------------------------------------------------
# lastUpdatedAtUtc moves on a description edit, so the multiset is the only
# honest test of whether a delta's base is still the base.
def test_diff_only_local(mm):
    """diff/only local"""
    ol, ov, cc = mm.diff_multiset("A", Counter({"Sol Ring": 1, "Island": 9}),
                                  ["A"], Counter({"Sol Ring": 1, "Island": 8,
                                                  "Swamp": 1}))
    assert ol == [("Island", 1)]


def test_diff_only_live(mm):
    """diff/only live"""
    ol, ov, cc = mm.diff_multiset("A", Counter({"Sol Ring": 1, "Island": 9}),
                                  ["A"], Counter({"Sol Ring": 1, "Island": 8,
                                                  "Swamp": 1}))
    assert ov == [("Swamp", 1)]


def test_diff_commander_same(mm):
    """diff/commander same"""
    ol, ov, cc = mm.diff_multiset("A", Counter({"Sol Ring": 1, "Island": 9}),
                                  ["A"], Counter({"Sol Ring": 1, "Island": 8,
                                                  "Swamp": 1}))
    assert cc is None


def test_diff_identical_body(mm):
    """diff/identical body"""
    ol, ov, cc = mm.diff_multiset("A", Counter({"X": 1}), ["B"], Counter({"X": 1}))
    assert (ol, ov) == ([], [])


def test_diff_commander_change_flagged(mm):
    """diff/commander change flagged"""
    ol, ov, cc = mm.diff_multiset("A", Counter({"X": 1}), ["B"], Counter({"X": 1}))
    assert cc == (["A"], ["B"])
