"""One commander's population ranking, from whichever source was asked for.

`ceiling` and `floor` are the same question asked in opposite directions --
what is above the bar and absent, what is in the list and below it -- and they
read the same two endpoints through the same slug and name rules. The fetch,
the source selection and the "no response" guard live here so a third source,
or a fix to one of those rules, lands in one place instead of two.

What deliberately does NOT live here is anything that prints. Both printers
emit their header line between the fetch and their remaining guards, so
hoisting those guards up here would move the header relative to the failure it
explains -- and `ceiling`'s bytes are snapshotted.

The two sources differ in one way every caller has to respect, so it is
carried in the bundle rather than re-derived at each call site:

    EDHREC     ranks the TOP of each cardlist and stops. A card it does not
               rank is of UNKNOWN inclusion, bounded only by how deep that
               list went -- `floors` says how deep, per list.
    edhtop16   counts whole decklists. A card it does not rank appeared in
               zero of them, which is a MEASURED zero. `exhaustive` is True
               and `floors` is empty, because there is no floor to be below.

Reading the second as the first understates; reading the first as the second
invents a 0% for every card the page simply stopped short of.
"""
from mtg_utils.formats import spec as format_spec
from mtg_utils.sources.edhrec import (display_floors, edhrec_fetch, edhrec_slug,
                                      parse_commander_page)
from mtg_utils.sources.edhtop16 import (edhtop16_commander_name, edhtop16_fetch,
                                        parse_edhtop16)

# How each source is named in a report header. Kept here so `ceiling` and
# `floor` cannot drift into spelling the same source two ways.
SOURCE_LABEL = {"edhrec": "EDHREC", "edhtop16": "edhtop16"}


# What each source's population actually is. BOTH of them are Commander, and
# neither says so anywhere in its payload.
POPULATION = {
    "edhrec": "EDHREC ranks the COMMANDER population and has no {label} page",
    "edhtop16": "edhtop16 counts COMMANDER tournament entries, not {label} "
                "results",
}


def population_mismatch(source, fmt=None):
    """Lines warning that the ranking population is not the deck's format.

    Returns () when the format IS Commander, which is every existing caller.

    Prints nothing -- like everything else in this module, it returns the
    text and lets the printer place it. Both printers emit their header
    between the fetch and their remaining guards, and `ceiling`'s bytes are
    snapshotted.

    This is worth a warning rather than a footnote because the failure is
    silent and confident. Fetched for a Standard Brawl commander during the
    session that prompted it, the page recommended Enchantress's Presence,
    Sythis, Starfield of Nyx and three more at 27-57% inclusion, and NOT ONE
    of them is legal in the format. Read by hand and labelled, a cross-format
    ranking is a useful archetype signal; run as a recommendation engine it
    produces a list of unplayable cards with confident percentages beside
    them.
    """
    spec = format_spec(fmt)
    if spec["legality"] == "commander":
        return ()
    return (f"  POPULATION IS COMMANDER, NOT {spec['label'].upper()}: "
            f"{POPULATION[source].format(label=spec['label'])}.",
            f"  Read these rows as an archetype signal, not as a "
            f"recommendation for this format.")


def fetch_ranking(cmdrs, rec_cache=None, cedh=False):
    """Commander(s) -> the population's ranking, as one bundle.

    NETWORK unless `rec_cache` already holds the page. Raises SystemExit when
    the endpoint gave nothing back, which is the one guard that sits at the
    same point in both printers -- before either has printed a line.

    Returns:
        source      "edhrec" | "edhtop16"
        label       the slug or commander name the report names in its header
        rows        parse_commander_page / parse_edhtop16 rows, front-face keyed
        capped      cardlist headers that came back at the display cap
        floors      {header: {header, entries, ranked, floor, capped}}; {}
                    for edhtop16. `ranked` is the depth a bound rests on and
                    the one a caller must quote -- see display_floors
        n_entries   tournament entries counted; None for EDHREC
        exhaustive  True when an unranked card is a measured zero, not a bound
    """
    if cedh:
        name = edhtop16_commander_name(cmdrs)
        data = edhtop16_fetch(name, rec_cache)
        if data is None:
            raise SystemExit(f"edhtop16: no response for {name!r}")
        rows, n_entries = parse_edhtop16(data)
        return {"source": "edhtop16", "label": name, "rows": rows,
                "capped": [], "floors": {}, "n_entries": n_entries,
                "exhaustive": True}
    slug = edhrec_slug(cmdrs)
    data = edhrec_fetch(slug, rec_cache)
    if data is None:
        raise SystemExit(
            f"EDHREC: no page for slug {slug!r}. Note apostrophes are "
            f"DROPPED, not hyphenated -- a wrong slug 403s rather than "
            f"404s, so this can read as a block.")
    rows, capped = parse_commander_page(data)
    return {"source": "edhrec", "label": slug, "rows": rows, "capped": capped,
            "floors": display_floors(data), "n_entries": None,
            "exhaustive": False}
