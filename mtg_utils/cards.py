"""Card plumbing: faces, DFC handling, tapped classification, mana production."""
import re

COLOURS = "WUBRG"


# Colourless is a real mana type a source can produce AND a real pip a cost can
# demand ({C} on Thought-Knot Seer). Filtering produced_mana to WUBRG alone made
# Ancient Tomb and Sol Ring look like they produced nothing a cost could want.
MANA_SYMBOLS = COLOURS + "C"


BASIC_TYPE_COLOUR = {"plains": "W", "island": "U", "swamp": "B",
                     "mountain": "R", "forest": "G"}


# "enters tapped" markers that are NOT a real cost in a four-player game, or
# that depend on a board state you usually control. Reported separately from
# the truly-tapped count.
CONDITIONAL_TAP_MARKERS = (
    "unless you have two or more opponents",   # battlebond
    "unless you control two or fewer other",   # fastland
    "unless you control a",                    # checkland / Mines of Moria
    "unless you control an",                   # The Lonely Mountain
    "unless you control two or more other",
)


# The life figure VARIES and must never be hard-coded. "you may pay 2 life" was
# the shockland's number standing in for the whole class, so The Black Gate
# ("you may pay 3 life") fell through to TRULY TAPPED -- a wrong verdict that
# looked right, and it shipped in a calibration table. The whole Zendikar MDFC
# land-back cycle pays 3 and was misclassified the same way.
CONDITIONAL_TAP_PATTERNS = (
    r"you may pay \d+ life",
    r"unless you pay \d+ life",
)


WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


# ============================================================ card plumbing
def faces(card):
    return card.get("card_faces") or [card]


def land_face(card):
    for f in faces(card):
        if "Land" in f.get("type_line", card.get("type_line", "")):
            return f
    if "Land" in card.get("type_line", "").split("//")[0]:
        return card
    return None


def front_name(name):
    """A card NAME reduced to its front face: 'A // B' -> 'A'.

    `front()` takes a Scryfall card object. This takes the string, which is
    what a decklist, a ManaBox export and every external ranking source hand
    you, and it is the join key between them — they do not agree on the
    convention:

        decklist   "Agadeem's Awakening // Agadeem, the Undercrypt"
        EDHREC     "Agadeem's Awakening"                    front face only
        edhtop16   "Sink into Stupor // Soporific Springs"   full name

    so a comparison written against one source is wrong against another.
    Reducing both sides is the only thing that works, and doing it by hand at
    each call site is how a card sitting in the deck got reported as missing.
    That bug is the reason this lives in cards.py rather than in whichever
    module noticed it last.

    Does not lower-case: some callers key a cache, some build an API
    identifier that wants the real capitalisation. Say `.lower()` where you
    mean it.
    """
    return (name or "").split(" // ")[0].strip()


def front(card, key, default=None):
    if card.get(key) is not None:
        return card[key]
    fs = card.get("card_faces") or []
    return fs[0].get(key, default) if fs else default


def is_front_land(card):
    return "Land" in card["type_line"].split("//")[0]


def has_land_back(card):
    return (not is_front_land(card)) and land_face(card) is not None


def enters_tapped(face, card=None):
    # `card` is unused and kept optional: every call site passes one, and
    # mtg_utils re-exports this, so dropping the parameter would break any
    # script that still calls enters_tapped(face, card).
    txt = (face.get("oracle_text") or "").lower()
    if "enters tapped" not in txt and "enters the battlefield tapped" not in txt:
        return False, None
    # Collect EVERY matching marker, literal and pattern, then return the
    # longest as the evidence string. Longest-wins is load-bearing twice over:
    # "unless you control a" is a PREFIX of "unless you control an", so tuple
    # order alone made The Lonely Mountain report the wrong matched text, and
    # the life-payment patterns must report the text they actually matched
    # ("you may pay 3 life") rather than a canned constant.
    hits = [m for m in CONDITIONAL_TAP_MARKERS if m in txt]
    for pat in CONDITIONAL_TAP_PATTERNS:
        hits += re.findall(pat, txt)
    if hits:
        return False, max(hits, key=len)
    return True, None


