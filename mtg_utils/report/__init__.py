"""Printers. These format what analysis.py computed; they do not compute.

Split from a single module by the QUESTION each printer answers:

    mana.py   the two models, the count sweep, the named swap
    deck.py   what is in the 100 -- skeleton, roster, combos, primer, floor
    own.py    ownership -- own, contention, ceiling
    live.py   the live Moxfield account -- diff, calibrate

Every public name is re-exported here, so `from mtg_utils.report import
report_mana` keeps working and no caller needs to know which file a printer
sits in. A printer missing from `__all__` is invisible to the CLI; a test
enforces that every submodule printer appears here.

What that re-export does NOT do is make a patch land. A module-level function
resolves in the globals of the module that DEFINES it, so
`monkeypatch.setattr(mtg_utils.report, "spellbook", fake)` binds a name on
this package that `report_combos` never reads -- the patch "succeeds" and the
real, networked function runs. Patch by name across sys.modules instead;
`patch_everywhere` in tests/conftest.py does exactly that, and asserts it
matched something.
"""
from mtg_utils.report.mana import report_mana, report_swap, report_variants
from mtg_utils.report.deck import (report_combos, report_floor, report_primer,
                                   report_roster, report_skeleton)
from mtg_utils.report.own import report_ceiling, report_contention, report_own
from mtg_utils.report.live import report_calibrate, report_diff

__all__ = ["report_calibrate", "report_ceiling", "report_combos",
           "report_contention", "report_diff", "report_floor", "report_mana",
           "report_own", "report_primer", "report_roster", "report_skeleton",
           "report_swap", "report_variants"]
