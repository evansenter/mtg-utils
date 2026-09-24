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


# The FIFTH "enters tapped" class, and the mirror image of every marker above:
# untapped EARLY and tapped LATE.
#
#   Starting Town  "This land enters tapped unless it's your first, second,
#                   or third turn of the game."
#
# Nothing in CONDITIONAL_TAP_MARKERS matches that, so it fell through to TRULY
# TAPPED -- which understates the deck, and understates it hardest in the
# early turns where a tapped land actually costs something. It is also not
# fixable by adding the string to the marker tuple: that would report the land
# as never tapped, which is wrong in the other direction from turn four
# onward. The class needs a turn, so the classifier returns one.
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
            "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
# The clause lists the turns on which the land enters UNTAPPED, so the answer
# is one past the LAST of them. Anchored on "turn of the game" so it cannot
# match "unless it's your turn" or any other conditional that happens to name
# an ordinal.
TURN_TAP = re.compile(r"unless it'?s your ([^.]*?) turn of the game")


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


def tapped_from_turn(txt):
    """The first turn this land enters TAPPED, or None if it has no such clause.

    "unless it's your first, second, or third turn of the game" names the
    turns it enters UNTAPPED, so the answer is one past the last of them: 4.

    The LAST ordinal in the clause, not the first and not the count of them.
    A card worded "unless it's your first or second turn" is a 3 and a card
    worded "unless it's your third turn" -- which nothing prints today -- is a
    4; counting the words would answer 3 for the second one.
    """
    m = TURN_TAP.search(txt or "")
    if not m:
        return None
    turns = [ORDINALS[w] for w in re.findall(r"[a-z]+", m.group(1))
             if w in ORDINALS]
    return max(turns) + 1 if turns else None


def enters_tapped_turn(face, card=None):
    """(tapped, conditional-marker, first-tapped-turn) for a land face.

    Three outcomes, not two, and the third is a real printed class rather than
    a generalisation for its own sake:

        (False, None, None)      never tapped
        (False, "<marker>", None) tapped unless a condition you usually meet
        (True, None, None)       truly tapped
        (True, None, 4)          untapped on turns 1-3, tapped from turn 4

    The turn is what makes the last one representable at all. Both models know
    which turn they are asking about, so honouring it is cheap -- and the two
    alternatives are wrong in opposite directions: TRULY TAPPED understates
    the early turns where a tapped land costs the most, and a conditional
    marker would report the land as untapped on turn seven.
    """
    txt = (face.get("oracle_text") or "").lower()
    if "enters tapped" not in txt and "enters the battlefield tapped" not in txt:
        return False, None, None
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
        return False, max(hits, key=len), None
    # Tested AFTER the markers, so a card carrying both is read as
    # conditional. No printed card carries both; the order is written down
    # rather than left to whichever branch came first, the same way
    # triggered_mana's phase-before-event order is.
    return True, None, tapped_from_turn(txt)


def enters_tapped(face, card=None):
    """(tapped, conditional-marker). The two-value form, kept verbatim.

    `card` is unused and kept optional: every call site passes one, and
    mtg_utils re-exports this, so dropping the parameter would break any
    script that still calls enters_tapped(face, card).

    A turn-conditional land answers (True, None) here -- tapped, with no
    marker -- which is exactly what it answered before the third class
    existed. Callers that must not lose the turn use enters_tapped_turn; this
    one is kept so a caller that never knew about it is not silently told the
    land is never tapped.
    """
    tapped, cond, _from = enters_tapped_turn(face, card)
    return tapped, cond


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
