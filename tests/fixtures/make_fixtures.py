#!/usr/bin/env python3
"""Generate the golden fixtures. RUN ONCE -- the fixtures are frozen.

Card NAMES here are chosen by hand to exercise specific code paths; every
card OBJECT comes verbatim from Scryfall, and a name that does not resolve
shows up in `not_found` rather than silently dropping out of the deck. Each
deck is accepted only if `verify` reports 100 cards, nothing illegal and no
colour-identity violations.
"""
import json, os, subprocess, sys, time, urllib.parse
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
import mana_model as m

OUT = sys.argv[1] if len(sys.argv) > 1 else HERE

# --- land packages, picked to hit specific paths -------------------------
MONO_LANDS = {
    "Mountain": 18,
    # amount=2 producers, and Ancient Tomb is a Game Changer land (verify)
    "Ancient Tomb": 1,
    # any-colour / typal / legendary roster rows
    "City of Brass": 1, "Mana Confluence": 1, "Exotic Orchard": 1,
    "Reflecting Pool": 1, "Command Tower": 1, "Cavern of Souls": 1,
    "Unclaimed Territory": 1, "Path of Ancestry": 1, "Plaza of Heroes": 1,
    # fetchlands: produced_mana is empty, colours come from fetch_targets
    "Bloodstained Mire": 1, "Wooded Foothills": 1, "Prismatic Vista": 1,
    # conditional tap ("unless you control a Mountain") vs truly tapped
    "Castle Embereth": 1,
    "Rogue's Passage": 1, "Buried Ruin": 1, "Blast Zone": 1,
}
MONO_SPELLS = [
    "Shatterskull Smashing",      # MDFC land back, pays 3 life
    "Fíli and Kíli, Joyous",      # restricted mana (Dwarf/Equipment/Saga only)
                                  # -- accented name, matched exactly (sec 5)
    "Sol Ring", "Arcane Signet", "Mind Stone", "Everflowing Chalice",
    "Jeska's Will",               # ritual: "add" text, not a permanent source
]

MULTI_LANDS = {
    "Forest": 3, "Island": 3, "Swamp": 3,
    # filter lands: the whole point of the multicolour fixture
    "Sunken Ruins": 1, "Twilight Mire": 1, "Flooded Grove": 1,
    # omni-typing applies to every land in play
    "Urborg, Tomb of Yawgmoth": 1, "Yavimaya, Cradle of Growth": 1,
    # karoo: "Add {B}{G}" is one alternative worth 2
    "Golgari Rot Farm": 1,
    "Ancient Tomb": 1,
    # duals / shocks / fetches / triome / battlebond / horizon / pain
    "Bayou": 1, "Underground Sea": 1, "Tropical Island": 1,
    "Overgrown Tomb": 1, "Watery Grave": 1, "Breeding Pool": 1,
    "Verdant Catacombs": 1, "Polluted Delta": 1, "Misty Rainforest": 1,
    "Zagoth Triome": 1, "Opulent Palace": 1,
    "Morphic Pool": 1, "Undergrowth Stadium": 1,
    "Waterlogged Grove": 1, "Nurturing Peatland": 1,
    "Llanowar Wastes": 1, "Underground River": 1, "Yavimaya Coast": 1,
    "Command Tower": 1, "Exotic Orchard": 1, "Reflecting Pool": 1,
}
MULTI_SPELLS = [
    "Agadeem's Awakening",        # MDFC land backs, all pay 3 life
    "Sea Gate Restoration",
    "Turntimber Symbiosis",
    "Commit // Memory",           # split: top-level cmc is the SUM of halves
    "Beseech the Queen",          # two-brid {2/B}, payable with generic
    "Delighted Halfling",         # restricted: legendary spells only
    "Sol Ring", "Arcane Signet", "Birds of Paradise", "Llanowar Elves",
]

COLOURLESS_LANDS = {
    "Wastes": 12,
    "Eldrazi Temple": 1,          # {C}{C} restricted to Eldrazi -- lands have
    "Ancient Tomb": 1,            # no `restricted` flag, so both count as 2
    "Sanctum of Ugin": 1, "Buried Ruin": 1, "Blast Zone": 1,
    "Rogue's Passage": 1, "Inventors' Fair": 1,
    "Cavern of Souls": 1, "Unclaimed Territory": 1, "Plaza of Heroes": 1,
    "Command Tower": 1, "Exotic Orchard": 1, "Reflecting Pool": 1,
    # a fetch with no basic-type targets in the deck: zero colours, still a source
    "Prismatic Vista": 1, "Wooded Foothills": 1,
}
COLOURLESS_SPELLS = [
    # real {C} pips -- the requirement four Forests cannot pay
    "Thought-Knot Seer", "Reality Smasher", "Matter Reshaper", "Endbringer",
    "Warping Wail", "Spatial Contortion", "Walking Ballista",
    "Sol Ring", "Everflowing Chalice", "Mind Stone", "Hedron Archive",
]

SPECS = [
    {"key": "mono", "cmdr": "Magda, Brazen Outlaw", "q": "ci<=r",
     "lands": MONO_LANDS, "spells": MONO_SPELLS},
    {"key": "multi", "cmdr": "Muldrotha, the Gravetide", "q": "ci<=bug",
     "lands": MULTI_LANDS, "spells": MULTI_SPELLS},
    {"key": "colourless", "cmdr": "Zhulodok, Void Gorger", "q": "ci<=c",
     "lands": COLOURLESS_LANDS, "spells": COLOURLESS_SPELLS},
]


