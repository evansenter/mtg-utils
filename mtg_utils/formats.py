"""What a FORMAT is, to this tool: a deck size, a legality key, a table size.

Three facts, and every one of them was a constant somewhere before this file
existed. `write` asserted `total == 100`, `verify` warned against 100 and read
`legalities["commander"]`, and the play/draw framing was written for a
four-player table. All four are correct for Commander and wrong for a 60-card
Standard Brawl list, which is a real deck someone brought to this toolchain on
the day it stopped working.

Deliberately three entries and not a taxonomy. Each one here is a format a
deck has actually been run through, with its `legality` key checked against a
live Scryfall record rather than recalled -- Scryfall spells historic Brawl
`brawl` and the 60-card format `standardbrawl`, with no `historicbrawl` key at
all, and a key that does not exist reads as "not legal" for every card in the
list rather than as a typo. Adding a fourth means checking its key the same
way.

`players` is the table size, and it is not decoration: every play-simulation
report prints an on-the-play and an on-the-draw column, and which one a
summary should lean on is exactly this number. At a four-player table you are
on the draw three turns in four; in 1v1 it is one in two.
"""

FORMATS = {
    "commander": {"size": 100, "legality": "commander",
                  "label": "Commander", "players": 4},
    # Arena's historic Brawl: 100 cards, one commander, and 1v1.
    "brawl": {"size": 100, "legality": "brawl",
              "label": "Brawl", "players": 2},
    "standardbrawl": {"size": 60, "legality": "standardbrawl",
                      "label": "Standard Brawl", "players": 2},
}

DEFAULT_FORMAT = "commander"


def spec(fmt=None):
    """The format table for `fmt`, defaulting to Commander.

    Fails by NAME on an unknown format. The alternative -- falling back to
    Commander -- would run the whole report against the wrong population and
    the wrong deck size while printing the format the caller asked for at the
    top of it.
    """
    fmt = fmt or DEFAULT_FORMAT
    if fmt not in FORMATS:
        raise SystemExit(
            f"unknown format {fmt!r}. Known: {', '.join(sorted(FORMATS))}. "
            f"Each carries a deck size and the Scryfall legality key to read, "
            f"so a format this tool has not been told about cannot be guessed "
            f"at -- it would check a legality key that does not exist, which "
            f"reads as 'every card is illegal'.")
    return FORMATS[fmt]


def deck_size(fmt=None):
    return spec(fmt)["size"]


def is_legal(card, fmt=None):
    """Is this Scryfall record legal in `fmt`?

    A card the cache has never seen is NOT legal here, because nothing says it
    is. Callers that want to distinguish "illegal" from "unknown" have to look
    the record up themselves -- `verify` does, and reports NOT FOUND
    separately, which is the distinction that matters when a name is simply
    misspelled.
    """
    key = spec(fmt)["legality"]
    return (card or {}).get("legalities", {}).get(key) == "legal"
