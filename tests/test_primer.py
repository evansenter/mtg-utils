"""Primer link validation.

A primer is prose, so before this nothing checked it at all. Two failures were
hit by hand in a single session, and both are invisible in the source text:

    [[Sword of Feast          a hard wrap puts a newline inside the brackets;
    and Famine]]              the link renders as literal text, brackets and
                              all, and the words still read correctly in the
                              markdown so proofreading does not catch it

    [[Force of Will]]         cut from the list months ago; the paragraph
                              still argues for it, because editing a decklist
                              touches nothing in the prose

The wrapped case is the one that motivated the regex being written with
re.S. WITHOUT DOTALL a wrapped link does not match the link pattern at all --
so the scan walks past the single link on the page that does not render, and
reports a clean primer. Matching it and rejecting it is the point; declining
to match it is how the check silently passes.

`tests/fixtures/primer.md` carries one instance of each finding and is
deliberately free of any bracket syntax in its prose -- a fixture that
discusses the markup it is parsed for ends up containing links nobody wrote.
It also has NO typo'd link, so every name in it resolves from the committed
projection and the report path needs no network; the not-a-card finding is
driven through primer_audit directly, which is where that logic lives.
"""
import json
import os
import shutil

import pytest

from conftest import FIXTURES

PRIMER = os.path.join(FIXTURES, "primer.md")
PRIMER_SCRY = os.path.join(FIXTURES, "primer.scry.json")
MULTI = os.path.join(FIXTURES, "multi.txt")


def _text():
    with open(PRIMER, encoding="utf-8") as f:
        return f.read()


def _scry():
    with open(PRIMER_SCRY, encoding="utf-8") as f:
        return json.load(f)


def _deck(mm):
    return mm.read_decklist(MULTI)


# --- extraction -------------------------------------------------------
def test_a_wrapped_link_is_found_at_all(mm):
    """THE case this module was written for.

    A pattern without re.S does not match this text, so the check reports zero
    problems on a primer whose link does not render. The assertion is that the
    link is SEEN -- flagging it is the next test's job, and it cannot be
    flagged if it was never matched.
    """
    links = mm.parse_primer_links("intro [[Sword of Feast\nand Famine]] outro")
    assert len(links) == 1
    assert links[0]["wrapped"] is True


def test_a_wrapped_link_still_reports_which_card_it_meant(mm):
    """"line 84 is broken and it means Sword of Feast and Famine" is an
    actionable sentence; "line 84 is broken" is a search."""
    links = mm.parse_primer_links("[[Sword of Feast\nand Famine]]")
    assert links[0]["name"] == "Sword of Feast and Famine"


def test_a_set_code_is_stripped_from_the_name(mm):
    """[[Sol Ring|LEA]] is the same card as [[Sol Ring]]. Left on, every
    deliberately-pinned printing in a primer reads as a card Scryfall has
    never heard of."""
    links = mm.parse_primer_links("[[Sol Ring|LEA]]")
    assert links[0]["name"] == "Sol Ring"


def test_links_carry_their_line_number(mm):
    """The value of the report is being told where to look. A list of bad card
    names in a 3000-word primer is barely better than no report."""
    links = mm.parse_primer_links("a\nb\n[[Sol Ring]]\nc\n[[Mox Diamond]]")
    assert [l["line"] for l in links] == [3, 5]


def test_an_opener_with_no_closer_is_reported(mm):
    """It cannot appear in the link list -- the pattern needs a closing pair to
    match -- so without this check it is not merely unreported, it is
    invisible: the card it names is never checked against anything."""
    text = "fine [[Sol Ring]]\nand then [[Ancient Tomb"
    links = mm.parse_primer_links(text)
    assert [l["name"] for l in links] == ["Sol Ring"]
    assert mm.unclosed_openers(text, links) == [2]


def test_a_closed_link_is_not_also_counted_as_unclosed(mm):
    """The mirror of the case above. Counting every opener would report a
    dangling bracket on every healthy link in the file, and a check that fires
    on everything is a check that gets switched off."""
    text = "[[Sol Ring]] and [[Ancient Tomb]]"
    assert mm.unclosed_openers(text, mm.parse_primer_links(text)) == []


