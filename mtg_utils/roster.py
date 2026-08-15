"""The section 6 land roster, as DATA rather than as a prohibition."""
# The section 6 roster walk, as DATA. A prohibition ("never skip a slot
# because another deck sleeves the single") cannot catch a card that was
# never generated as a candidate -- an Aragorn list ran three tapped Triomes
# while all six ABUR duals sat unused, and no rule fired. So the roster
# enumerates: every slot of every cycle, for every colour pair in the
# identity, marked IN / benched / buy.
#
# Every name here is asserted against Scryfall at report time: a typo or a
# misremembered cycle member surfaces as NOT FOUND or as a colour-identity
# mismatch, never as a silently missing row.

from mtg_utils.cards import BASIC_TYPE_COLOUR, front_name

WUBRG = "WUBRG"


def pair_key(a, b):
    """Canonical WUBRG-ordered two-colour key. pair_key('U','W') == 'WU'."""
    return "".join(sorted({a, b}, key=WUBRG.index))


def identity_pairs(identity):
    cols = [c for c in WUBRG if c in set(identity)]
    return [pair_key(cols[i], cols[j])
            for i in range(len(cols)) for j in range(i + 1, len(cols))]


# Ten pairs, in canonical order.
_P = ["WU", "WB", "WR", "WG", "UB", "UR", "UG", "BR", "BG", "RG"]


PAIR_CYCLES = [
    ("ABUR dual", dict(zip(_P, [
        "Tundra", "Scrubland", "Plateau", "Savannah", "Underground Sea",
        "Volcanic Island", "Tropical Island", "Badlands", "Bayou", "Taiga"]))),
    ("Shockland", dict(zip(_P, [
        "Hallowed Fountain", "Godless Shrine", "Sacred Foundry", "Temple Garden",
        "Watery Grave", "Steam Vents", "Breeding Pool", "Blood Crypt",
        "Overgrown Tomb", "Stomping Ground"]))),
    ("Fetchland", dict(zip(_P, [
        "Flooded Strand", "Marsh Flats", "Arid Mesa", "Windswept Heath",
        "Polluted Delta", "Scalding Tarn", "Misty Rainforest", "Bloodstained Mire",
        "Verdant Catacombs", "Wooded Foothills"]))),
    ("Horizon land", {  # ONLY SIX EXIST -- the other four rows are "no such card"
        "WB": "Silent Clearing", "WR": "Sunbaked Canyon", "WG": "Horizon Canopy",
        "UR": "Fiery Islet", "UG": "Waterlogged Grove", "BG": "Nurturing Peatland"}),
    ("Painland", dict(zip(_P, [
        "Adarkar Wastes", "Caves of Koilos", "Battlefield Forge", "Brushland",
        "Underground River", "Shivan Reef", "Yavimaya Coast", "Sulfurous Springs",
        "Llanowar Wastes", "Karplusan Forest"]))),
    ("Filter land", dict(zip(_P, [
        "Mystic Gate", "Fetid Heath", "Rugged Prairie", "Wooded Bastion",
        "Sunken Ruins", "Cascade Bluffs", "Flooded Grove", "Graven Cairns",
        "Twilight Mire", "Fire-Lit Thicket"]))),
    ("Battlebond land", dict(zip(_P, [
        "Sea of Clouds", "Vault of Champions", "Spectator Seating",
        "Bountiful Promenade", "Morphic Pool", "Training Center",
        "Rejuvenating Springs", "Luxury Suite", "Undergrowth Stadium",
        "Spire Garden"]))),
    ("Checkland", dict(zip(_P, [
        "Glacial Fortress", "Isolated Chapel", "Clifftop Retreat", "Sunpetal Grove",
        "Drowned Catacomb", "Sulfur Falls", "Hinterland Harbor", "Dragonskull Summit",
        "Woodland Cemetery", "Rootbound Crag"]))),
    ("Pathway", dict(zip(_P, [
        "Hengegate Pathway", "Brightclimb Pathway", "Needleverge Pathway",
        "Branchloft Pathway", "Clearwater Pathway", "Riverglide Pathway",
        "Barkchannel Pathway", "Blightstep Pathway", "Darkbore Pathway",
        "Cragcrown Pathway"]))),
    ("Surveil land", dict(zip(_P, [
        "Meticulous Archive", "Shadowy Backstreet", "Elegant Parlor", "Lush Portico",
        "Undercity Sewers", "Thundering Falls", "Hedge Maze", "Raucous Theater",
        "Underground Mortuary", "Commercial District"]))),
    ("Fastland", dict(zip(_P, [
        "Seachrome Coast", "Concealed Courtyard", "Inspiring Vantage",
        "Razorverge Thicket", "Darkslick Shores", "Spirebluff Canal",
        "Botanical Sanctum", "Blackcleave Cliffs", "Blooming Marsh",
        "Copperline Gorge"]))),
]


