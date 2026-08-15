"""Shared test plumbing.

The golden suite runs two copies of the code -- reference/mana_model_v0.py and
whatever the repo currently ships -- over the same frozen fixtures, in the same
process, and compares stdout byte for byte.

Same process matters: set iteration order depends on PYTHONHASHSEED, and running
both copies under one interpreter means any hash-order effect is shared rather
than showing up as a spurious diff. CI pins the seed as well.
"""
import csv
import importlib.util
import io
import os
import shutil
import sys
from collections import defaultdict
from contextlib import redirect_stdout, redirect_stderr

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(REPO, "tests", "fixtures")
EXPECTED = os.path.join(FIXTURES, "expected")
REFERENCE = os.path.join(REPO, "reference", "mana_model_v0.py")

if REPO not in sys.path:
    sys.path.insert(0, REPO)

DECKS = ("mono", "multi", "colourless")


def pytest_addoption(parser):
    parser.addoption(
        "--regen-golden", action="store_true", default=False,
        help="rewrite tests/fixtures/expected/ from reference/mana_model_v0.py")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def candidate():
    """The copy under test: the root mana_model.py entry point, before and
    after it becomes a shim over the package. Imported the same way throughout
    so the harness itself never changes shape mid-refactor."""
    return _load(os.path.join(REPO, "mana_model.py"), "_candidate_mana_model")


@pytest.fixture(scope="session")
def reference():
    """v0, frozen. Skipped once reference/ is deleted in the final commit --
    by then the committed snapshots carry the invariant."""
    if not os.path.exists(REFERENCE):
        pytest.skip("reference/ has been deleted; snapshots carry the invariant")
    return _load(REFERENCE, "_reference_mana_model")


@pytest.fixture(scope="session")
def mm():
    """The single copy to use for ordinary (non-golden) unit tests."""
    return _load(os.path.join(REPO, "mana_model.py"), "_unit_mana_model")


def card(**kw):
    """Ported verbatim from selftest's `_card`."""
    kw.setdefault("type_line", "Land")
    kw.setdefault("oracle_text", "")
    return kw


def src(colours="", amount=1, filt=None, omni=None):
    """Ported verbatim from selftest's `_src`."""
    return {"colours": frozenset(colours), "amount": amount,
            "filter": filt, "omni": omni}


def load_fixture_collection(path=os.path.join(FIXTURES, "collection.csv")):
    """A stand-in for load_collection bound to the fixture CSV.

    load_collection's signature is `def load_collection(path=COLLECTION)`, so
    the default is bound at import time and patching the module's COLLECTION
    constant does nothing. The function itself has to be replaced -- and it is
    replaced identically in both copies, so output equality still measures the
    thing it claims to.

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
    old_loader = mod.load_collection
    # prog is derived from sys.argv[0] and appears in --help output
    sys.argv = ["mana_model.py"] + argv
    mod.load_collection = load_fixture_collection
    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            try:
                mod.main()
            except SystemExit as e:
                if e.code not in (0, None):
                    buf.write(f"\n[exit {e.code}]\n")
    finally:
        sys.argv = old_argv
        mod.load_collection = old_loader
    return buf.getvalue()


def deck_args(deck, cmd, extra=()):
    return [cmd, os.path.join(FIXTURES, f"{deck}.txt"),
            f"--cache={os.path.join(FIXTURES, f'{deck}.scry.json')}"] + list(extra)