# --- the audit --------------------------------------------------------
def test_a_link_to_a_cut_card_is_reported(mm):
    """The failure a primer accumulates on its own."""
    a = mm.primer_audit("[[Force of Will]] is great",
                        "Muldrotha, the Gravetide", {"Sol Ring": 1},
                        {"force of will": {"name": "Force of Will"}})
    assert [l["name"] for l in a["not_in_deck"]] == ["Force of Will"]
    assert a["ok"] is False


def test_a_link_to_a_card_in_the_deck_is_not_reported(mm):
    a = mm.primer_audit("[[Sol Ring]] is great", "Muldrotha, the Gravetide",
                        {"Sol Ring": 1}, {"sol ring": {"name": "Sol Ring"}})
    assert a["not_in_deck"] == []
    assert a["ok"] is True


def test_the_commander_is_never_reported_as_cut(mm):
    """The commander is in the deck and is not in `entries`. A primer names it
    in the first sentence, so getting this wrong makes every primer fail on
    its own title."""
    a = mm.primer_audit("[[Muldrotha, the Gravetide]] replays permanents",
                        "Muldrotha, the Gravetide", {"Sol Ring": 1},
                        {"muldrotha, the gravetide": {"name": "Muldrotha"}})
    assert a["not_in_deck"] == []


@pytest.mark.parametrize("link,entry", [
    ("Commit", "Commit // Memory"),
    ("Commit // Memory", "Commit // Memory"),
    ("Commit // Memory", "Commit"),
], ids=["primer/front face vs full decklist entry",
        "primer/full name vs full decklist entry",
        "primer/full name vs front-face decklist entry"])
def test_a_dfc_matches_the_deck_whichever_side_spells_it_out(mm, link, entry):
    """The decklist spells out both halves; a primer usually writes the front
    face, which is also what EDHREC returns -- but not always, and this repo's
    own multi fixture holds "Agadeem's Awakening" front-face-only beside
    "Commit // Memory" in full. Compared as written they are different strings
    and the primer reports a card in the list as cut: the same bug ceiling was
    written to stop, in a second place.

    Both sides are reduced, so BOTH spellings must be tested. A case that only
    links the front face passes with the link side left un-normalised, which
    is half the guard doing nothing.
    """
    a = mm.primer_audit(f"[[{link}]] is the reset", "Muldrotha, the Gravetide",
                        {entry: 1}, {"commit": {"name": "Commit // Memory"},
                                     "commit // memory": {"name": "Commit"}})
    assert a["not_in_deck"] == []


def test_a_typo_is_reported_as_not_a_card(mm):
    """A dead link still reads as an argument for a card that is in the deck.
    Driven here rather than through the report because a name Scryfall does
    not know is, by construction, a name no committed cache can hold -- the
    report path would have to reach the network to find that out."""
    a = mm.primer_audit("[[Cyclonic Riftt]] wins", "Muldrotha, the Gravetide",
                        {"Cyclonic Rift": 1}, {"cyclonic rift": {"name": "x"}})
    assert [l["name"] for l in a["not_found"]] == ["Cyclonic Riftt"]
    assert a["not_in_deck"] == []


def test_a_wrapped_link_is_reported_once_not_three_times(mm):
    """A broken link naming a cut card qualifies for all three findings. One
    broken link is one problem, and listing it three times buries the other
    two -- which is how a report with a real finding in it gets skimmed."""
    a = mm.primer_audit("[[Force of\nWill]] is great",
                        "Muldrotha, the Gravetide", {"Sol Ring": 1},
                        {"force of will": {"name": "Force of Will"}})
    assert len(a["wrapped"]) == 1
    assert a["not_found"] == []
    assert a["not_in_deck"] == []


