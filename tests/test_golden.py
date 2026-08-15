"""Golden output equality.

The invariant this repo is built around: no refactor may change what the tool
prints. Not "should be equivalent" -- measured equal, on real decks, byte for
byte.

The snapshots in tests/fixtures/expected/ began as the output of the original
single-file implementation, kept at reference/mana_model_v0.py through the
migration. While it existed each case asserted three ways -- reference against
snapshot, candidate against snapshot, and reference directly against candidate
-- so the committed snapshots are provably that program's bytes rather than
something typed to make a test pass. The reference is gone; those tests skip,
and the snapshots carry the invariant.

CHANGING A SNAPSHOT CHANGES THE DEFINITION OF CORRECT OUTPUT.

    pytest tests/test_golden.py --regen-golden

rewrites them from the CURRENT code. That is the right tool for a deliberate
change to what the tool reports and the wrong tool for everything else -- it
will happily paper over a refactor that moved a probability by half a point,
which is the exact failure this suite exists to prevent. Use it only when
moving the number is the point of the commit, review the resulting diff, and
put what moved and why in the commit message.
"""
import os

import pytest

from conftest import DECKS, EXPECTED, deck_args, run_cli

# The offline subcommands. combos/contention/diff/calibrate/moxfield all need
# the network and are covered by unit tests over their pure parse functions
# instead; `own` additionally prints a buy list that is just load_collection
# plus the same cache, and is covered by report tests.
CMDS = ("verify", "mana", "roster", "skeleton")

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
    on a baseline that was never produced by the code being preserved.

    Skips once reference/ is deleted. It does NOT regenerate: with the
    reference gone there is nothing here to regenerate from.
    """
    if request.config.getoption("--regen-golden"):
        pytest.skip("regenerating from the current code")
    assert _output(reference, "ref", deck, cmd, str(tmp_path)) == _read_snapshot(deck, cmd)


@pytest.mark.parametrize("deck", DECKS)
@pytest.mark.parametrize("cmd", CMDS)
def test_candidate_matches_snapshot(candidate, deck, cmd, tmp_path, request):
    got = _output(candidate, "cand", deck, cmd, str(tmp_path))
    if request.config.getoption("--regen-golden"):
        os.makedirs(EXPECTED, exist_ok=True)
        with open(_snapshot_path(deck, cmd), "w", encoding="utf-8") as f:
            f.write(got)
        pytest.skip("regenerated")
    assert got == _read_snapshot(deck, cmd)


@pytest.mark.parametrize("deck", DECKS)
@pytest.mark.parametrize("cmd", CMDS)
def test_reference_matches_candidate(reference, candidate, deck, cmd, tmp_path,
                                     request):
    if request.config.getoption("--regen-golden"):
        pytest.skip("regenerating")
    assert (_output(reference, "ref", deck, cmd, str(tmp_path))
            == _output(candidate, "cand", deck, cmd, str(tmp_path)))


def _help_snapshot():
    with open(os.path.join(EXPECTED, "help.txt"), encoding="utf-8") as f:
        return f.read()


def test_reference_help_matches_snapshot(reference, tmp_path, request):
    """Provenance for the help snapshot. Skips once reference/ is gone."""
    if request.config.getoption("--regen-golden"):
        pytest.skip("regenerating from the current code")
    assert run_cli(reference, ["--help"], str(tmp_path)) == _help_snapshot()


def test_help_text_is_unchanged(candidate, tmp_path, request):
    """--help prints the banner via argparse's `description`.

    Moving that text into a package without passing it explicitly silently
    replaces the whole banner with whichever module's docstring argparse
    happens to see.

    Deliberately does NOT depend on the reference fixture: this is one of the
    assertions that has to outlive reference/, and a test that skips is not a
    test. Splitting it out was prompted by running the suite with reference/
    moved aside and finding --help checked by nothing at all.
    """
    got = run_cli(candidate, ["--help"], str(tmp_path))
    if request.config.getoption("--regen-golden"):
        os.makedirs(EXPECTED, exist_ok=True)
        with open(os.path.join(EXPECTED, "help.txt"), "w", encoding="utf-8") as f:
            f.write(got)
        pytest.skip("regenerated")
    assert got == _help_snapshot()


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
    # Split on the header's stable PREFIX: it now carries the sims/reps/seed
    # provenance after this point, and matching the whole line meant a
    # format change turned this guard into an IndexError rather than into a
    # failure that says what broke. splitlines()[1:] drops the rest of the
    # header line, which is what the old exact match consumed.
    body = out.split("--- sources model (colour), worst lines")[1]
    body = body.split("--- play simulation")[0]
    rows = [l for l in body.splitlines()[1:] if l.strip()]
    assert rows, "colourless deck reported no coloured lines at all"
    assert all("{C}" in l for l in rows), rows
    assert "Zhulodok, Void Gorger on curve" in out
