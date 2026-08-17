"""EDHREC: commander inclusion percentages, with an on-disk cache.

Two things about this endpoint cost an afternoon each to find, so they are
encoded here rather than left to be rediscovered.

**The slug drops apostrophes, it does not hyphenate them.**
`Y'shtola, Night's Blessed` is `yshtola-nights-blessed`. Building
`y-shtola-nights-blessed` the way a naive punctuation-to-hyphen rule would
returns **403**, not 404 -- so the failure reads as "EDHREC is blocking us"
rather than as "that slug is wrong". Verified against the live endpoint.

**Inclusion is not a field.** `cardviews` carry `num_decks` and
`potential_decks`; the percentage is the ratio. Reading a nonexistent
`inclusion` key gives None, and None formatted into a table reads as 0%.

**Cardlists are capped at 50 per type.** Absence from the page is therefore
NOT evidence a card is unplayed, and this module never lets a caller confuse
the two: `parse_commander_page` marks each list that came back at the cap, and
a card missing from a capped list is reported as "below cutoff" rather than
scored.

**Each cardlist stops at a DIFFERENT depth**, and that difference is the only
thing on the page that says anything about a card it did not rank.
`display_floors` reads it off; the numbers are in that docstring.
"""
import json
import os
import re
import subprocess
import time

from mtg_utils.cards import front_name
from mtg_utils.sources import UA_BROWSER

EDHREC_JSON = "https://json.edhrec.com/pages"

# A cardlist that comes back at exactly this length was truncated by EDHREC,
# so anything not on it is simply unknown. Observed at 50 for Creatures and
# Lands on a real commander page while Instants came back at 36.
PAGE_CAP = 50


def edhrec_slug(name):
    """Commander name -> EDHREC slug.

    Apostrophes are DROPPED; every other run of non-alphanumerics becomes a
    single hyphen. `Kroxa, Titan of Death's Hunger` ->
    `kroxa-titan-of-deaths-hunger`.

    A partner pair is joined with a hyphen in ALPHABETICAL order, which is
    the canonical form: `tymna-the-weaver-thrasios-triton-hero` does not 404,
    it returns `{"redirect": "/commanders/thrasios-triton-hero-tymna-the-
    weaver"}` -- a 200 with no cardlists in it. Parsed without care that
    yields zero ranked cards and an audit that reports nothing missing, which
    reads as a clean bill of health for the deck. edhrec_fetch follows the
    redirect anyway; sorting here just gets it right on the first request.

    A DFC uses its FRONT face only -- EDHREC pages are keyed on the front.
    """
    if isinstance(name, (list, tuple)):
        return "-".join(sorted(edhrec_slug(n) for n in name))
    name = front_name(name)
    # Drop apostrophes FIRST, so they close up rather than becoming hyphens.
    # Covers the typographic apostrophe too: Scryfall uses U+2019 in some
    # names and a straight quote in others, and the slug is the same either
    # way.
    name = re.sub(r"['’]", "", name.lower())
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name)).strip("-")


def edhrec_fetch(slug, cache_path=None, page="commanders"):
    """Fetch one EDHREC page, memoised on disk by (page, slug).

    Cache shape mirrors scry_fetch's: a plain dict written back on every run.
    A miss is fetched with a browser User-Agent and a Referer, which is what
    the endpoint expects; a failure is returned as None rather than cached,
    for the same reason scry_fetch does not cache a not_found -- the two
    reasons a page fails are a wrong slug and a page that does not exist yet,
    and both want a retry.
    """
    key = f"{page}/{slug}"
    cache = {}
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
    if key in cache:
        return cache[key]
    data = None
    # A non-canonical slug answers 200 with {"redirect": "/commanders/..."}
    # and no cardlists. Following it is not optional: parsed as a page it
    # ranks zero cards, and an audit over zero cards reports nothing missing
    # -- a silent pass for a deck nobody checked. Bounded so a redirect loop
    # cannot spin.
    for _hop in range(3):
        url = f"{EDHREC_JSON}/{page}/{slug}.json"
        data = None
        for _try in range(3):
            r = subprocess.run(
                ["curl", "-s", "-H", f"User-Agent: {UA_BROWSER}",
                 "-H", "Referer: https://edhrec.com/", url],
                capture_output=True, text=True)
            try:
                data = json.loads(r.stdout)
                break
            except Exception:
                time.sleep(1)
        if not isinstance(data, dict) or "redirect" not in data:
            break
        slug = data["redirect"].rstrip("/").split("/")[-1]
        time.sleep(0.2)
    if data is None:
        return None
    cache[key] = data
    if cache_path:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    return data


