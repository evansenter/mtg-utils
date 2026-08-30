"""`write --arena`: the import block, and which printing each line names.

Arena's importer does not take a bare card name. It takes

    N Card Name (SET) CollectorNumber

and it wants a printing that exists ON ARENA, which is not the printing
Scryfall returns for a name. So every line needs a search and three filters,
and the filters were hand-rolled twice in one session before this existed.

The selection is the half that goes wrong, and `pick_arena_printing` is pure so
it can be tested without the network. `brawl.arena.json` is the frozen capture
for the brawl fixture -- every Arena printing of every card in it, projected to
the five fields the rules read, and captured with NO format filter applied so
the selection is what the suite tests rather than something already decided.
"""
import json
import os
import shutil
import subprocess
from collections import Counter

import pytest

from conftest import FIXTURES, run_cli

ARENA = os.path.join(FIXTURES, "brawl.arena.json")
BRAWL = os.path.join(FIXTURES, "brawl.txt")


@pytest.fixture
def no_network(monkeypatch):
    """A cache key that does not match what the code asks for sends the suite
    to the live endpoint and every assertion still passes -- the failure
    `_no_network` in test_ceiling.py was written after. Same guard."""
    def boom(*a, **kw):
        raise AssertionError(
            "the offline suite tried to reach Scryfall -- the arena cache key "
            "probably does not match what the code asks for")
    monkeypatch.setattr(subprocess, "run", boom)


@pytest.fixture
def arena_cache(tmp_path):
    """arena_fetch rewrites its cache on every run, so the committed fixture
    is copied first -- the same trap the golden harness handles for
    scry_fetch."""
    dst = os.path.join(str(tmp_path), "brawl.arena.json")
    shutil.copyfile(ARENA, dst)
    return dst


def _p(set_, number, released, games=("arena",), legal="legal", rarity="rare"):
    return {"set": set_, "collector_number": number, "released_at": released,
            "games": list(games), "rarity": rarity,
            "legalities": {"commander": legal, "standardbrawl": legal}}


# --- the selection rules -----------------------------------------------
def test_the_newest_arena_printing_wins(mm):
    """arena/the most recent printing is chosen

    It is the one an Arena player actually has and the one the collection UI
    shows first. Both real: Abrade is on Arena in AKR (2020) and SOA (2026).
    """
    got = mm.pick_arena_printing([_p("akr", "136", "2020-08-13"),
                                  _p("soa", "37", "2026-04-24")])
    assert (got["set"], got["collector_number"]) == ("soa", "37")


def test_a_paper_only_printing_is_refused(mm):
    """arena/a printing not on Arena is never named

    Its set code is one Arena has never heard of, and the import fails on
    that line.
    """
    assert mm.pick_arena_printing([_p("lea", "1", "2093-08-05",
                                      games=("paper",))]) is None


def test_a_printing_illegal_in_the_format_is_refused(mm):
    """arena/an illegal printing is not named

    A Standard Brawl list naming an Alchemy-only printing is an import that
    half-works, which is worse than one that does not.
    """
    old = _p("akr", "136", "2020-08-13", legal="not_legal")
    new = _p("soa", "37", "2026-04-24")
    assert mm.pick_arena_printing([old], "standardbrawl") is None
    assert mm.pick_arena_printing([old, new], "standardbrawl")["set"] == "soa"


def test_a_non_numeric_collector_number_is_refused(mm):
    """arena/a suffixed collector number is not named

    Scryfall really does return `1★`, `M19-314` and `410z` -- all three are
    verbatim, from this repo's own probes of Llanowar Elves and Sol Ring.
    Every one of them is paper-only, so the `games` filter removes them
    first and NOTHING IN brawl.arena.json EXERCISES THIS: it is a second
    guard, kept because the session that prompted this module had a promo
    printing break an import. Written against hand-built candidates for
    exactly that reason, rather than pretending the fixture covers it.
    """
    for number in ("1★", "M19-314", "410z"):
        assert mm.pick_arena_printing([_p("x", number, "2026-01-01")]) is None
    assert mm.pick_arena_printing(
        [_p("x", "1★", "2026-01-01"), _p("y", "12", "2020-01-01")])["set"] == "y"