def fetch_targets(txt):
    out = set()
    if "search your library for a" not in txt:
        return out
    for t, c in BASIC_TYPE_COLOUR.items():
        if t in txt:
            out.add(c)
    if not out and "basic land card" in txt:      # Prismatic Vista
        out = set(BASIC_TYPE_COLOUR.values())
    return out


# The land a fetch clause finds can arrive TAPPED, and the wording is the only
# thing that says so. Two phrasings are printed:
#
#   Verdant Catacombs  "...put it onto the battlefield, then shuffle."
#   Evolving Wilds     "...put it onto the battlefield tapped, then shuffle."
#   Terminal Moraine   "...put that card onto the battlefield tapped, ..."
#
# so the pronoun varies and the word after "battlefield" does not.
FETCH_TAPPED = "onto the battlefield tapped"


def fetches_tapped(txt):
    """True when the land this text fetches arrives tapped.

    A gate on the wording, nothing more: it says what the FETCH does, not what
    the fetcher is worth. Terminal Moraine carries the clause and is an
    ordinary untapped land. Ask is_tapped_fetcher, which reads both halves.
    """
    return FETCH_TAPPED in txt


def is_tapped_fetcher(face, card=None):
    """A land that makes no mana of its own and hands you a TAPPED land.

    Evolving Wilds and Terramorphic Expanse produce nothing at all and fetch a
    basic that enters tapped, so what you have on the turn you play one is
    exactly what an unconditionally tapped land gives you: nothing. They were
    scored as untapped any-colour sources, because "a fetchland is never
    tapped" was written as a universal and holds only of the ones that fetch
    UNTAPPED -- Verdant Catacombs, Prismatic Vista, the whole Onslaught and
    Zendikar cycle. See KNOWN_ISSUES.md #20 for what that moved.

    The no-mana half of the gate is what keeps the two families apart.
    Terminal Moraine taps for {C} the turn it lands and its fetch sits behind
    an activated `{2}, {T}, Sacrifice` cost, so it is an untapped land that
    happens to carry the clause -- and it is the same gate build_land_profiles
    uses to decide a land is a fetch at all, deliberately, so the two cannot
    drift apart the way the land and accelerant restriction rules once did.

    `card` is consulted for produced_mana only when the face carries none,
    matching build_land_profiles: a land face on a DFC has its own entry, a
    single-faced card has it at the top level.
    """
    pm = [x for x in (face.get("produced_mana")
                      or (card or {}).get("produced_mana") or [])
          if x in MANA_SYMBOLS]
    if pm:
        return False
    txt = (face.get("oracle_text") or "").lower()
    return bool(fetch_targets(txt)) and fetches_tapped(txt)


def mana_amount(txt):
    """Largest number of mana a single 'Add ...' clause produces. Ancient Tomb
    is {C}{C} and counts as two sources for the quantity question."""
    best = 1
    low = (txt or "").lower()
    for m in re.finditer(r"add ([^.;\n]*)", low):
        clause = m.group(1)
        # An "Add" clause lists ALTERNATIVES separated by commas and "or"; the
        # land produces ONE of them. Counting symbols across the whole clause
        # credited every dual land with 2 mana and Jetmir's Garden with 3,
        # which inflated every play-simulation figure in a multicolour deck.
        # Concatenated symbols WITHIN one alternative are real: Ancient Tomb
        # "Add {C}{C}" is 2, Azorius Chancery "Add {W}{U}" is 2.
        for alt in re.split(r",|\bor\b", clause):
            n = len(re.findall(r"\{[wubrgc]\}", alt))
            if not n:
                wm = re.match(r"\s*(one|two|three|four|five|six)\s+mana", alt)
                n = WORDNUM[wm.group(1)] if wm else 0
            best = max(best, n)
    return max(best, 1)