# Three-colour rows, keyed by the WUBRG-ordered identity string.
TRIPLE_CYCLES = {
    "WUB": ("Raffine's Tower", "Arcane Sanctum"),
    "WUR": ("Raugrin Triome", "Mystic Monastery"),
    "WUG": ("Spara's Headquarters", "Seaside Citadel"),
    "WBR": ("Savai Triome", "Nomad Outpost"),
    "WBG": ("Indatha Triome", "Sandsteppe Citadel"),
    "WRG": ("Jetmir's Garden", "Jungle Shrine"),
    "UBR": ("Xander's Lounge", "Crumbling Necropolis"),
    "UBG": ("Zagoth Triome", "Opulent Palace"),
    "URG": ("Ketria Triome", "Frontier Bivouac"),
    "BRG": ("Ziatora's Proving Ground", "Savage Lands"),
}


# Identity-independent rows. Each costs a coloured source; the model prices
# that, so walk them and say why, rather than skipping the row.
ANY_COLOUR = [
    ("Any-colour", "Command Tower"),
    ("Any-colour", "City of Brass"),
    ("Any-colour", "Mana Confluence"),
    ("Any-colour", "Exotic Orchard"),
    ("Any-colour", "Reflecting Pool"),
    ("Fetch (basic)", "Prismatic Vista"),
    ("Typal", "Cavern of Souls"),
    ("Typal", "Secluded Courtyard"),
    ("Typal", "Three Tree City"),
    ("Typal", "Unclaimed Territory"),
    ("Typal (tapped)", "Path of Ancestry"),
    ("Legendary", "Plaza of Heroes"),
    ("Legendary", "Great Hall of the Citadel"),
]


def roster_names(identity):
    """Every card the roster walk will look at, for a colour identity."""
    ident = set(identity)
    out = []
    for _slot, table in PAIR_CYCLES:
        for pk in identity_pairs(identity):
            if table.get(pk):
                out.append(table[pk])
    # fetchlands that reach ONE colour of the identity are still live slots
    for pk, name in PAIR_CYCLES[2][1].items():
        if set(pk) & ident and not set(pk) <= ident:
            out.append(name)
    key = "".join(c for c in WUBRG if c in ident)
    if key in TRIPLE_CYCLES:
        out += list(TRIPLE_CYCLES[key])
    out += [n for _s, n in ANY_COLOUR]
    return list(dict.fromkeys(out))


def roster_status(name, deck_names, owned):
    """IN beats owned; owned-but-benched is NOT a reason to skip a slot."""
    low = name.lower()
    if low in deck_names:
        return "IN"
    q = owned.get(low, 0) or owned.get(front_name(low), 0)
    return f"BENCH x{q}" if q else "BUY"


# PAIR_CYCLES is ordered BEST FIRST, and that ordering is now load-bearing
# rather than cosmetic: `roster_slot` returns the index as a rank, and the
# ceiling cross-reference calls a land a downgrade when a lower-indexed cycle
# for the same pair is already in the list. Reordering this list therefore
# changes reported verdicts -- it is data, not presentation.
#
# A land in NO cycle is ranked below all of them. That is the battle-land
# case: Cinder Glade is on no roster cycle and is a documented downgrade to
# every dual that is, so "absent from the roster" has to sort worse than
# "present on the worst cycle", not better.
OFF_ROSTER_RANK = len(PAIR_CYCLES)


def roster_slot(name):
    """Where a card sits on the roster walk: dict(cycle, key, rank) or None.

    `rank` is the index into PAIR_CYCLES, so smaller is better. A triple-land
    row carries rank 0 or 1 within its own three-colour key -- the two are
    listed best-first as well -- and an any-colour row carries rank None,
    because that list has no quality ordering and inventing one here would
    manufacture a downgrade verdict out of nothing.
    """
    low = name.lower()
    for rank, (slot, table) in enumerate(PAIR_CYCLES):
        for pk, member in table.items():
            if member.lower() == low:
                return {"cycle": slot, "key": pk, "rank": rank}
    for key, members in TRIPLE_CYCLES.items():
        for rank, member in enumerate(members):
            if member.lower() == low:
                return {"cycle": "Triome" if rank == 0 else "Tri-land",
                        "key": key, "rank": rank}
    for slot, member in ANY_COLOUR:
        if member.lower() == low:
            return {"cycle": slot, "key": None, "rank": None}
    return None


def pair_from_type_line(type_line):
    """The colour pair a dual land covers, read off its BASIC LAND TYPES.

    'Land — Mountain Forest' -> 'RG'. This is what catches the cycles the
    roster does not enumerate: a battle land carries basic types and no
    roster slot, so without this it would be indistinguishable from Gaea's
    Cradle -- a land with no pair at all, which the roster rightly has no
    opinion about.

    Returns None unless exactly two colours are named. A Triome names three
    (it is on the roster by name anyway) and a fetchland names none.
    """
    low = (type_line or "").lower()
    cols = {col for t, col in BASIC_TYPE_COLOUR.items() if t in low}
    return pair_key(*cols) if len(cols) == 2 else None