def test_the_fixture_primer_finds_each_failure_exactly_once(mm):
    """End to end over the committed primer, which carries one of each."""
    cmdr, entries = _deck(mm)
    a = mm.primer_audit(_text(), cmdr, entries, _scry())
    assert [l["name"] for l in a["wrapped"]] == ["Agadeem's Awakening"]
    assert [l["name"] for l in a["not_in_deck"]] == ["Force of Will"]
    assert a["not_found"] == []
    assert a["unclosed"] == [42]
    assert a["ok"] is False


def test_a_clean_primer_passes(mm):
    """The mirror of every case above: the check must be capable of saying
    yes, or it is not a check, it is a complaint."""
    cmdr, entries = _deck(mm)
    a = mm.primer_audit("[[Sol Ring]] and [[Eternal Witness]] and\n"
                        "[[Ashnod's Altar]] carry the deck.",
                        cmdr, entries, _scry())
    assert a["ok"] is True
    assert a["distinct"] == 3


# --- the report -------------------------------------------------------
def _run_primer(mm, monkeypatch, tmp_path, text=None):
    import subprocess

    def boom(*a, **kw):
        raise AssertionError(
            "the offline suite tried to reach the network -- every name in "
            "the fixture primer should resolve from primer.scry.json")

    monkeypatch.setattr(subprocess, "run", boom)
    # scry_fetch rewrites its cache on every run, so the committed projection
    # is copied first -- the same trap the golden harness already handles.
    cache = os.path.join(str(tmp_path), "primer.scry.json")
    shutil.copyfile(PRIMER_SCRY, cache)
    path = PRIMER
    if text is not None:
        path = os.path.join(str(tmp_path), "custom.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    import mtg_utils.report as report
    cmdr, entries = _deck(mm)
    return report.report_primer(cmdr, entries, _scry(), path, cache)


def test_the_report_names_the_line_of_every_finding(mm, monkeypatch, tmp_path,
                                                    capsys):
    _run_primer(mm, monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert "BROKEN ACROSS LINES (1)" in out
    assert "line 21: Agadeem's Awakening" in out
    assert "LINKED BUT NOT IN THE DECK (1)" in out
    assert "line 28: Force of Will" in out
    # NEUTRAL wording. "the primer still argues for these" asserted the
    # opposite of what the section usually holds -- on the primer that
    # prompted this, 21 of 21 links here were traps entries arguing AGAINST
    # the card or suggestions not yet adopted, and zero were stale. A heading
    # that mis-frames the hit in the reassuring direction is the one that
    # trains a reader to skim past a real finding.
    assert "still argues for these" not in out
    assert "confirm each is deliberate" in out
    assert "UNCLOSED" in out and "line 42" in out


def test_the_report_says_so_when_the_primer_is_clean(mm, monkeypatch, tmp_path,
                                                     capsys):
    a = _run_primer(mm, monkeypatch, tmp_path,
                    text="[[Sol Ring]] and [[Eternal Witness]] carry it.")
    out = capsys.readouterr().out
    assert a["ok"] is True
    assert "every link renders" in out
    assert "BROKEN" not in out and "LINKED BUT NOT IN THE DECK" not in out


def test_a_wrapped_link_is_never_sent_to_scryfall(mm, monkeypatch, tmp_path):
    """Its name is a guess at what the author meant. Asking Scryfall about a
    guess turns one clear "this link is broken" into a second, contradictory
    "...and that card does not exist" -- and on a wrap that happens to split a
    name into two real words, into a network call for a card nobody named.

    The no-network guard in the harness is what enforces it, so the wrapped
    name here has to be one the committed projection does NOT hold. "Toxic
    Deluge" is in the multi decklist and deliberately absent from
    primer.scry.json: send it and scry_fetch misses the cache, reaches for
    curl, and the harness turns that into a failure. Picking a name the
    projection already has would make this case pass either way.
    """
    assert "toxic deluge" not in _scry(), \
        "this case needs a name the projection does not hold"
    a = _run_primer(mm, monkeypatch, tmp_path,
                    text="[[Toxic\nDeluge]] and [[Sol Ring]]")
    assert len(a["wrapped"]) == 1