def test_the_tie_break_is_total(mm):
    """arena/two printings released the same day sort the same way twice

    Two Arena sets really do share a release date, and a cache is a frozen
    projection: a rerun has to write the same file as the run before it.
    """
    a = _p("aaa", "1", "2026-01-01")
    b = _p("bbb", "2", "2026-01-01")
    assert mm.pick_arena_printing([a, b])["set"] == "bbb"
    assert mm.pick_arena_printing([b, a])["set"] == "bbb"


def test_no_printings_at_all_is_none_not_an_error(mm):
    """arena/a card with no Arena printing answers None

    Sol Ring has none. That is a real answer about the card, not a failure.
    """
    assert mm.pick_arena_printing([]) is None
    assert mm.pick_arena_printing(None) is None


# --- the frozen capture ------------------------------------------------
def test_the_fixture_resolves_every_card(mm, arena_cache, no_network):
    """arena/every card in the brawl list has an importable printing"""
    cmdr, entries = mm.read_decklist(BRAWL)
    prints, missing = mm.arena_printings(mm.flat(cmdr, entries),
                                         "standardbrawl", arena_cache)
    assert missing == []
    assert len(prints) == 46          # 45 decklist entries + the commander


def test_the_capture_exercises_the_choice(mm, arena_cache, no_network):
    """arena/the fixture holds real cards with several printings to choose from

    A capture with one printing per card could not test the selection at all
    -- every row would be the answer whatever the rule was. Abrade came back
    with five, spanning six years, and the newest is what gets written.

    The other two filters reject NOTHING here, and that is a fact about the
    data rather than an oversight: the search applies `game:arena` itself, and
    Scryfall's `legalities` is an oracle-level field repeated identically on
    every printing, so neither can pick one printing over another. They are
    tested above, against hand-built candidates, for exactly that reason.
    """
    got = mm.arena_fetch("Abrade", arena_cache)
    assert len(got) > 1
    dates = sorted(p["released_at"] for p in got)
    assert dates[0] != dates[-1], "one release date is no choice at all"
    assert mm.pick_arena_printing(got, "standardbrawl")["released_at"] \
        == dates[-1]


# --- the file it writes ------------------------------------------------
def _write(mm, tmp_path, arena_cache, *extra):
    out = os.path.join(str(tmp_path), "arena.txt")
    text = run_cli(mm, ["write", BRAWL,
                        f"--cache={os.path.join(FIXTURES, 'brawl.scry.json')}",
                        "--format=standardbrawl", "--arena",
                        f"--arena-cache={arena_cache}", f"--out={out}"]
                   + list(extra), str(tmp_path))
    return text, open(out, encoding="utf-8").read()


def test_the_block_structure_is_arenas(mm, tmp_path, arena_cache, no_network):
    """arena/Commander header, blank, Deck header

    Arena's own layout. A file that is right in every other respect and
    missing the `Deck` header imports as nothing.
    """
    _text, got = _write(mm, tmp_path, arena_cache)
    lines = got.splitlines()
    assert lines[0] == "Commander"
    assert lines[1] == "1 Terra, Magical Adept (FIN) 245"
    assert lines[2] == ""
    assert lines[3] == "Deck"
    assert lines[4].startswith("1 Abrade (")


def test_every_line_carries_a_printing(mm, tmp_path, arena_cache, no_network):
    """arena/no line is written without its (SET) NUMBER"""
    _text, got = _write(mm, tmp_path, arena_cache)
    body = [l for l in got.splitlines()[4:] if l.strip()]
    assert len(body) == 45
    for line in body:
        qty, rest = line.split(" ", 1)
        assert qty.isdigit()
        assert rest.rsplit(" ", 1)[1].isdigit(), line
        assert rest.rsplit(" ", 2)[1].startswith("("), line


