"""`--turns`: the horizon is a caller's decision, not a constant.

PLAYSIM_TURNS is 7, documented as where a Commander game is decided. For a
60-card 1v1 game that is defensible but not obviously right, and it is a HARD
edge rather than a budget: a line landing past it is dropped, not measured
coarsely, so it becomes a row that is simply not in the table.

The horizon has to reach BOTH models from one place. `worst_lines` picks the
candidate rows and `playsim_report` measures them; a row allowed through by one
and dropped by the other is a line missing from the table beside it, with
nothing saying why.
"""
import json
import os

import pytest

from conftest import FIXTURES, run_cli

BRAWL = [os.path.join(FIXTURES, "brawl.txt"),
         f"--cache={os.path.join(FIXTURES, 'brawl.scry.json')}",
         "--format=standardbrawl"]
FAST = ["--sims=200", "--trials=400", "--reps=1"]


def _deck(mm):
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "brawl.txt"))
    with open(os.path.join(FIXTURES, "brawl.scry.json"), encoding="utf-8") as f:
        return cmdr, entries, json.load(f)


def test_the_default_horizon_is_playsim_turns(mm):
    """turns/the default is unchanged"""
    cmdr, entries, scry = _deck(mm)
    a = mm.analyse_mana(cmdr, entries, scry, sims=200, trials=400, reps=1)
    assert a["turns"] == mm.PLAYSIM_TURNS


def test_a_shorter_horizon_drops_the_later_lines(mm):
    """turns/no measured line lands past the horizon

    Both halves: the sources-model rows and the simulated lines. Asserting
    only one would pass with the two models holding different horizons, which
    is the failure this parameter exists to prevent.
    """
    cmdr, entries, scry = _deck(mm)
    a = mm.analyse_mana(cmdr, entries, scry, sims=200, trials=400, reps=1,
                        turns=3)
    assert a["rows"], "a three-turn horizon still has rows to report"
    assert all(turn <= 3 for _p, turn, _mv, _req, _c, _sp in a["rows"])
    for _label, turn in ((l, t) for l, (_m, t, _s)
                         in a["sim"]["play"]["lines"].items()):
        assert turn <= 3
    # The SIMULATION's own horizon, not just which lines survived selection:
    # `lines` is already filtered to turn <= 3 by worst_lines, so a play
    # simulation still running to seven would satisfy every assertion above
    # while doing more than twice the work and reporting baselines for turns
    # nothing asked about.
    assert sorted(a["sim"]["play"]["generic"]) == [1, 2, 3]
    assert sorted(a["sim"]["draw"]["generic"]) == [1, 2, 3]


def test_the_long_horizon_measures_lines_the_short_one_drops(mm):
    """turns/the parameter actually changes what is measured

    The brawl deck's own worst line at turn six is a green double -- with the
    horizon at three it is not a row at all. Two-sided, so a `turns` that is
    accepted and ignored fails here rather than passing quietly.
    """
    cmdr, entries, scry = _deck(mm)
    short = mm.analyse_mana(cmdr, entries, scry, 200, 400, reps=1, turns=3)
    long = mm.analyse_mana(cmdr, entries, scry, 200, 400, reps=1, turns=7)
    assert max(t for _p, t, _m, _r, _c, _s in long["rows"]) > 3
    assert max(t for _p, t, _m, _r, _c, _s in short["rows"]) <= 3


def test_the_report_names_a_non_default_horizon(mm, tmp_path):
    """turns/a shortened run says so

    Silently dropping the later half of the table would leave a report that
    looks complete and is not.
    """
    out = run_cli(mm, ["mana"] + BRAWL + FAST + ["--turns=4"], str(tmp_path))
    assert ("  horizon: turns 1-4 (default 7) -- a line landing later is not "
            "measured and is not listed.") in out


def test_the_default_run_says_nothing_about_the_horizon(mm, tmp_path):
    """turns/a default run is byte-identical

    Which is why no Commander snapshot moves.
    """
    out = run_cli(mm, ["mana"] + BRAWL + FAST, str(tmp_path))
    assert "horizon: turns" not in out


def test_turns_must_be_at_least_one(mm, tmp_path):
    """turns/zero is refused by name

    A zero horizon measures nothing and would print an empty table under a
    full set of headings.
    """
    out = run_cli(mm, ["mana"] + BRAWL + FAST + ["--turns=0"], str(tmp_path))
    assert "--turns must be at least 1, got 0" in out


# --- the play/draw framing ---------------------------------------------
def test_a_two_player_format_says_so(mm, tmp_path):
    """turns/1v1 gets the table-size note

    Both columns are correct in every format; which one a SUMMARY leans on is
    a fact about the table. The repo's default framing is the four-player one
    -- on the draw three turns in four -- and it is wrong by half in 1v1.
    """
    out = run_cli(mm, ["mana"] + BRAWL + FAST, str(tmp_path))
    assert "Standard Brawl is 2-player: you are on the draw about half the time," in out


def test_commander_keeps_the_pod_framing(mm, tmp_path):
    """turns/a four-player format adds no note"""
    out = run_cli(mm, ["mana", os.path.join(FIXTURES, "mono.txt"),
                       f"--cache={os.path.join(FIXTURES, 'mono.scry.json')}"]
                  + FAST, str(tmp_path))
    assert "-player: you are on the draw" not in out
