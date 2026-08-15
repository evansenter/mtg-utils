"""Byte-exact output for the printers the golden suite does not run.

`test_golden.py` covers verify, mana, roster and skeleton, because those are
the subcommands that run offline through the CLI. `variants`, the named swap,
`own` and `ceiling` also run offline, and until now nothing pinned their bytes
-- so a refactor could reflow a column, drop a caveat line, or reorder a table
and every test would still pass.

These call the printers DIRECTLY rather than through the CLI. That is
deliberate: the thing at risk in a move is the printer, and going through
argparse would drag in cache plumbing (`ceiling` fetches the whole decklist at
the CLI layer) that has nothing to do with formatting.

Regenerate with the same flag as the golden suite:

    pytest tests/test_printer_snapshots.py --regen-golden

and the same rule applies -- that flag rewrites the definition of correct
output, so only reach for it when moving the output is the point.
"""
import io
import json
import os
import shutil
import subprocess
from contextlib import redirect_stdout

import pytest

from conftest import EXPECTED, FIXTURES, load_fixture_collection, patch_everywhere

SNAPS = os.path.join(EXPECTED, "printers")
COMBOS = os.path.join(FIXTURES, "ceiling.combos.json")


def _combos():
    """The frozen Spellbook response. `ceiling` cross-checks every row against
    Commander Spellbook and that is ON by default, so a snapshot of it has to
    pin the combo data too -- otherwise the printer reaches the network and
    the snapshot records whatever Spellbook said that afternoon."""
    with open(COMBOS, encoding="utf-8") as f:
        return json.load(f)


def _deck(mm, name):
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, f"{name}.txt"))
    with open(os.path.join(FIXTURES, f"{name}.scry.json"), encoding="utf-8") as f:
        return cmdr, entries, json.load(f)


def _capture(fn, *a, **kw):
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(*a, **kw)
    return buf.getvalue()


def _check(request, name, got):
    path = os.path.join(SNAPS, f"{name}.txt")
    if request.config.getoption("--regen-golden"):
        os.makedirs(SNAPS, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(got)
        pytest.skip("regenerated")
    if not os.path.exists(path):
        pytest.fail(f"missing snapshot {path} -- regenerate with --regen-golden")
    with open(path, encoding="utf-8") as f:
        assert got == f.read()


@pytest.fixture
def offline(monkeypatch):
    """No printer here may reach the network. A snapshot captured against a
    live endpoint is not a snapshot, it is a weather report."""
    def boom(*a, **kw):
        raise AssertionError("a snapshot test tried to reach the network")
    monkeypatch.setattr(subprocess, "run", boom)


def test_variants_sweep(mm, request, offline):
    """The count sweep. Small budget, fixed seed -- the numbers are pinned as
    output, not as a claim about the deck."""
    cmdr, entries, scry = _deck(mm, "multi")
    got = _capture(mm.report_variants, cmdr, entries, scry, [0, 2], [0],
                   600, 17, 3)
    _check(request, "variants", got)


def test_named_swap(mm, request, offline):
    cmdr, entries, scry = _deck(mm, "partner")
    got = _capture(mm.report_swap, cmdr, entries, scry,
                   [("Mystic Gate", "Wooded Bastion")], 300, 600, 17, 3)
    _check(request, "swap", got)


def test_own_buy_list(mm, request, monkeypatch, offline):
    patch_everywhere(monkeypatch, "load_collection", load_fixture_collection)
    cmdr, entries, scry = _deck(mm, "mono")
    got = _capture(mm.report_own, cmdr, entries, scry)
    _check(request, "own", got)


def test_ceiling_edhrec(mm, request, monkeypatch, tmp_path, offline):
    patch_everywhere(monkeypatch, "load_collection", load_fixture_collection)
    patch_everywhere(monkeypatch, "spellbook", lambda c, e: _combos())
    # scry_fetch rewrites its cache on every run, so the committed fixture is
    # copied first -- the trap the golden harness already handles.
    scry_copy = os.path.join(str(tmp_path), "ceiling.scry.json")
    shutil.copyfile(os.path.join(FIXTURES, "ceiling.scry.json"), scry_copy)
    with open(scry_copy, encoding="utf-8") as f:
        scry = json.load(f)
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "partner.txt"))
    got = _capture(mm.report_ceiling, cmdr, entries, scry, scry_copy,
                   os.path.join(FIXTURES, "ceiling.rec.json"), False, 75.0)
    _check(request, "ceiling", got)


def test_ceiling_cedh(mm, request, monkeypatch, tmp_path, offline):
    patch_everywhere(monkeypatch, "load_collection", load_fixture_collection)
    patch_everywhere(monkeypatch, "spellbook", lambda c, e: _combos())
    scry_copy = os.path.join(str(tmp_path), "ceiling.scry.json")
    shutil.copyfile(os.path.join(FIXTURES, "ceiling.scry.json"), scry_copy)
    with open(scry_copy, encoding="utf-8") as f:
        scry = json.load(f)
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "partner.txt"))
    got = _capture(mm.report_ceiling, cmdr, entries, scry, scry_copy,
                   os.path.join(FIXTURES, "ceiling.top16.json"), True, 90.0)
    _check(request, "ceiling_cedh", got)


def test_skeleton_matches_the_golden_run(mm, request, offline):
    """Called directly rather than through the CLI, so the golden snapshot
    and this one would diverge if the printer ever depended on CLI state."""
    cmdr, entries, scry = _deck(mm, "colourless")
    got = _capture(mm.report_skeleton, cmdr, entries, scry)
    with open(os.path.join(EXPECTED, "colourless.skeleton.txt"),
              encoding="utf-8") as f:
        assert got == f.read()
