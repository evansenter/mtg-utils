"""edhtop16: cEDH tournament inclusion, counted from returned entries.

GraphQL at https://edhtop16.com/api/graphql. Three things worth encoding:

**Commander names must be JSON-encoded, not string-escaped.** Names carry
apostrophes (`Kraum, Ludevic's Opus`), and hand-built backslash escaping
breaks on them. The query is sent with variables and `json.dumps` does the
encoding.

**A partner pair is one commander here**, written as the two names joined by
`" / "` and sorted alphabetically -- `Thrasios, Triton Hero / Tymna the
Weaver`. Querying either half alone resolves to a commander with ZERO
entries, which reads as "no cEDH data" rather than as "wrong name".

**Inclusion is counted manually across entries**, and below a handful of
entries the number is meaningless. `parse_edhtop16` therefore returns the
entry count alongside every percentage and the report refuses to quote a
percentage under MIN_ENTRIES.
"""
import json
import os
import subprocess
import time
from collections import Counter

from mtg_utils.cards import front_name
from mtg_utils.sources import UA_BROWSER

EDHTOP16_GQL = "https://edhtop16.com/api/graphql"

# Below this many tournament entries, a per-card percentage is noise dressed
# as data: at four entries every card is 25%, 50%, 75% or 100%.
MIN_ENTRIES = 5

_QUERY = """query($n: String!, $first: Int!) {
  commander(name: $n) {
    name
    entries(first: $first) { edges { node { maindeck { name } } } }
  }
}"""


def edhtop16_commander_name(cmdr):
    """Commander(s) -> the name edhtop16 keys on.

    A partner pair is ONE commander there, joined by " / " and sorted
    alphabetically. Passing one half alone returns a commander with zero
    entries -- indistinguishable from a commander nobody plays, which is
    exactly the wrong conclusion to draw about Thrasios.
    """
    names = list(cmdr) if isinstance(cmdr, (list, tuple)) else [cmdr]
    return " / ".join(sorted(names))


def edhtop16_fetch(name, cache_path=None, first=100):
    """Fetch tournament entries for a commander, memoised on disk by name.

    Returns the raw GraphQL `data.commander` object, or None.
    """
    key = f"edhtop16/{first}/{name}"
    cache = {}
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
    if key in cache:
        return cache[key]
    # json.dumps does the escaping. Building the query string by hand and
    # backslash-escaping the name breaks on every commander with an
    # apostrophe, which in cEDH is most of the popular ones.
    payload = json.dumps({"query": _QUERY,
                          "variables": {"n": name, "first": first}})
    data = None
    for _try in range(3):
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", "-H", "Content-Type: application/json",
             "-H", f"User-Agent: {UA_BROWSER}", "--data-binary", payload,
             EDHTOP16_GQL],
            capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
        except Exception:
            time.sleep(1); continue
        if d.get("errors"):
            raise SystemExit(f"edhtop16 GraphQL error: {d['errors']}")
        data = (d.get("data") or {}).get("commander")
        break
    if data is None:
        return None
    cache[key] = data
    if cache_path:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    return data


def parse_edhtop16(data):
    """Commander entries -> (rows, entry_count).

    Counted per entry, not per copy: a card is in a decklist or it is not.

    edhtop16 returns FULL DFC names ("Sink into Stupor // Soporific
    Springs") -- the opposite convention from EDHREC, which returns front
    faces only. Both are keyed to the front face here so one comparison works
    against either source and against a decklist spelling out both halves.
    """
    edges = (((data or {}).get("entries") or {}).get("edges")) or []
    n = len(edges)
    counts = Counter()
    for e in edges:
        deck = ((e or {}).get("node") or {}).get("maindeck") or []
        seen = {front_name(c.get("name")) for c in deck if c.get("name")}
        counts.update(seen)
    # synergy is an EDHREC statistic and this endpoint does not carry it.
    # Emitted as None so the column prints "-" rather than 0.0, which would
    # read as "measured, and this card is pure goodstuff" -- a claim no
    # tournament sample here supports. Sorting by synergy against --cedh
    # therefore ranks nothing, which is correct and visible.
    rows = [{"name": name, "num_decks": k, "potential_decks": n,
             "inclusion": 100.0 * k / n, "synergy": None,
             "cardlist": "edhtop16"}
            for name, k in counts.items()] if n else []
    # Ties are broken by NAME so the order is total. Without a
    # tiebreaker the order of equal-inclusion rows falls out of dict or
    # set iteration, which Python randomises per process -- so the table
    # printed a different ranking on every run. At six tournament
    # entries most cards tie at 100%, and whichever one floated to the
    # top read as the strongest signal in the report.
    rows.sort(key=lambda r: (-r["inclusion"], r["name"]))
    return rows, n
