"""The count sweep simulates the deck's OWN library, not a 99-card one.

`report_variants` passed a literal 99 to `replicate_playsim` while
`analyse_mana` derived the library as `len(names)`. Every deck whose library
is not 99 cards was therefore swept against a diluted one: a 60-card Standard
Brawl list was simulated as though 39 blank cards had been shuffled in and its
figures came out roughly halved, and a partner pair -- library 98 -- was
diluted by one.

Nothing in the sweep's own output looks wrong when this is broken, which is
why the assertion is on the ARGUMENT rather than on a printed figure: the bug
surfaced only because `mana` and this table disagreed about the same line on
the same deck. A figure-level assertion would have to pin a Monte Carlo mean,
and the movement here (1.2 points on the partner deck) is the same size as
the noise a different seed produces.
"""
import json
import os

import pytest

from conftest import FIXTURES, patch_everywhere

# (deck, library) -- the library is the deck minus its commanders, which is
# the number `analyse_mana` has always used.
DECKS = [("partner", 98), ("mono", 99), ("multi", 99), ("colourless", 99)]


def _deck(mm, name):
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, f"{name}.txt"))
    with open(os.path.join(FIXTURES, f"{name}.scry.json"), encoding="utf-8") as f:
        scry = json.load(f)
    return cmdr, entries, scry


@pytest.mark.parametrize("deck,library", DECKS,
                         ids=[f"variants/{d} sweeps a {n}-card library"
                              for d, n in DECKS])
def test_the_sweep_simulates_the_decks_own_library(mm, monkeypatch, capsys,
                                                   deck, library):
    cmdr, entries, scry = _deck(mm, deck)
    seen = []

    def fake_replicate_playsim(lands, accels, deck_size, lines, trials, seed,
                               reps, turns=None, rituals=None):
        seen.append(deck_size)
        return {side: {"generic": {turns: (0.0, 0.0)},
                       "lines": {"cmdr": (0.0, turns, 0.0)}}
                for side in ("play", "draw")}

    patch_everywhere(monkeypatch, "replicate_playsim", fake_replicate_playsim)
    mm.report_variants(cmdr, entries, scry, [0], [0], trials=1, reps=1)
    capsys.readouterr()
    assert seen == [library]
