"""The report package's API surface.

report.py was one 750-line module and is now a package split by the question
each printer answers. Splitting it is only safe if the surface is unchanged:
`from mtg_utils.report import report_mana` has to keep working, and so does
`mana_model.report_mana`, because mana_model.py exists precisely so scripts
written against the original single file keep running.

The interesting case is not "did the split work" -- the rest of the suite
answers that. It is "does the NEXT printer get wired up", because a printer
added to a submodule and left out of the package __init__ is invisible to
every caller that imports from `mtg_utils.report`, and nothing else would
notice: the submodule's own tests would pass perfectly well.
"""
import importlib
import pkgutil

import pytest

import mtg_utils.report as report


def _submodule_printers():
    """Every report_* defined in a submodule of the package."""
    found = {}
    for info in pkgutil.iter_modules(report.__path__):
        mod = importlib.import_module(f"mtg_utils.report.{info.name}")
        for name in dir(mod):
            if name.startswith("report_"):
                found.setdefault(name, info.name)
    return found


def test_every_submodule_printer_is_re_exported():
    """A printer added to a submodule and forgotten in __init__ is invisible
    to `from mtg_utils.report import ...` and to the CLI, and no other test
    would fail."""
    missing = sorted(set(_submodule_printers()) - set(report.__all__))
    assert not missing, f"defined in a submodule but not re-exported: {missing}"


def test_all_matches_what_the_package_actually_exposes():
    for name in report.__all__:
        assert hasattr(report, name), f"__all__ promises {name}, package lacks it"
        assert callable(getattr(report, name))
    exposed = {n for n in dir(report) if n.startswith("report_")}
    assert exposed == set(report.__all__), sorted(exposed ^ set(report.__all__))


def test_the_shim_still_exposes_every_printer(mm):
    """mana_model.py exists so scripts written against the original single
    file keep running. `from mtg_utils import *` copies names at import time,
    so a printer that never reaches mtg_utils/__init__ never reaches here."""
    for name in report.__all__:
        assert hasattr(mm, name), f"mana_model lost {name}"


@pytest.mark.parametrize("name", sorted(report.__all__))
def test_each_printer_is_importable_from_the_package_root(name):
    """The import path callers use must not depend on which file a printer
    was filed under -- that is the whole point of the package __init__."""
    mod = importlib.import_module("mtg_utils.report")
    assert callable(getattr(mod, name))


def test_printers_are_spread_across_the_split():
    """A split that left everything in one submodule would pass every other
    case here while achieving nothing."""
    by_mod = {}
    for name, mod in _submodule_printers().items():
        by_mod.setdefault(mod, []).append(name)
    assert len(by_mod) >= 4, by_mod
    assert all(v for v in by_mod.values())


def test_every_cli_subcommand_still_has_its_printer(mm):
    """The CLI is the real consumer. If a printer stopped resolving, argparse
    would still build and `--help` would still be byte-identical -- the
    failure would only appear when someone ran the subcommand."""
    import mtg_utils.cli as cli
    for name in report.__all__:
        assert hasattr(cli, name), f"cli.py cannot see {name}"
