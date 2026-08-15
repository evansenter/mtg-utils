"""Decision notes: why a card is not in the list, kept where the list is.

The proposal this came from wanted a checked-in ledger keyed by commander,
with rejected rows hidden behind a flag. Both halves are changed here, and the
reasons are the whole design:

**Kept in the decklist, not in a separate store keyed by commander.** A second
store is a thing nothing keeps honest: its entries are invalidated by deck
changes it cannot observe, and nothing fails when they go stale. `read_decklist`
has always skipped '#' lines, so a note in the decklist travels in the same file
as the cards it reasons about, changes in the same diff, is reviewed by whoever
edits the list -- and is invisible to every existing reader. It is also keyed
per DECK rather than per commander, which is the right key: two builds of the
same commander diverge on the first swap.

**Annotates, never suppresses.** Hiding is the one thing a note must not do. A
stale CUT would silently remove a card that has since become right, and a
shorter table reads as less work to do -- the same reason a capped cardlist is
reported rather than dropped.

**And the notes are falsifiable.** This repo does not store measurements --
`report_calibrate` says "never quote a stored row" in as many words. A judgement
is storable only if something can tell you it has gone wrong, so reasons cite
cards with [[...]], the same markup a primer uses, and the same extractor
checks both. A reason naming a card the deck no longer holds has expired.
"""
import os

import pytest

from conftest import FIXTURES, load_fixture_collection, patch_everywhere

DECK = os.path.join(FIXTURES, "partner.decisions.txt")
PLAIN = os.path.join(FIXTURES, "partner.txt")


# --- the notes are invisible to every existing reader ------------------
def test_notes_do_not_change_the_deck(mm):
    """The load-bearing property of putting them in the decklist.

    partner.decisions.txt is partner.txt with a note block on top. If those
    lines changed what the file parses to by so much as one card, every figure
    this repo produces about that deck would move -- so this is asserted
    against the frozen original rather than assumed from "read_decklist skips
    comments".
    """
    assert mm.read_decklist(DECK) == mm.read_decklist(PLAIN)


def test_an_ordinary_comment_is_not_a_decision(mm):
    """The note block in the fixture opens with four lines of prose comment.
    A parser that treated every '#' line as a note would invent four decisions
    with empty verdicts, and the staleness report would then be mostly noise
    about its own documentation."""
    got = mm.read_decisions(DECK)
    assert [d["verdict"] for d in got] == ["CUT", "TRAP", "DEFER", "CUT"]


def test_a_note_carries_its_line_number(mm):
    """A staleness report has to say WHERE, or acting on it means grepping."""
    got = mm.read_decisions(DECK)
    assert [d["line"] for d in got] == [9, 10, 11, 12]


@pytest.mark.parametrize("line,want", [
    ("# CUT: Sol Ring -- too fast", ("CUT", "Sol Ring", "too fast")),
    ("#TRAP: Sol Ring -- no space after hash",
     ("TRAP", "Sol Ring", "no space after hash")),
    ("# cut: Sol Ring -- lowercase verdict",
     ("CUT", "Sol Ring", "lowercase verdict")),
    ("# CUT: Fíli and Kíli, Joyous -- a name with a comma in it",
     ("CUT", "Fíli and Kíli, Joyous", "a name with a comma in it")),
], ids=["note/plain", "note/no space after the hash",
        "note/verdict is case-insensitive",
        "note/a card name containing a comma"])
