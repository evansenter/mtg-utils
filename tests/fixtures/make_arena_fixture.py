#!/usr/bin/env python3
"""Capture the Arena printings for brawl.txt. RUN ONCE -- the fixture is frozen.

One Scryfall search per distinct card, projected to the five fields the
selection rules read. A projection for the same reason `ceiling.scry.json` is
one: the full records for these 45 names run to megabytes to answer a question
that needs a set code, a collector number, a rarity, a date and two flags.
Every value in it is verbatim.

It is captured with NO format filter applied, so the frozen file holds every
Arena printing of every card -- the selection is what the offline suite tests,
and a file already narrowed to one format could not test it.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
import mana_model as m

OUT = sys.argv[1] if len(sys.argv) > 1 else HERE

if __name__ == "__main__":
    cmdr, entries = m.read_decklist(os.path.join(OUT, "brawl.txt"))
    cache = os.path.join(OUT, "brawl.arena.json")
    names = list(dict.fromkeys(m.front_name(n) for n in m.flat(cmdr, entries)))
    print(f"{len(names)} distinct names")
    for n in names:
        got = m.arena_fetch(n, cache)
        print(f"  {n:36s} {len(got)} printing(s)")
    prints, missing = m.arena_printings(m.flat(cmdr, entries),
                                        "standardbrawl", cache)
    print(f"\nresolved {len(prints)}; no importable printing: {missing}")
    sys.exit(1 if missing else 0)
