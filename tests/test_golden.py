"""Golden output equality.

The invariant this repo is built around: no refactor may change what the tool
prints. Not "should be equivalent" -- measured equal, on real decks, byte for
byte.

Three assertions per case, and they are not redundant:

  reference == snapshot   the committed snapshot really is v0's output, and
                          not something a human typed to make a test pass
  candidate == snapshot   the current code still prints it
  reference == candidate  direct, no snapshot in the middle

The first goes away with reference/ in the final commit. The other two carry
the invariant forward permanently, which is the only reason deleting reference/
is safe.

Regenerate the snapshots (from the reference, never from the candidate) with:

    pytest tests/test_golden.py --regen-golden
"""
import os

import pytest

from conftest import DECKS, EXPECTED, deck_args, run_cli

# The offline subcommands. combos/contention/diff/calibrate/moxfield all need
# the network and are covered by unit tests over their pure parse functions
# instead; `own` additionally prints a buy list that is just load_collection
# plus the same cache, and is covered by report tests.
CMDS = ("verify", "mana", "roster")

_MEMO = {}


def _output(mod, tag, deck, cmd, tmpdir):
    """Run once per (copy, deck, subcommand) per session -- `mana` is a few
    seconds a go and three tests compare each result."""
    key = (tag, deck, cmd)
    if key not in _MEMO:
        _MEMO[key] = run_cli(mod, deck_args(deck, cmd), tmpdir)
    return _MEMO[key]


def _snapshot_path(deck, cmd):
    return os.path.join(EXPECTED, f"{deck}.{cmd}.txt")


def _read_snapshot(deck, cmd):
    path = _snapshot_path(deck, cmd)
    if not os.path.exists(path):
        pytest.fail(f"missing snapshot {path} -- regenerate with --regen-golden")
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("deck", DECKS)
@pytest.mark.parametrize("cmd", CMDS)
def test_reference_matches_snapshot(reference, deck, cmd, tmp_path, request):
    """The snapshot is v0's bytes. Without this the other two tests could agree
    on a baseline that was never produced by the code being preserved."""
    got = _output(reference, "ref", deck, cmd, str(tmp_path))
    if request.config.getoption("--regen-golden"):
        os.makedirs(EXPECTED, exist_ok=True)
        with open(_snapshot_path(deck, cmd), "w", encoding="utf-8") as f:
            f.write(got)
        pytest.skip("regenerated")
    assert got == _read_snapshot(deck, cmd)


@pytest.mark.parametrize("deck", DECKS)
@pytest.mark.parametrize("cmd", CMDS)
def test_candidate_matches_snapshot(candidate, deck, cmd, tmp_path, request):
    if request.config.getoption("--regen-golden"):
        pytest.skip("regenerating from the reference, not the candidate")
    got = _output(candidate, "cand", deck, cmd, str(tmp_path))
    assert got == _read_snapshot(deck, cmd)


@pytest.mark.parametrize("deck", DECKS)
@pytest.mark.parametrize("cmd", CMDS)
def test_reference_matches_candidate(reference, candidate, deck, cmd, tmp_path,
                                     request):
    if request.config.getoption("--regen-golden"):
        pytest.skip("regenerating")
    assert (_output(reference, "ref", deck, cmd, str(tmp_path))
            == _output(candidate, "cand", deck, cmd, str(tmp_path)))


def test_help_text_is_unchanged(reference, candidate, tmp_path, request):
    """--help prints the module docstring via argparse's `description`. Moving
    that docstring into a package without passing it explicitly silently
    replaces the whole banner with a different module's docstring."""
    ref = run_cli(reference, ["--help"], str(tmp_path))
    if request.config.getoption("--regen-golden"):
        os.makedirs(EXPECTED, exist_ok=True)
        with open(os.path.join(EXPECTED, "help.txt"), "w", encoding="utf-8") as f:
            f.write(ref)
        pytest.skip("regenerated")
    with open(os.path.join(EXPECTED, "help.txt"), encoding="utf-8") as f:
        snapshot = f.read()
    cand = run_cli(candidate, ["--help"], str(tmp_path))
    assert ref == snapshot
    assert cand == snapshot


def test_analyse_mana_returns_identical_data(reference, candidate, tmp_path):
    """Structural equality alongside the stdout diff. When a byte diff does
    appear this says which field moved, instead of leaving you to eyeball two
    forty-line reports."""
    for deck in DECKS:
        path = os.path.join(os.path.dirname(EXPECTED), f"{deck}.txt")
        cache = os.path.join(os.path.dirname(EXPECTED), f"{deck}.scry.json")
        out = {}
        for tag, mod in (("ref", reference), ("cand", candidate)):
            cmdr, entries = mod.read_decklist(path)
            scry, nf = mod.scry_fetch(mod.flat(cmdr, entries), cache)
            assert nf == [], f"{deck}: fixture cache is incomplete: {nf}"
            out[tag] = mod.analyse_mana(cmdr, entries, scry, sims=400, trials=800)
        assert out["ref"]["rows"] == out["cand"]["rows"], deck
        assert out["ref"]["sim"] == out["cand"]["sim"], deck
        assert out["ref"]["verify"] == out["cand"]["verify"], deck
        assert out["ref"]["lines"] == out["cand"]["lines"], deck


def test_colourless_worst_lines_is_not_empty(candidate, tmp_path):
    """An empty table compares equal to an empty table.

    `{C}` parsed to nothing for months, which made the colourless archetype
    report zero coloured lines -- read at the time as "this deck has no colour
    constraints" rather than as a broken parser. A golden diff cannot catch
    that on its own: both sides would be empty and agree.

    Zhulodok costs {5}{C}, so the commander's own line carries the pip.
    """
    out = _output(candidate, "cand", "colourless", "mana", str(tmp_path))
    body = out.split("--- sources model (colour), worst lines ---")[1]
    body = body.split("--- play simulation")[0]
    rows = [l for l in body.splitlines() if l.strip()]
    assert rows, "colourless deck reported no coloured lines at all"
    assert all("{C}" in l for l in rows), rows
    assert "Zhulodok, Void Gorger on curve" in out