def test_the_note_syntax(mm, tmp_path, line, want):
    """The comma case is the one that bites. Card names carry commas
    constantly -- every "Name, the Title" legend -- so the separator between
    the card and its reason has to be something a name cannot contain, which
    is why it is ' -- ' rather than a comma or a colon.
    """
    p = os.path.join(str(tmp_path), "d.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(f"Cmdr\n\n{line}\n1 Sol Ring\n")
    got = mm.read_decisions(p)
    assert (got[0]["verdict"], got[0]["card"], got[0]["reason"]) == want


# --- the two ways a note goes stale ------------------------------------
def test_a_cut_card_that_is_back_in_the_deck_is_reported(mm):
    """Someone changed their mind, or added it back without seeing the note.
    Either way the note now argues against the deck it ships with, which is
    the failure mode a ledger nobody checks reaches on its own."""
    cmdr, entries = mm.read_decklist(DECK)
    a = mm.decisions_audit(mm.read_decisions(DECK), cmdr, entries)
    assert [d["card"] for d in a["readmitted"]] == ["Sol Ring"]


def test_a_reason_citing_a_cut_card_has_expired(mm):
    """THE case the [[...]] markup exists for.

    "Destroys your own Craterhoof Behemoth" stops being true the moment
    Craterhoof is cut, and nothing about cutting Craterhoof touches this line.
    A free-text reason cannot be checked at all -- and an unfalsifiable note is
    exactly the stored row this repo refuses to quote.
    """
    cmdr, entries = mm.read_decklist(DECK)
    a = mm.decisions_audit(mm.read_decisions(DECK), cmdr, entries)
    assert [(d["card"], d["gone"]) for d in a["stale"]] == \
        [("Displacer Kitten", ["Dockside Extortionist"])]


def test_a_reason_citing_a_card_still_in_the_deck_is_not_stale(mm):
    """The mirror. Two of the fixture's four notes cite cards that ARE in the
    list, and a check that flagged those would fire on every healthy note."""
    cmdr, entries = mm.read_decklist(DECK)
    a = mm.decisions_audit(mm.read_decisions(DECK), cmdr, entries)
    assert len(a["stale"]) == 1
    assert "Wakening Sun's Avatar" not in [d["card"] for d in a["stale"]]


def test_a_defer_is_never_reported_as_readmitted(mm):
    """A defer says "not yet", so the card being in the list is the note
    coming true, not the note going wrong. Only CUT and TRAP contradict."""
    cmdr, entries = mm.read_decklist(DECK)
    notes = [{"verdict": "DEFER", "card": "Sol Ring", "reason": "later",
              "line": 1}]
    a = mm.decisions_audit(notes, cmdr, entries)
    assert a["readmitted"] == []


def test_a_dfc_note_matches_the_decklist_spelling(mm):
    """Same front-face rule as everywhere else. The decklist spells out both
    halves and a note will not."""
    a = mm.decisions_audit(
        [{"verdict": "CUT", "card": "Commit", "reason": "x", "line": 1}],
        "Cmdr", {"Commit // Memory": 1})
    assert [d["card"] for d in a["readmitted"]] == ["Commit"]


# --- the report --------------------------------------------------------
def _run(mm, monkeypatch, tmp_path, deck=DECK, **kw):
    """patch_everywhere, not setattr(report, ...).

    A module-level function resolves in the globals of the module that
    DEFINES it, so patching the package a printer used to live in keeps
    "succeeding" after the printer moves to a submodule -- while the real,
    networked function runs. This file was written before report.py became a
    package and hit exactly that.
    """
    import json
    import shutil
    import subprocess

    import mtg_utils.report as report

    patch_everywhere(monkeypatch, "load_collection", load_fixture_collection)
    patch_everywhere(monkeypatch, "spellbook",
                     lambda c, e: {"almostIncluded": []})

    def boom(*a, **kw):
        raise AssertionError("the offline suite tried to reach the network")

    monkeypatch.setattr(subprocess, "run", boom)
    cache = os.path.join(str(tmp_path), "s.json")
    shutil.copyfile(os.path.join(FIXTURES, "ceiling.scry.json"), cache)
    with open(os.path.join(FIXTURES, "ceiling.scry.json"), encoding="utf-8") as f:
        scry = json.load(f)
    cmdr, entries = mm.read_decklist(deck)
    return report.report_ceiling(
        cmdr, entries, scry, cache,
        rec_cache=os.path.join(FIXTURES, "ceiling.rec.json"),
        decklist=deck, **kw)


def test_the_report_annotates_a_ranked_row_with_its_note(mm, monkeypatch,
                                                         tmp_path, capsys):
    """Displacer Kitten is ranked at 7.9% and carries a DEFER. The annotation
    sits under the row it belongs to."""
    _run(mm, monkeypatch, tmp_path, threshold=7.0)
    out = capsys.readouterr().out.split("\n")
    i = next(n for n, l in enumerate(out) if "Displacer Kitten" in l and "%" in l)
    assert "DEFER revisit once" in out[i + 1]


def test_an_annotated_row_is_still_in_the_table(mm, monkeypatch, tmp_path):
    """ANNOTATES, NEVER SUPPRESSES. The proposal wanted these hidden behind a
    flag; a stale note would then silently remove a card that has since become
    right, and the reader would never learn it had been removed."""
    a = _run(mm, monkeypatch, tmp_path, threshold=7.0)
    assert "Displacer Kitten" in [m["name"] for m in a["missing"]]


def test_the_report_names_both_kinds_of_stale_note(mm, monkeypatch, tmp_path,
                                                   capsys):
    """Printed whether or not the stale note's card came up in this run -- a
    note nobody is looking at is exactly the one that rots."""
    _run(mm, monkeypatch, tmp_path, threshold=90.0)
    out = capsys.readouterr().out
    assert "NOTES THAT NOW CONTRADICT THE LIST (1)" in out
    assert "line 12: Sol Ring is marked CUT and is IN the deck" in out
    assert "NOTES WHOSE REASON HAS EXPIRED (1)" in out
    assert "Dockside Extortionist, no longer in the deck" in out


def test_a_deck_with_no_notes_says_nothing_about_them(mm, monkeypatch,
                                                      tmp_path, capsys):
    """Every existing caller predates notes, and a decklist without any must
    print exactly what it printed before."""
    _run(mm, monkeypatch, tmp_path, deck=PLAIN, threshold=90.0)
    assert "NOTES" not in capsys.readouterr().out
