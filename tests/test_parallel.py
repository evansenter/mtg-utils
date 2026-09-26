"""Worker processes must not move a number.

The CLI runs Monte Carlo replicates across processes; the library default is
the plain in-process loop. The golden suite goes through the CLI and so pins
the parallel path to the committed bytes, and most unit tests call the
library and so pin the serial one -- this is the direct comparison, on the
returned data, so a divergence says which field moved.
"""
import json
import os

import pytest

from conftest import FIXTURES


def _deck(mm, name):
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, f"{name}.txt"))
    with open(os.path.join(FIXTURES, f"{name}.scry.json"), encoding="utf-8") as f:
        return cmdr, entries, json.load(f)


@pytest.mark.parametrize("deck", ["multi", "partner"])
def test_analyse_mana_is_identical_in_worker_processes(mm, deck):
    cmdr, entries, scry = _deck(mm, deck)
    serial = mm.analyse_mana(cmdr, entries, scry, sims=300, trials=600, reps=3)
    parallel = mm.analyse_mana(cmdr, entries, scry, sims=300, trials=600,
                               reps=3, jobs=3)
    for key in ("rows", "lines", "sim"):
        assert serial[key] == parallel[key], key


def test_variants_sweep_is_identical_in_worker_processes(mm):
    """Six configurations of three replicates go out as ONE batch, so the
    results have to come back and be regrouped per configuration in order --
    a batch regrouped off by one replicate still prints plausible numbers."""
    cmdr, entries, scry = _deck(mm, "multi")
    args = (cmdr, entries, scry, [-2, 0, 2], [0, 2], 600)
    serial = mm.sweep_variants(*args, seed=17, reps=3)
    parallel = mm.sweep_variants(*args, seed=17, reps=3, jobs=4)
    assert serial == parallel


def test_pmap_keeps_submission_order(mm):
    from mtg_utils.parallel import pmap
    assert pmap(divmod, [(n, 3) for n in range(10)], jobs=4) == \
        [divmod(n, 3) for n in range(10)]
