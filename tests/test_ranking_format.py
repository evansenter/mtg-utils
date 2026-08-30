"""`ceiling` and `floor` read a COMMANDER population, whatever format you are in.

Both endpoints rank Commander decks and neither says so anywhere in its
payload. Fetched for a Standard Brawl commander during the session that
prompted this, the page recommended Enchantress's Presence, Eidolon of
Blossoms, Sythis, Starfield of Nyx, Sanctum Weaver and Sterling Grove at 27-57%
inclusion -- NOT ONE of which is legal in the format. Read by hand and
labelled, the cross-format ranking is a useful archetype signal. Run as a
recommendation engine it produces a list of unplayable cards with confident
percentages beside them.

So `ceiling` says the population is a different one, and drops the rows that
cannot be registered. `floor` says it too and drops nothing, because every card
it ranks is already in the list -- what the format changes there is what the
figures MEAN.
"""
import json
import os

import pytest

from conftest import FIXTURES, card, patch_everywhere

# EDHREC's own header, verbatim from ceiling.rec.json's shape.
SOL_RING = card(name="Sol Ring", type_line="Artifact",
                legalities={"commander": "legal", "standardbrawl": "not_legal"})
ABRADE = card(name="Abrade", type_line="Instant",
              legalities={"commander": "legal", "standardbrawl": "legal"})
# A record with NO legalities block at all: exactly the shape
# tests/fixtures/ceiling.scry.json is projected down to.
PROJECTED = card(name="Projected Card", type_line="Instant")


def _rows(*names):
    return [{"name": n, "inclusion": 90.0, "synergy": 0.1, "num_decks": 9,
             "potential_decks": 10, "cardlist": "Artifacts"} for n in names]


# --- the population warning --------------------------------------------
@pytest.mark.parametrize("source,fmt,wanted", [
    ("edhrec", None, False),
    ("edhrec", "commander", False),
    ("edhrec", "standardbrawl", True),
    ("edhtop16", "brawl", True),
], ids=["rank/commander gets no warning", "rank/explicit commander gets none",
        "rank/standard brawl is warned about",
        "rank/brawl is warned about on edhtop16"])
def test_population_mismatch(mm, source, fmt, wanted):
    lines = mm.population_mismatch(source, fmt)
    assert bool(lines) is wanted
    if wanted:
        assert lines[0].startswith("  POPULATION IS COMMANDER, NOT ")
        assert "archetype signal" in lines[1]


def test_the_warning_names_the_source_it_came_from(mm):
    """rank/each source explains its own population

    "EDHREC has no Standard Brawl page" and "edhtop16 counts Commander
    tournament entries" are different facts, and a reader deciding whether to
    trust the table needs the one that applies.
    """
    rec = mm.population_mismatch("edhrec", "standardbrawl")[0]
    top = mm.population_mismatch("edhtop16", "standardbrawl")[0]
    assert "has no Standard Brawl page" in rec
    assert "tournament entries" in top


# --- the ceiling filter ------------------------------------------------
def test_an_illegal_row_is_dropped_and_counted(mm):
    """ceiling/a row that cannot be registered is not recommended"""
    scry = {"sol ring": SOL_RING, "abrade": ABRADE}
    a = mm.ceiling_audit(["Cmdr"], {}, _rows("Sol Ring", "Abrade"), [], {},
                         scry, 50.0, "inclusion", None, "standardbrawl")
    assert [m["name"] for m in a["missing"]] == ["Abrade"]
    assert a["illegal"] == ["Sol Ring"]


def test_commander_drops_nothing(mm):
    """ceiling/the default format filters nothing

    Which is why no committed ceiling snapshot moves.
    """
    scry = {"sol ring": SOL_RING, "abrade": ABRADE}
    a = mm.ceiling_audit(["Cmdr"], {}, _rows("Sol Ring", "Abrade"), [], {},
                         scry, 50.0)
    assert sorted(m["name"] for m in a["missing"]) == ["Abrade", "Sol Ring"]
    assert a["illegal"] == []


def test_a_record_that_says_nothing_keeps_its_row(mm):
    """ceiling/silence is not evidence of illegality

    Two live cases, and both are in this repo: a name Scryfall did not know
    is reported separately as NOT FOUND, and `ceiling.scry.json` is a
    projection carrying only the fields the ceiling path reads -- four of its
    records have no `legalities` block at all. Read as illegal, they vanish
    from a Commander report about a Commander deck, and the four assertions
    around them still pass.
    """
    scry = {"projected card": PROJECTED}
    a = mm.ceiling_audit(["Cmdr"], {}, _rows("Projected Card", "Unfetched"),
                         [], {}, scry, 50.0, "inclusion", None,
                         "standardbrawl")
    assert sorted(m["name"] for m in a["missing"]) == ["Projected Card",
                                                       "Unfetched"]
    assert a["illegal"] == []