def test_the_commander_is_written_as_its_front_face(mm, tmp_path, arena_cache,
                                                    no_network):
    """arena/Arena names a DFC by its front face

    A third convention beside EDHREC's front faces and Moxfield's and
    Commander Spellbook's full `A // B`. The commander here is
    `Terra, Magical Adept // Esper Terra` on Scryfall.
    """
    _text, got = _write(mm, tmp_path, arena_cache)
    assert "Esper Terra" not in got
    assert got.splitlines()[1].startswith("1 Terra, Magical Adept (")
    # Written from the FULL name too, which is how Moxfield and Commander
    # Spellbook spell it -- the brawl decklist happens to carry the front
    # face, so it alone cannot tell the two apart.
    out = os.path.join(str(tmp_path), "full.txt")
    mm.write_arena_deck("Terra, Magical Adept // Esper Terra",
                        Counter({"Esper Origins // Summon: Esper Maduin": 1}),
                        out, {"terra, magical adept": _p("fin", "245",
                                                         "2025-06-13"),
                              "esper origins": _p("fin", "60", "2025-06-13")},
                        size=2)
    lines = open(out, encoding="utf-8").read().splitlines()
    assert lines[1] == "1 Terra, Magical Adept (FIN) 245"
    assert lines[4] == "1 Esper Origins (FIN) 60"


def test_the_read_back_reports_the_totals(mm, tmp_path, arena_cache,
                                          no_network):
    """arena/the same read-back assertion `write` exists for

    The run that prompted all of this hand-assembled its list precisely
    because `write` refused a 60-card deck, and lost this check with it.
    """
    text, _got = _write(mm, tmp_path, arena_cache)
    assert "read back: 45 entries, 60 cards, Commander/Deck headers OK" in text


def test_adds_and_cuts_match_past_the_printing(mm, tmp_path, arena_cache,
                                               no_network):
    """arena/--adds compares the NAME, not the whole line

    Every line here carries a `(SET) NUMBER` the caller never typed, so a
    check that split on the first space would compare 'Abrade (SOA) 37'
    against 'Abrade' and pass no --adds check ever -- an assertion that
    cannot fail is one nobody should trust.
    """
    text, _got = _write(mm, tmp_path, arena_cache, "--adds=Abrade;",
                        "--cuts=Sol Ring;")
    assert "read back:" in text
    # And it can still FAIL. A check that passes for every input is not a
    # check; the AssertionError propagates out of the CLI rather than being
    # caught and printed, which is what write_deck does too.
    with pytest.raises(AssertionError) as e:
        _write(mm, tmp_path, arena_cache, "--adds=Sol Ring;")
    assert "MISSING ADD: Sol Ring" in str(e.value)


def test_a_card_with_no_printing_refuses_the_write(mm, tmp_path):
    """arena/a missing printing stops the file, by name

    Arena rejects a line with no `(SET) NUMBER` and reports the line it
    stopped on, so a file that is right for 58 cards and silently wrong for
    one is the expensive failure here.
    """
    with pytest.raises(SystemExit) as e:
        mm.write_arena_deck("Cmdr", Counter({"Sol Ring": 1}),
                            os.path.join(str(tmp_path), "x.txt"),
                            {"cmdr": _p("fin", "1", "2025-06-13")})
    assert "no importable Arena printing for 'Sol Ring'" in str(e.value)


def test_the_size_assertion_still_holds(mm, tmp_path, arena_cache):
    """arena/a wrong total still fails, naming the format"""
    prints = {"cmdr": _p("fin", "1", "2025-06-13"),
              "island": _p("fin", "2", "2025-06-13")}
    with pytest.raises(AssertionError) as e:
        mm.write_arena_deck("Cmdr", Counter({"Island": 5}),
                            os.path.join(str(tmp_path), "x.txt"), prints,
                            fmt="standardbrawl")
    assert "deck is 6 cards, Standard Brawl is 60" in str(e.value)
