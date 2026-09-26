"""Shared test plumbing.

The golden suite runs the CLI in-process over the frozen fixtures and compares
stdout byte for byte with tests/fixtures/expected/. The snapshots began as the
output of the original single-file implementation; see test_golden.py.

Nothing here may reach the network: `_no_network` below is autouse, so a
fixture cache that misses a card fails the test that missed it instead of
quietly fetching the card live and passing.
"""
import csv
import importlib.util
import io
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from contextlib import redirect_stdout, redirect_stderr

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(REPO, "tests", "fixtures")
EXPECTED = os.path.join(FIXTURES, "expected")

if REPO not in sys.path:
    sys.path.insert(0, REPO)

DECKS = ("mono", "multi", "colourless", "partner", "brawl")

# Extra CLI arguments a particular fixture deck always needs. `brawl` is the
# one deck here that is not Commander, and every subcommand accepts --format,
# so it is passed for all of them rather than per command: run as Commander
# the same file is a 60-card deck reported as 40 cards short, with a legality
# column read off the wrong key.
DECK_EXTRA = {"brawl": ("--format=standardbrawl",)}


def pytest_addoption(parser):
    parser.addoption(
        "--regen-golden", action="store_true", default=False,
        help="rewrite tests/fixtures/expected/ from the CURRENT code -- only "
             "when moving a reported number is the point of the change")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def candidate():
    """The copy the golden suite runs: the root mana_model.py entry point,
    loaded the way a user runs it."""
    return _load(os.path.join(REPO, "mana_model.py"), "_candidate_mana_model")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Every fetch in the package is `subprocess.run(["curl", ...])`, so
    refusing curl here makes the whole suite offline by construction.

    Five roster tests ran against live Scryfall for months: their walk looked
    up two cards the brawl cache never held, scry_fetch fetched them, and every
    assertion passed. A test that wants a canned response patches
    subprocess.run itself, which overrides this for its own body.
    """
    real = subprocess.run

    def guard(cmd, *a, **kw):
        if cmd and cmd[0] == "curl":
            raise AssertionError(f"test tried to reach the network: {cmd[-1]}")
        return real(cmd, *a, **kw)
    monkeypatch.setattr(subprocess, "run", guard)


@pytest.fixture(scope="session")
def mm():
    """The single copy to use for ordinary (non-golden) unit tests."""
    return _load(os.path.join(REPO, "mana_model.py"), "_unit_mana_model")


def card(**kw):
    """Ported verbatim from selftest's `_card`."""
    kw.setdefault("type_line", "Land")
    kw.setdefault("oracle_text", "")
    return kw


def src(colours="", amount=1, filt=None, omni=None, kind="land"):
    """Ported from selftest's `_src`, plus `kind`.

    The original had no `kind` because nothing read it. castable now does, for
    omni-typing only: Urborg makes every LAND a Swamp and says nothing about a
    rock. Every stand-in built by this helper represents a land -- which is
    what the omni case has always asserted, in those words -- so the default
    keeps each ported case meaning exactly what it meant.
    """
    return {"colours": frozenset(colours), "amount": amount,
            "filter": filt, "omni": omni, "kind": kind}


def load_fixture_collection(path=os.path.join(FIXTURES, "collection.csv")):
    """A stand-in for load_collection bound to the fixture CSV.

    load_collection's signature is `def load_collection(path=COLLECTION)`, so
    the default is bound at import time and patching the module's COLLECTION
    constant did nothing. The function itself is replaced, by name, everywhere
    it is bound.

    This deliberately mirrors the real loader, including the rule that the
    front-face key is only added when it differs from the full name.
    """
    owned = defaultdict(int)
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            q = int(r["Quantity"])
            n = r["Name"].strip().lower()
            owned[n] += q
            front_name = n.split(" // ")[0]
            if front_name != n:
                owned[front_name] += q
    return owned


def patch_everywhere(monkeypatch, name, replacement):
    """Rebind `name` on every loaded module that defines a function of it.

    A module-level function is looked up in the globals of the module that
    DEFINES it, not the one that calls it. So `monkeypatch.setattr(report,
    "spellbook", fake)` works only while `report_combos` lives in
    `mtg_utils.report` -- move it into a submodule and the patch still
    "succeeds", the assertion still runs, and the REAL function is called.
    Against a network dependency that means a test that quietly starts
    hitting Spellbook and passes anyway.

    Patching by name across sys.modules means a test does not encode where a
    function currently lives.

    Asserts it matched something: a patch that binds nothing is not a
    no-op, it is a test that silently talks to the outside world.
    """
    hits = 0
    for mod in list(sys.modules.values()):
        if mod is None:
            continue
        try:
            cur = getattr(mod, name, None)
        except Exception:            # module with an exotic __getattr__
            continue
        if callable(cur) and getattr(cur, "__name__", None) == name:
            monkeypatch.setattr(mod, name, replacement)
            hits += 1
    assert hits, (f"patch target {name!r} matched no loaded module -- it was "
                  f"renamed, or the module defining it is not imported yet")
    return hits


def run_cli(mod, argv, tmpdir):
    """Run `mod.main()` with argv and return everything it printed.

    The cache is copied into tmpdir first: scry_fetch writes its cache back on
    every run (json.dump at the end), so pointing it at the committed fixture
    would have the suite mutating its own inputs.
    """
    argv = list(argv)
    for i, a in enumerate(argv):
        if a.startswith("--cache="):
            src = a.split("=", 1)[1]
            dst = os.path.join(tmpdir, os.path.basename(src))
            shutil.copyfile(src, dst)
            argv[i] = f"--cache={dst}"

    old_argv = sys.argv
    # prog is derived from sys.argv[0] and appears in --help output
    sys.argv = ["mana_model.py"] + argv
    buf = io.StringIO()
    try:
        with pytest.MonkeyPatch.context() as mp, \
                redirect_stdout(buf), redirect_stderr(buf):
            patch_everywhere(mp, "load_collection", load_fixture_collection)
            try:
                mod.main()
            except SystemExit as e:
                if e.code not in (0, None):
                    buf.write(f"\n[exit {e.code}]\n")
    finally:
        sys.argv = old_argv
    return buf.getvalue()


def deck_args(deck, cmd, extra=()):
    return ([cmd, os.path.join(FIXTURES, f"{deck}.txt"),
             f"--cache={os.path.join(FIXTURES, f'{deck}.scry.json')}"]
            + list(DECK_EXTRA.get(deck, ())) + list(extra))
