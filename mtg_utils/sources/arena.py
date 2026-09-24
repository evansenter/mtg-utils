"""Arena printings: which `(SET) NUMBER` an Arena import line has to name.

Arena's importer does not take a bare card name. It takes

    N Card Name (SET) CollectorNumber

and it wants a printing that EXISTS ON ARENA, which is not the same as the
printing Scryfall returns for a name. So every line needs a search, and the
search needs three filters and a tie-break -- all of which were hand-rolled
twice in one session before this module existed, which is the usual sign.

The filters, in the order they matter:

  on Arena          `games` must contain "arena". A paper-only printing gives
                    a set code Arena has never heard of and the whole import
                    fails on that line.
  legal in format   PER CARD, not per printing: Scryfall's `legalities` is an
                    oracle-level field repeated identically on every printing
                    record, so this rule can never pick one printing over
                    another. What it does is make an illegal CARD a miss, so
                    `write --arena` refuses to emit a line for it rather than
                    writing a file Arena accepts and the format does not.
  numeric number    Scryfall really does return collector numbers like `1★`,
                    `M19-314` and `410z`. Every one this repo's probes found
                    is paper-only, so the `games` filter already removes them
                    today -- this is a second guard, and it is here rather
                    than assumed because the session that prompted this
                    module had a promo printing break an import.

Two of those three therefore reject nothing in the frozen capture: the search
applies the `games` filter itself, and legality is per card. They are tested
against hand-built candidates, and the fact that the capture cannot exercise
them is written down in the cases rather than left for someone to assume it
does.

The tie-break is the most recent RELEASED printing, because that is the one
Arena players actually have and the one its collection UI shows first.
"Released" is load-bearing: Scryfall lists preview sets weeks ahead, and the
first capture of the brawl fixture's basics picked `TRK`, dated 2026-11-13,
on 2026-08-30 -- a set code Arena did not have yet, on 17 lines of a 60-card
import. A printing dated after `today` is not a candidate. Ties on the
release date break on the set code, so a rerun writes the same file: two Arena
sets really do share a release day.

**Scryfall's search endpoint is rate limited harder than /cards/collection.**
0.1-0.2s is fine there and 429s here; this waits ~0.5s and backs off, and it
asserts the result count rather than trusting the loop, which is the rule
every search loop in this repo follows.

A name with no Arena printing at all is NOT an error -- Sol Ring has none --
so it comes back as a miss the caller reports, the way scry_fetch reports
`not_found`.
"""
import json
import os
import subprocess
import time
import urllib.parse

from mtg_utils.cards import front_name
from mtg_utils.formats import spec as format_spec
from mtg_utils.sources import UA_TOOL

SEARCH = "https://api.scryfall.com/cards/search"

# What a printing is reduced to on disk. The cache is a PROJECTION for the
# same reason tests/fixtures/ceiling.scry.json is: the full records for one
# 60-card deck run to megabytes to answer a question that needs five fields
# per printing. Every value in it is verbatim.
PRINTING_FIELDS = ("set", "collector_number", "rarity", "released_at",
                   "games", "legalities")


def _project(card):
    return {k: card.get(k) for k in PRINTING_FIELDS}


def arena_fetch(name, cache_path=None):
    """Every Arena printing of `name`, projected, memoised on disk.

    Returns a list, empty when the card has no Arena printing at all. That is
    a real answer and it IS cached: "Sol Ring is not on Arena" does not become
    true later in the way a 404 for a card too new for Scryfall does.

    A FAILED request is not cached, for the reason scry_fetch does not cache a
    not_found: a transport failure and a genuine absence must not become the
    same stored answer.
    """
    key = f"arena/{front_name(name).lower()}"
    cache = {}
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
    if key in cache:
        return cache[key]
    q = f'!"{front_name(name)}" game:arena'
    url = (f"{SEARCH}?q={urllib.parse.quote(q)}&unique=prints&order=released")
    rows, total = [], None
    while url:
        data = _search_page(url, q)
        if data.get("object") == "error":
            # "Your query didn't match any cards" is the shape a card with no
            # Arena printing comes back as. Any OTHER error is a fault and must
            # not be stored as "this card is not on Arena".
            if data.get("code") != "not_found" or rows:
                raise SystemExit(f"Scryfall /cards/search: {data.get('details')}")
            break
        total = data.get("total_cards")
        rows += data.get("data") or []
        # A page is 175 cards and a basic land has more Arena printings than
        # that -- Swamp had 209 on 2026-09-24. The first version read one page
        # and checked `len(rows) <= total`, which cannot fail.
        url = data.get("next_page") if data.get("has_more") else None
        if url:
            time.sleep(0.5)
    if total is not None:
        # Asserted, not trusted: a short page under `object: list` is what a
        # silent 429 looks like, and a card that came back short here would be
        # priced off whichever printings happened to arrive.
        assert len(rows) == total, (q, total, len(rows))
    out = [_project(c) for c in rows]
    cache[key] = out
    if cache_path:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    time.sleep(0.5)
    return out


def _search_page(url, q):
    """One /cards/search page, with backoff. See the module docstring."""
    for attempt in range(4):
        r = subprocess.run(["curl", "-s", "-H", "Accept: application/json",
                            "-H", f"User-Agent: {UA_TOOL}", url],
                           capture_output=True, text=True)
        try:
            data = json.loads(r.stdout)
        except Exception:
            time.sleep(0.5 + attempt * 2)
            continue
        if data.get("object") in ("list", "error"):
            return data
        time.sleep(0.5 + attempt * 2)
    raise SystemExit(f"Scryfall /cards/search failed after retries: {q}")


def pick_arena_printing(printings, fmt=None, today=None):
    """The printing an Arena import line should name, or None.

    Pure, so the selection rules are testable without the network -- which is
    the half that actually goes wrong. See the module docstring for why each
    filter is there and why the tie-break is total.

    `today` is an ISO date string and defaults to the current UTC date. It is
    a parameter so a test can pin it: the frozen capture holds a preview set
    dated 2026-11-13, and a case that read the clock would change its answer
    on that day with no code change.
    """
    today = today or time.strftime("%Y-%m-%d", time.gmtime())
    key = format_spec(fmt)["legality"]
    ok = [p for p in printings or []
          if "arena" in (p.get("games") or [])
          and (p.get("legalities") or {}).get(key) == "legal"
          and str(p.get("collector_number") or "").isdigit()
          and (p.get("released_at") or "") <= today]
    if not ok:
        return None
    # Newest first; the set code makes the order total. Sorting rather than
    # trusting `order=released` because the cache is a frozen projection and
    # a rerun has to write the same file as the run before it.
    return max(ok, key=lambda p: (p.get("released_at") or "",
                                  p.get("set") or ""))


def arena_printings(names, fmt=None, cache_path=None, today=None):
    """({front-face name lowered: printing}, [names with no usable printing]).

    NETWORK per distinct name on a cache miss, one search each -- see the
    module docstring on the rate limit.

    A name is a MISS when the card is not on Arena at all and when every Arena
    printing of it is illegal in the format or unimportable. Those are
    different facts and the caller reports them the same way, deliberately:
    either way there is no line it can write, and inventing one would produce
    a file Arena rejects halfway through.
    """
    out, missing = {}, []
    for n in dict.fromkeys(front_name(x) for x in names):
        pick = pick_arena_printing(arena_fetch(n, cache_path), fmt, today)
        if pick is None:
            missing.append(n)
        else:
            out[n.lower()] = pick
    return out, missing