def parse_commander_page(data):
    """EDHREC commander JSON -> (rows, capped_lists).

    rows: one dict per distinct card, front-face keyed, carrying
    num_decks, potential_decks and the computed inclusion percentage.
    capped_lists: the cardlist headers that came back AT the display cap, so
    the caller can say "below cutoff" instead of inventing a zero.

    A card appearing in two cardlists (Lands and Utility Lands, say) is kept
    once, at its highest inclusion -- the same card counted twice would make
    a deck look like it was missing two cards.
    """
    lists = (((data or {}).get("container") or {}).get("json_dict") or {}).get("cardlists") or []
    rows, capped = {}, []
    for cl in lists:
        views = cl.get("cardviews") or []
        if len(views) >= PAGE_CAP:
            capped.append(cl.get("header") or "?")
        for cv in views:
            num, pot = cv.get("num_decks"), cv.get("potential_decks")
            if not num or not pot:
                # No ratio means no percentage. Emitting 0.0 here is how a
                # missing field becomes a confident wrong number in a table.
                continue
            # EDHREC returns FRONT-FACE names ("Agadeem's Awakening", never
            # "Agadeem's Awakening // Agadeem, the Undercrypt"). Keyed on the
            # front face so it compares against a decklist that spells out
            # both halves -- the bug that reported an in-deck card missing.
            name = front_name(cv.get("name"))
            if not name:
                continue
            pct = 100.0 * num / pot
            prev = rows.get(name.lower())
            if prev is None or pct > prev["inclusion"]:
                # synergy is carried through as None when absent, never as
                # 0.0. Zero is a REAL synergy value -- it is what a pure
                # goodstuff card scores -- so a missing field defaulted to
                # zero is indistinguishable from a measured "no better here
                # than anywhere else", which is the one thing this column
                # exists to tell apart.
                rows[name.lower()] = {
                    "name": name, "num_decks": num, "potential_decks": pot,
                    "inclusion": pct, "synergy": cv.get("synergy"),
                    "cardlist": cl.get("header") or "?"}
    # Total order: ties break by name. Insertion order happens to be stable
    # here because the page JSON is, but relying on that makes the ordering
    # an accident of the source rather than a property of this function --
    # and the edhtop16 parser had exactly that bug.
    return sorted(rows.values(),
                  key=lambda r: (-r["inclusion"], r["name"])), capped


def display_floors(data):
    """EDHREC commander JSON -> {header: {header, entries, floor, capped}}.

    The complement of `parse_commander_page`. That function reports what the
    page RANKED; this one reports how deep each list went, which is the only
    thing on the page that says anything at all about a card it did not rank.

    Absence is worth wildly different amounts per type, because EDHREC stops
    each list at a different depth. Measured on the live commander page this
    repo's floor.rec.json fixture was captured from, 2026-08-16:

        Creatures           50 rows, lowest shown  5.80%   (at the cap)
        Instants            42 rows, lowest shown  5.06%
        Mana Artifacts      16 rows, lowest shown  5.44%
        Enchantments        11 rows, lowest shown  5.34%
        Utility Artifacts    6 rows, lowest shown  5.55%
        Battles              1 row,  lowest shown  5.44%

    so a single number for the whole page would throw the difference away.
    The depths MOVE with the population, so they are read off the page
    fetched in this run and never pinned in code.

    `floor` is the lowest inclusion the list actually printed, so a card the
    list omits sits AT OR BELOW it -- at, not strictly below, because a tie
    on the boundary row is broken by something this end cannot see. Callers
    report it as `<=` for that reason.

    A list that ranked nothing is dropped rather than recorded at 0.0: a
    floor of zero reads as "everything is below 0%", which is the strongest
    possible claim drawn from the weakest possible evidence -- the same
    mistake `parse_commander_page` refuses to make on a cardview with no
    ratio.

    `entries` and `ranked` are BOTH carried, and they are different numbers
    whenever a cardview came back without a ratio. `entries` is how many rows
    the page displayed, which is what `capped` is a statement about and what
    keeps this agreeing with `parse_commander_page`. `ranked` is how many of
    them carried a figure, which is the depth `floor` was actually measured
    over -- so it is the one a caller must quote as the justification for a
    bound. Collapsing the two would have a list print "50 rows" as the
    evidence for a floor read off however many of them happened to be
    scoreable.
    """
    lists = (((data or {}).get("container") or {}).get("json_dict") or {}).get("cardlists") or []
    out = {}
    for cl in lists:
        header = cl.get("header") or "?"
        views = cl.get("cardviews") or []
        pcts = [100.0 * cv["num_decks"] / cv["potential_decks"] for cv in views
                if cv.get("num_decks") and cv.get("potential_decks")]
        if not pcts:
            continue
        entry = {"header": header, "entries": len(views), "ranked": len(pcts),
                 "floor": min(pcts), "capped": len(views) >= PAGE_CAP}
        prev = out.get(header)
        # A repeated header keeps the HIGHER floor. Every use of this is a
        # bound of the form "below x", so the weaker of two candidates is the
        # safe one -- the same reason display_floor_bound takes the max over
        # the lists a card could have been filed under.
        if prev is None or entry["floor"] > prev["floor"]:
            out[header] = entry
    return out