COLLECTION_COLS = ["Binder Name", "Name", "Set code", "Collector number", "Foil",
                   "Rarity", "Quantity", "ManaBox ID", "Scryfall ID",
                   "Purchase price", "Condition", "Language", "Added"]

# Deliberate shape, mirroring the real ManaBox export:
#   - one card across two printings AND two finishes: must SUM to 4, not double-count
#   - a DFC with " // ": both the full name and the front face become keys
#   - an accented name: matched exactly, never normalised
#   - roster cards owned but NOT in any fixture deck, so `BENCH xN` is exercised
#   - NO basic lands: ManaBox does not track them (project knowledge sec 5)
COLLECTION_ROWS = [
    ("Rares",   "Sol Ring",                                       "LTC", "284", "normal", "uncommon", 2),
    ("Rares",   "Sol Ring",                                       "C21", "263", "normal", "uncommon", 1),
    ("Foils",   "Sol Ring",                                       "LTC", "284", "foil",   "uncommon", 1),
    ("Duals",   "Underground Sea",                                "LEB", "286", "normal", "rare",     2),
    ("Duals",   "Bayou",                                          "3ED", "282", "normal", "rare",     1),
    ("Duals",   "Tundra",                                         "3ED", "287", "normal", "rare",     1),
    ("Filters", "Twilight Mire",                                  "EVE", "150", "normal", "rare",     1),
    ("Filters", "Sunken Ruins",                                   "SHM", "276", "normal", "rare",     1),
    ("Fetches", "Verdant Catacombs",                              "MH3", "224", "normal", "rare",     1),
    ("Lands",   "Ancient Tomb",                                   "UMA", "236", "normal", "rare",     1),
    ("Lands",   "Command Tower",                                  "ELD", "333", "normal", "common",   3),
    ("Modal",   "Agadeem's Awakening // Agadeem, the Undercrypt",  "ZNR", "090", "normal", "mythic",   1),
    ("Dwarves", "Fíli and Kíli, Joyous",                          "LTR", "213", "normal", "rare",     1),
    ("Rares",   "Thought-Knot Seer",                              "OGW", "006", "normal", "rare",     2),
    # owned, benched: in the roster walk for these identities, in none of the decks
    ("Lands",   "Hinterland Harbor",                              "DOM", "246", "normal", "rare",     1),
    ("Lands",   "Drowned Catacomb",                               "XLN", "253", "normal", "rare",     2),
    ("Lands",   "Blooming Marsh",                                 "KLR", "282", "normal", "rare",     1),
    ("Lands",   "Great Hall of the Citadel",                      "LTR", "256", "normal", "rare",     1),
    ("Lands",   "Three Tree City",                                "BLB", "263", "normal", "mythic",   2),
]


def write_collection(path):
    import csv
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLLECTION_COLS)
        for i, (binder, name, setc, num, foil, rarity, qty) in enumerate(COLLECTION_ROWS):
            w.writerow([binder, name, setc, num, foil, rarity, qty, str(10000 + i),
                        f"0000000{i % 10}-0000-0000-0000-{i:012d}", "1.50",
                        "near_mint", "en", "2026-01-%02d 12:00:00" % (i % 28 + 1)])


def search(query, tries=4):
    """/cards/search is rate limited harder than /cards/collection: ~0.5s plus
    backoff, and an unguarded loop 429s silently (project knowledge sec 7)."""
    url = ("https://api.scryfall.com/cards/search?q="
           + urllib.parse.quote(query) + "&order=edhrec&unique=cards")
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


def build(spec):
    entries = Counter()
    for n, q in spec["lands"].items():
        entries[n] += q
    for n in spec["spells"]:
        entries[n] += 1
    need = 99 - sum(entries.values())
    assert need > 0, (spec["key"], need)

    d = search(f"{spec['q']} legal:commander -t:land")
    # assert the result count rather than trusting the loop (sec 7)
    assert d.get("total_cards", 0) >= need, (spec["key"], d.get("total_cards"))
    time.sleep(0.6)

    taken = 0
    for c in d["data"]:
        if taken >= need:
            break
        name = c["name"]
        if name == spec["cmdr"] or name in entries:
            continue
        if "Land" in c["type_line"].split("//")[0]:
            continue
        entries[name] += 1
        taken += 1
    assert taken == need, f"{spec['key']}: filled {taken} of {need}"

    os.makedirs(OUT, exist_ok=True)
    deck_path = os.path.join(OUT, f"{spec['key']}.txt")
    cache_path = os.path.join(OUT, f"{spec['key']}.scry.json")
    m.write_deck(spec["cmdr"], entries, deck_path)

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
    print(f"  identity={ident or 'C'}  total={v['total']}  lands={v['lands']}"
          f"  mdfc={v['mdfc_land_backs']}  nonland={v['nonland']}"
          f"  avg_mv={v['avg_mv']:.2f}  GC={len(v['game_changers'])}"
          f"  truly_tapped={len(v['truly_tapped'])}"
          f"  conditional={len(v['conditional_tapped'])}")
    print(f"  illegal={v['illegal']}")
    print(f"  ci_violations={v['ci_violations']}")
    return nf + nf2, v, ident


if __name__ == "__main__":
    bad = False
    os.makedirs(OUT, exist_ok=True)
    write_collection(os.path.join(OUT, "collection.csv"))
    for spec in SPECS:
        print(f"\n=== {spec['key']} : {spec['cmdr']} ===")
        nf, v, ident = build(spec)
        if nf or v["illegal"] or v["ci_violations"] or v["total"] != 100:
            bad = True
    sys.exit(1 if bad else 0)
