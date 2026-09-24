#!/usr/bin/env python3
"""Generate the Standard Brawl fixture. RUN ONCE -- the fixture is frozen.

The fifth deck shape, and the first that is not Commander. It exists because
the four Commander fixtures cannot break any claim this repo makes about
format, deck size, or the two land classes below -- a green suite over
fixtures that cannot break a claim is evidence about the fixtures.

What it deliberately covers, none of which any other fixture holds:

  60 cards          1 commander + 59, so a hard-coded 100 fails on it
  a DFC commander   `Terra, Magical Adept // Esper Terra`; the decklist spells
                    the front face, which is what Moxfield and Commander
                    Spellbook disagree with in opposite directions
  a five-colour identity on a three-colour build -- Terra is WUBRG and the
                    list is BRG, which is what `roster` walks wrongly
  a gated coloured half   the Verge cycle: "{T}: Add {R}. Activate only if you
                    control a Mountain or a Forest", plus Training Compound's
                    board condition, both profiled as free colour
  a TAXED coloured half   Hidden Grotto / Conduit Pylons / Crystal Grotto:
                    "{1}, {T}: Add one mana of any color", scored as a free
                    five-colour source with the {1} nowhere
  a turn-conditional tap  Starting Town, "enters tapped unless it's your
                    first, second, or third turn of the game" -- untapped
                    early and tapped late, the mirror of every conditional
                    marker already modelled
  a commander combo piece  The Apprentice's Folly, which combos WITH Terra

Card NAMES are chosen by hand for those paths; every card OBJECT comes
verbatim from Scryfall. The deck is accepted only if `verify` reports 60
cards, nothing illegal in Standard Brawl and no colour-identity violations.
"""
import json, os, subprocess, sys, time, urllib.parse
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
import mana_model as m

OUT = sys.argv[1] if len(sys.argv) > 1 else HERE

CMDR = "Terra, Magical Adept"

BRAWL_LANDS = {
    # the two shapes FR-1 is about
    "Blazemire Verge": 1,        # {T}: Add {R}. Activate only if ...
    "Wastewood Verge": 1,
    "Thornspire Verge": 1,
    "Training Compound": 1,      # a different board condition, same shape
    "Hidden Grotto": 1,          # {1}, {T}: Add one mana of any color
    "Conduit Pylons": 1,
    "Crystal Grotto": 1,
    # untapped early, tapped late -- a class the classifier has no bucket for
    "Starting Town": 1,
    "Swamp": 6, "Mountain": 6, "Forest": 5,
}
BRAWL_SPELLS = [
    "The Apprentice's Folly",    # combos with the commander
]

# Standard Brawl legal, in Terra's identity, ordered by EDHREC rank so the
# filler is at least cards people play. -t:land because the manabase above is
# the part chosen by hand.
QUERY = "legal:standardbrawl ci<=wubrg -t:land"
SIZE = 60


def search(query, page=1, tries=4):
    """/cards/search is rate limited harder than /cards/collection: ~0.5s plus
    backoff, and an unguarded loop 429s silently."""
    url = ("https://api.scryfall.com/cards/search?q=" + urllib.parse.quote(query)
           + f"&order=edhrec&unique=cards&page={page}")
    for attempt in range(tries):
        r = subprocess.run(["curl", "-s", "-H", "Accept: application/json",
                            "-H", f"User-Agent: {m.UA_TOOL}", url],
                           capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
        except Exception:
            time.sleep(1 + attempt * 2); continue
        if d.get("object") == "list":
            return d
        time.sleep(1 + attempt * 2)
    raise SystemExit(f"Scryfall search failed after {tries} tries: {query}")


def build():
    entries = Counter()
    for n, q in BRAWL_LANDS.items():
        entries[n] += q
    for n in BRAWL_SPELLS:
        entries[n] += 1
    need = (SIZE - 1) - sum(entries.values())
    assert need > 0, need

    d = search(QUERY)
    # assert the result count rather than trusting the loop
    assert d.get("total_cards", 0) >= need, d.get("total_cards")
    time.sleep(0.6)

    taken = 0
    for c in d["data"]:
        if taken >= need:
            break
        name = c["name"]
        if name == CMDR or m.front_name(name) == CMDR or name in entries:
            continue
        if "Land" in c["type_line"].split("//")[0]:
            continue
        entries[name] += 1
        taken += 1
    assert taken == need, f"filled {taken} of {need}"

    deck_path = os.path.join(OUT, "brawl.txt")
    cache_path = os.path.join(OUT, "brawl.scry.json")
    m.write_deck(CMDR, entries, deck_path, size=SIZE)

    cmdr, ents = m.read_decklist(deck_path)
    scry, nf = m.scry_fetch(m.flat(cmdr, ents), cache_path)
    if nf:
        print(f"  !! NOT FOUND: {nf}")

    # the roster walk fetches its own names; fold them into the same frozen
    # cache so `roster` runs with no network at all
    ci = set()
    for cn in m.as_cmdrs(cmdr):
        if scry.get(cn.lower()):
            ci |= set(scry[cn.lower()]["color_identity"])
    ident = "".join(c for c in m.WUBRG if c in ci)
    scry, nf2 = m.scry_fetch(m.roster_names(ident), cache_path)
    if nf2:
        print(f"  !! ROSTER NOT FOUND: {nf2}")

    v = m.verify(cmdr, ents, scry)
    illegal = [(n, why) for n, why in v["illegal"]]
    print(f"  identity={ident}  total={v['total']}  lands={v['lands']}"
          f"  nonland={v['nonland']}  avg_mv={v['avg_mv']:.2f}")
    print(f"  commander-illegal (expected, this is a Brawl list): {illegal}")
    print(f"  ci_violations={v['ci_violations']}")
    bad = [n for n in m.flat(cmdr, ents)
           if scry.get(n.lower())
           and scry[n.lower()]["legalities"].get("standardbrawl") != "legal"]
    print(f"  NOT STANDARD BRAWL LEGAL: {sorted(set(bad))}")
    return nf + nf2, v, bad


if __name__ == "__main__":
    nf, v, bad = build()
    sys.exit(1 if (nf or bad or v["ci_violations"] or v["total"] != SIZE) else 0)