@pytest.mark.parametrize("fmt,wanted", [
    ("standardbrawl", True), ("commander", False), (None, False)],
    ids=["formats/says_illegal on a banned card",
         "formats/says_illegal on a legal card",
         "formats/says_illegal defaults to commander"])
def test_says_illegal(mm, fmt, wanted):
    assert mm.says_illegal(SOL_RING, fmt) is wanted


def test_says_illegal_is_false_when_the_record_is_silent(mm):
    """formats/says_illegal answers False for an unknown card

    The whole reason it exists beside `is_legal`, which answers False for
    both "banned" and "never heard of it".
    """
    assert mm.says_illegal(PROJECTED, "standardbrawl") is False
    assert mm.says_illegal(None, "standardbrawl") is False
    assert mm.is_legal(PROJECTED, "standardbrawl") is False


# --- what the printers actually print ----------------------------------
def _bundle(source="edhrec", rows=None):
    return {"source": source, "label": "terra-magical-adept",
            "rows": rows if rows is not None else _rows("Sol Ring", "Abrade"),
            "capped": [], "floors": {}, "n_entries": None,
            "exhaustive": source == "edhtop16"}


def _patch(mm, monkeypatch, bundle, scry=None):
    """No network anywhere: the ranking, the Scryfall lookup and Spellbook.

    `scry_fetch` returns the SAME records the caller passed in, because
    report_ceiling rebinds `scry` to what it fetches -- the above-bar cards
    are by definition not in the decklist, so their records arrive here and
    nowhere else. A fake returning {} makes every row unknown, and an unknown
    row is kept, so the filter would silently never fire.
    """
    from conftest import load_fixture_collection
    patch_everywhere(monkeypatch, "load_collection", load_fixture_collection)
    patch_everywhere(monkeypatch, "fetch_ranking",
                     lambda cmdrs, rec_cache=None, cedh=False: bundle)
    patch_everywhere(monkeypatch, "scry_fetch",
                     lambda names, path=None: (dict(scry or {}), []))
    patch_everywhere(monkeypatch, "spellbook",
                     lambda c, e, s=None: {"included": [], "almostIncluded": []})


def test_ceiling_prints_the_warning_above_the_table(mm, monkeypatch, capsys):
    """ceiling/the population warning sits under the header

    Above the first figure, deliberately: a caveat below the table is one the
    reader meets after having already believed the percentages.
    """
    import mtg_utils.report as report
    scry = {"sol ring": SOL_RING, "abrade": ABRADE}
    _patch(mm, monkeypatch, _bundle(), scry)
    report.report_ceiling(["Cmdr"], {}, scry, None, None, False, 50.0,
                          "inclusion", False, None, "standardbrawl")
    out = capsys.readouterr().out.splitlines()
    assert out[1].startswith("=== CEILING vs EDHREC")
    assert out[2].startswith("  POPULATION IS COMMANDER, NOT STANDARD BRAWL")
    assert ("  1 row above the bar is not legal in Standard Brawl and is not "
            "listed.") in out
    assert not any("Sol Ring" in l for l in out)


def test_ceiling_says_nothing_extra_for_commander(mm, monkeypatch, capsys):
    """ceiling/a Commander run is unchanged"""
    import mtg_utils.report as report
    scry = {"sol ring": SOL_RING, "abrade": ABRADE}
    _patch(mm, monkeypatch, _bundle(), scry)
    report.report_ceiling(["Cmdr"], {}, scry, None, None, False, 50.0,
                          "inclusion", False, None)
    out = capsys.readouterr().out
    assert "POPULATION IS COMMANDER" not in out
    assert "are not listed." not in out
    assert "Sol Ring" in out


def test_floor_warns_but_drops_nothing(mm, monkeypatch, capsys):
    """floor/the caveat without a filter

    Every card `floor` ranks is already in the list, so there is nothing to
    drop -- `verify` is what says whether the list is legal. What the format
    changes here is what the figures MEAN, and this command exists to price a
    cut.
    """
    import mtg_utils.report as report
    from collections import Counter
    scry = {"sol ring": SOL_RING}
    _patch(mm, monkeypatch, _bundle(rows=_rows("Sol Ring")), scry)
    report.report_floor(["Cmdr"], Counter({"Sol Ring": 1}), scry, None, False,
                        50.0, "inclusion", "standardbrawl")
    out = capsys.readouterr().out
    assert "POPULATION IS COMMANDER, NOT STANDARD BRAWL" in out
    assert "Sol Ring" in out
