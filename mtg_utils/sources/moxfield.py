"""Moxfield v3: the private backend, and the parse every subcommand starts from."""
import json
import subprocess
import time
from collections import Counter

from mtg_utils.sources import UA_BROWSER

def parse_moxfield(d):
    """v3 shape, as a PURE function so a shape change is caught by selftest.

    Boards nest under `boards`, cards are keyed by opaque internal ids, and the
    board key union includes `partners` alongside `commanders`. This is the
    single highest-blast-radius parse in the file: every subcommand starts
    here, and a silent shape change would produce a plausible partial deck.
    """
    cmdrs, main = [], Counter()
    boards = d.get("boards") or {}
    if not boards:
        raise SystemExit("Moxfield returned no boards -- 403 (UA fingerprint) "
                         f"or an error body: {str(d)[:200]!r}")
    for bname in ("commanders", "partners"):
        for e in ((boards.get(bname) or {}).get("cards") or {}).values():
            cmdrs.append(e["card"]["name"])
    for e in ((boards.get("mainboard") or {}).get("cards") or {}).values():
        main[e["card"]["name"]] += e["quantity"]
    return d.get("name"), cmdrs, main


def moxfield_deck(deck_id):
    """curl ONLY -- api2.moxfield.com fingerprints the client; urllib 403s."""
    for _try in range(3):
        r = subprocess.run(["curl", "-s", "-H", f"User-Agent: {UA_BROWSER}",
                            f"https://api2.moxfield.com/v3/decks/all/{deck_id}"],
                           capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
        except Exception:
            time.sleep(3); continue
        return parse_moxfield(d)
    raise SystemExit(f"Moxfield fetch failed for {deck_id} "
                     f"(last body: {r.stdout[:200]!r})")


def moxfield_user_decks(user, fmt="commander"):
    """Public decks for a user. Search LAGS several minutes behind edits and
    lists only public decks, so a missing deck means private, unlisted, or not
    yet propagated -- never assume it does not exist."""
    url = ("https://api2.moxfield.com/v2/decks/search?authorUserNames="
           f"{user}&pageNumber=1&pageSize=100")
    r = subprocess.run(["curl", "-s", "-H", f"User-Agent: {UA_BROWSER}",
                        "-H", "Cache-Control: no-cache", "-H", "Pragma: no-cache", url],
                       capture_output=True, text=True)
    d = json.loads(r.stdout)
    return [(x["publicId"], x["name"]) for x in d.get("data", [])
            if (not fmt or x.get("format") == fmt)
            and "(duplicated from" not in x.get("name", "")]
