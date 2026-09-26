"""Golden output equality.

The invariant this repo is built around: no refactor may change what the tool
prints. Not "should be equivalent" -- measured equal, on real decks, byte for
byte.

The snapshots in tests/fixtures/expected/ began as the output of the original
single-file implementation, and through the migration to a package every case
was also diffed directly against that frozen copy -- so they are provably that
program's bytes rather than something typed to make a test pass. The copy is
gone and the snapshots carry the invariant; every deliberate move since is in
the commit that made it.

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
CMDS = ("verify", "mana", "roster", "skeleton", "variants")

# `variants` is snapshotted at a reduced budget. It sweeps six configurations
# and so runs six times the simulation `mana` does, which at the default
# --trials would have cost the suite more than everything else in it put
# together. A tenth of the budget still walks the whole path -- the sweep, the
# threading of the generator through it, the +/- columns and the formatting --
# and moves the printed figures if any of that changes.
#
# It is pinned here at all because it was the only Monte Carlo command with no
# byte-level snapshot, which made it the one place a refactor could move a
# reported number and be told so by nothing.
EXTRA = {"variants": ("--trials=2000",)}

_MEMO = {}


def _output(mod, deck, cmd, tmpdir):
    """Run once per (deck, subcommand) per session -- the colourless check
    below reads the same `mana` run the snapshot case does."""
    key = (deck, cmd)
    if key not in _MEMO:
        _MEMO[key] = run_cli(mod, deck_args(deck, cmd, EXTRA.get(cmd, ())),
                             tmpdir)
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
def test_candidate_matches_snapshot(candidate, deck, cmd, tmp_path, request):
    got = _output(candidate, deck, cmd, str(tmp_path))
    if request.config.getoption("--regen-golden"):
        os.makedirs(EXPECTED, exist_ok=True)
        with open(_snapshot_path(deck, cmd), "w", encoding="utf-8") as f:
            f.write(got)
        pytest.skip("regenerated")
    assert got == _read_snapshot(deck, cmd)


def _help_snapshot():
    with open(os.path.join(EXPECTED, "help.txt"), encoding="utf-8") as f:
        return f.read()


def test_help_text_is_unchanged(candidate, tmp_path, request):
    """--help prints the banner via argparse's `description`.

    Moving that text into a package without passing it explicitly silently
    replaces the whole banner with whichever module's docstring argparse
    happens to see.

    """
    got = run_cli(candidate, ["--help"], str(tmp_path))
    if request.config.getoption("--regen-golden"):
        os.makedirs(EXPECTED, exist_ok=True)
        with open(os.path.join(EXPECTED, "help.txt"), "w", encoding="utf-8") as f:
            f.write(got)
        pytest.skip("regenerated")
    assert got == _help_snapshot()


def test_colourless_worst_lines_is_not_empty(candidate, tmp_path):
    """An empty table compares equal to an empty table.

    `{C}` parsed to nothing for months, which made the colourless archetype
    report zero coloured lines -- read at the time as "this deck has no colour
    constraints" rather than as a broken parser. A golden diff cannot catch
    that on its own: both sides would be empty and agree.

    Zhulodok costs {5}{C}, so the commander's own line carries the pip.
    """
    out = _output(candidate, "colourless", "mana", str(tmp_path))
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


def test_brawl_fixture_is_a_60_card_standard_brawl_list(candidate):
    """The brawl fixture is the only thing here that can break a format claim.

    Four 100-card Commander decks cannot fail a hard-coded 100 or a legality
    key read off the wrong format, so a green suite over them alone is
    evidence about the fixtures. This asserts the fifth deck is still the
    shape it was added as -- a fixture that drifts out of its own format
    stops covering the thing it exists for, and does it silently.
    """
    path = os.path.join(os.path.dirname(EXPECTED), "brawl.txt")
    cache = os.path.join(os.path.dirname(EXPECTED), "brawl.scry.json")
    cmdr, entries = candidate.read_decklist(path)
    scry, nf = candidate.scry_fetch(candidate.flat(cmdr, entries), cache)
    assert nf == [], f"brawl fixture cache is incomplete: {nf}"
    v = candidate.verify(cmdr, entries, scry, "standardbrawl")
    assert v["total"] == 60
    assert len(cmdr) == 1
    assert v["illegal"] == []
    assert v["ci_violations"] == []
    # The commander is a DFC written with its front face -- the join key three
    # external sources spell three different ways.
    assert cmdr[0] == "Terra, Magical Adept"
    assert scry[cmdr[0].lower()]["name"] == "Terra, Magical Adept // Esper Terra"


def test_both_entry_points_start(tmp_path):
    """`python -m mtg_utils` and `python3 mana_model.py` are both documented,
    and the in-process harness above runs neither: it calls main() directly.
    Run as real processes, so a broken `__main__.py` or import-time error in
    the shim fails here rather than on first use. prog is argv[0], so the
    module form's usage line differs and only the body is compared."""
    import subprocess
    import sys
    from conftest import REPO
    for argv in ([sys.executable, "mana_model.py", "--help"],
                 [sys.executable, "-m", "mtg_utils", "--help"]):
        r = subprocess.run(argv, cwd=REPO, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert r.stdout.split("\n\n", 1)[1] == _help_snapshot().split("\n\n", 1)[1]
