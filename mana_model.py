#!/usr/bin/env python3
"""
mana_model.py — deck validation and castability for Commander decks.

ONE FILE. Do not create a second script beside this one; extend it and
re-deliver the whole thing (see PROJECT NOTES at the bottom).

Two models, because they answer different questions:

  sources model   "can I make these pips"      -> analyse()
  play simulation "do I have N mana on turn N" -> playsim()

Mana sources are LANDS PLUS CHEAP ACCELERANTS (mana value <= 3 that tap for
mana) plus MDFC land backs. Lands-only understates castability badly: measured
on Pantlaza, {2}{R}{G}{W} on turn five was 36.4% lands-only and 53.5% once the
accelerants were counted. The lands-only figure is a statement about land
count, not about castability, and must not be reported as one.

Subcommands
-----------
  fetch       build/refresh the Scryfall cache for a decklist
  verify      count, legality, colour identity, Game Changers, MV, tapped classes
  mana        sources model + play simulation (the full section 6 pass)
  roster      section 6 roster walk: every cycle slot, IN / benched / buy
  variants    opt-in land/accelerant sweep; slow, run when the base is unsettled
  combos      Commander Spellbook full-deck audit
  own         ownership vs ManaBox + grouped buy list
  contention  copies owned vs Moxfield decks wanting the card
  moxfield    fetch a live deck into decklist format
  write       write the final 100 and assert it back
  diff        card-multiset diff of a local list against the LIVE Moxfield deck
  audit       verify + mana + roster + combos + own  (full pass, no variants)
  selftest    offline regression tests; run after ANY edit to this file
  calibrate   re-measure every live deck into one table (never store the rows)

Decklist format: first non-blank line is the commander, then one entry per
line as "N Card Name" or bare "Card Name".
"""
import json, random, re, sys, os, csv, time, math, subprocess, itertools, argparse
from collections import Counter, defaultdict
from mtg_utils.decklist import (
    _entry,
    read_decklist,
    as_cmdrs,
    flat,
    write_deck,
    diff_multiset)
from mtg_utils.castability import (
    pips_from_cost,
    castable_faces,
    _match,
    castable,
    playable_set,
    probability,
    hypergeometric,
    playsim,
    playsim_report)
from mtg_utils.profiles import (
    FILTER_LANDS,
    OMNI_TYPE,
    build_land_profiles,
    build_accel_profiles)
from mtg_utils.cards import (
    COLOURS,
    MANA_SYMBOLS,
    BASIC_TYPE_COLOUR,
    CONDITIONAL_TAP_MARKERS,
    CONDITIONAL_TAP_PATTERNS,
    WORDNUM,
    faces,
    land_face,
    front,
    is_front_land,
    has_land_back,
    enters_tapped,
    fetch_targets,
    mana_amount)

UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
UA_TOOL = "MTGDeckTool/2.0"
COLLECTION = "/mnt/project/ManaBox_Collection.csv"

# ============================================================ Scryfall
def scry_fetch(names, cache_path=None):
    cache = {}
    if cache_path and os.path.exists(cache_path):
        cache = json.load(open(cache_path))
    want = [n for n in dict.fromkeys(names) if n.lower() not in cache]
    nf = []
    for i in range(0, len(want), 75):
        chunk = want[i:i + 75]
        payload = json.dumps({"identifiers": [{"name": n.split(" // ")[0]} for n in chunk]})
        for _try in range(4):
            r = subprocess.run(
                ["curl", "-s", "-X", "POST", "-H", "Content-Type: application/json",
                 "-H", "Accept: application/json", "-H", f"User-Agent: {UA_TOOL}",
                 "-d", payload, "https://api.scryfall.com/cards/collection"],
                capture_output=True, text=True)
            try:
                d = json.loads(r.stdout)
            except Exception:
                time.sleep(2); continue
            if d.get("object") == "list":
                break
            time.sleep(2)
        else:
            raise SystemExit("Scryfall /cards/collection failed after retries")
        for c in d["data"]:
            # key on BOTH the full name and the front-face name
            cache[c["name"].lower()] = c
            cache[c["name"].split(" // ")[0].lower()] = c
        nf += [x.get("name") for x in d.get("not_found", [])]
        time.sleep(0.2)
    if cache_path:
        json.dump(cache, open(cache_path, "w"))
    return cache, nf


# ============================================================ verify
def verify(cmdr, entries, scry):
    cmdrs = as_cmdrs(cmdr)
    names = flat(cmdr, entries)
    total = len(names)
    gc, illegal, ci_bad = [], [], []
    ident = set()
    for cn in cmdrs:
        if scry.get(cn.lower()):
            ident |= set(scry[cn.lower()]["color_identity"])
    lands = nonland = 0
    mv_sum = 0.0
    truly, cond = [], []
    for n, q in list(entries.items()) + [(cn, 1) for cn in cmdrs]:
        c = scry.get(n.lower())
        if not c:
            illegal.append((n, "NOT FOUND")); continue
        if c["legalities"]["commander"] != "legal":
            illegal.append((n, c["legalities"]["commander"]))
        if set(c["color_identity"]) - ident:
            ci_bad.append((n, "".join(c["color_identity"])))
        if c.get("game_changer"):
            gc.append(n)
        if is_front_land(c):
            lands += q
            lf = land_face(c)
            t, cm = enters_tapped(lf, c)
            if t:
                truly.append(n)
            elif cm:
                cond.append((n, cm))
        elif n not in cmdrs:
            nonland += q
            mv_sum += float(front(c, "cmc", 0) or 0) * q
    mdfc = sum(q for n, q in entries.items()
               if scry.get(n.lower()) and has_land_back(scry[n.lower()]))
    return {"total": total, "lands": lands, "mdfc_land_backs": mdfc,
            "nonland": nonland, "avg_mv": mv_sum / nonland if nonland else 0,
            "game_changers": sorted(gc), "illegal": illegal,
            "ci_violations": ci_bad, "truly_tapped": truly,
            "conditional_tapped": cond}


# ============================================================ collection
def load_collection(path=COLLECTION):
    owned = defaultdict(int)
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            q = int(r["Quantity"])
            n = r["Name"].strip().lower()
            owned[n] += q
            front_name = n.split(" // ")[0]
            if front_name != n:
                owned[front_name] += q
    return owned


# ============================================================ external APIs
def spellbook(cmdr, entries):
    cmdrs = as_cmdrs(cmdr)
    payload = json.dumps({"commanders": [{"card": c} for c in cmdrs],
                          "main": [{"card": n} for n in flat(cmdr, entries)[len(cmdrs):]]})
    for _try in range(3):
        r = subprocess.run(["curl", "-s", "-X", "POST",
                            "-H", "Content-Type: application/json",
                            "-H", f"User-Agent: {UA_TOOL}", "-d", payload,
                            "https://backend.commanderspellbook.com/find-my-combos/"],
                           capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
        except Exception:
            time.sleep(2); continue
        if isinstance(d, dict) and "results" in d:
            return d["results"]
        time.sleep(2)
    raise SystemExit("Commander Spellbook find-my-combos failed after retries "
                     f"(last body: {r.stdout[:200]!r})")


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


# ============================================================ reporting
def worst_lines(names, scry, lands, accels, sims, rng, top=5):
    """Sources-model rows, worst first. Pure compute -- no printing, so a test
    can assert on the numbers instead of scraping stdout."""
    cand = {}
    for n in names:
        c = scry.get(n.lower())
        if not c or is_front_land(c) or has_land_back(c):
            continue
        for label, cost, mv in castable_faces(c):
            req = pips_from_cost(cost)
            if not req:
                continue
            turn = max(mv, len(req), 1)
            if turn > 7:
                continue
            cand.setdefault((turn, mv, tuple(sorted(req))), []).append(label)
    rows = []
    for (turn, mv, req), cards in cand.items():
        p = probability(lands, accels, 99, list(req), mv, turn, sims, rng)
        rows.append((p, turn, mv, req, sorted(set(cards))))
    rows.sort()
    return rows[:top] if top else rows


def commander_lines(cmdr, scry):
    """One play-sim line per commander -- a partner pair has two curves."""
    out = []
    for cn in as_cmdrs(cmdr):
        c = scry.get(cn.lower())
        if not c:
            continue
        out.append((f"{cn} on curve", int(front(c, "cmc", 0) or 0),
                    "".join(f"{{{x}}}" for x in
                            pips_from_cost(front(c, "mana_cost", "")))))
    return out


def analyse_mana(cmdr, entries, scry, sims, trials, seed=17, lines=None):
    """The whole section 6 measurement, as data. report_mana only prints it."""
    ncmdr = len(as_cmdrs(cmdr))
    names = flat(cmdr, entries)[ncmdr:]
    lands = build_land_profiles(names, scry)
    accels = build_accel_profiles(names, scry)
    v = verify(cmdr, entries, scry)
    rows = worst_lines(names, scry, lands, accels, sims, random.Random(seed))
    if lines is None:
        lines, seen = [], set()
        for p, turn, mv, req, cards in rows:
            key = (mv, tuple(req))
            if key in seen:
                continue
            seen.add(key)
            lines.append((f"{cards[0]} T{turn}", mv,
                          "".join("{%s}" % x for x in req)))
        lines += commander_lines(cmdr, scry)
    res = playsim_report(lands, accels, 99, lines, trials, random.Random(seed))
    return {"verify": v, "lands": lands, "accels": accels,
            "rows": rows, "lines": lines, "sim": res}


def report_mana(cmdr, entries, scry, sims, trials, seed=17, lines=None):
    a = analyse_mana(cmdr, entries, scry, sims, trials, seed, lines)
    v, accels, rows, lines, res = (a["verify"], a["accels"], a["rows"],
                                   a["lines"], a["sim"])

    print(f"\n=== MANA BASE ({v['lands']} front-face lands"
          f" + {v['mdfc_land_backs']} MDFC land-backs, "
          f"{len(v['truly_tapped'])} truly tapped) ===")
    for n, m in v["conditional_tapped"]:
        print(f"  conditional, not counted: {n}   [{m}]")
    for n in v["truly_tapped"]:
        print(f"  TRULY TAPPED: {n}")
    restricted = [a["name"] for a in accels if a.get("restricted")]
    print(f"  accelerants counted: {len([a for a in accels if not a.get('restricted')])}"
          f"  (restricted, excluded: {', '.join(restricted) if restricted else 'none'})")

    print("\n--- sources model (colour), worst lines ---")
    for p, turn, mv, req, cards in rows:
        pips = "".join("{%s}" % x for x in req)
        print(f"  T{turn} {pips:12} {p*100:5.1f}%   {', '.join(cards[:3])}")

    print(f"\n--- play simulation, {trials} trials ---")
    print(f"  {'line':44s} {'on play':>9} {'on draw':>9} {'baseline(any N on TN)':>22}")
    for label, mv, pipstr in lines:
        if label not in res["play"]["lines"]:
            continue
        a, turn = res["play"]["lines"][label]
        b, _ = res["draw"]["lines"][label]
        g1 = res["play"]["generic"][turn]
        g2 = res["draw"]["generic"][turn]
        print(f"  {label:44s} {a:8.1f}% {b:8.1f}%   {g1:7.1f}% / {g2:.1f}%")
    print("\n  Diagnosis: a line CLOSE to its baseline is a QUANTITY problem "
          "(no land swap will help).\n  A line FAR BELOW its baseline is a "
          "COLOUR problem (a filter land for that pip is the answer).")
    return res


def report_variants(cmdr, entries, scry, land_deltas, accel_deltas, trials, seed=17):
    """Sweep land count and accelerant count. Slow; opt-in."""
    names = flat(cmdr, entries)[len(as_cmdrs(cmdr)):]
    base_lands = build_land_profiles(names, scry)
    accels = build_accel_profiles(names, scry)
    accels = [a for a in accels if not a.get("restricted")]
    basic = next((p for p in base_lands if not p["tapped"] and p["colours"]), None)
    generic_rock = {"name": "generic rock", "kind": "accel", "colours": frozenset(),
                    "filter": None, "omni": None, "amount": 1, "cost": 2,
                    "tapped": False, "cond_tap": None, "restricted": False,
                    "creature": False, "mdfc": False}
    _cl = commander_lines(cmdr, scry)
    _, cmv, _cpips = _cl[0]
    creq = pips_from_cost(_cpips)
    print(f"\n=== VARIANTS SWEEP ({trials} trials) — commander line and generic baseline ===")
    print(f"  {'config':26s} {'cmdr on curve':>16} {'any N on turn N':>18}")
    for dl in land_deltas:
        for da in accel_deltas:
            if dl >= 0:
                lands = base_lands + [dict(basic) for _ in range(dl)]
            else:
                lands = list(base_lands)
                for _ in range(-dl):
                    drop = next((i for i, p in enumerate(lands)
                                 if not p["tapped"] and not p["filter"]
                                 and p.get("amount", 1) == 1
                                 and len(p["colours"]) == 1), None)
                    if drop is None:
                        break
                    lands.pop(drop)
            acc = accels + [dict(generic_rock) for _ in range(da)]
            rng = random.Random(seed)
            r = playsim_report(lands, acc, 99,
                               [("cmdr", cmv, "".join(f"{{{x}}}" for x in creq))],
                               trials, rng)
            a, turn = r["play"]["lines"]["cmdr"]
            b, _ = r["draw"]["lines"]["cmdr"]
            g1, g2 = r["play"]["generic"][turn], r["draw"]["generic"][turn]
            print(f"  {len(lands)} lands, {len(acc)} accel"
                  f"{'':<7} {a:6.1f}% / {b:5.1f}% {g1:9.1f}% / {g2:5.1f}%")


def report_own(cmdr, entries, scry):
    owned = load_collection()
    buckets = defaultdict(list)
    tot = 0.0
    for n in as_cmdrs(cmdr) + list(entries):
        if owned.get(n.lower(), 0) > 0:
            continue
        c = scry.get(n.lower())
        if not c:
            continue
        tl = c["type_line"]
        if "Basic Land" in tl:
            continue          # basics are NOT tracked in ManaBox; never a buy line
        if "Land" in tl.split("//")[0]:
            b = "Lands"
        elif "Equipment" in tl:
            b = "Equipment"
        elif "Creature" in tl.split("//")[0]:
            b = "Creatures"
        elif "Artifact" in tl:
            b = "Artifacts"
        elif "Enchantment" in tl:
            b = "Enchantments"
        else:
            b = "Instants / Sorceries"
        price = c.get("prices", {}).get("usd")
        buckets[b].append((n, price, c.get("edhrec_rank")))
        if price:
            tot += float(price)
    print("\n=== BUY LIST (absent from ManaBox_Collection.csv) ===")
    for b in ["Creatures", "Equipment", "Artifacts", "Enchantments",
              "Instants / Sorceries", "Lands"]:
        if b not in buckets:
            continue
        print(f"\n{b} ({len(buckets[b])})")
        for n, p, rk in sorted(buckets[b]):
            rks = f"EDHREC #{rk}" if rk else ""
            print(f"  (BUY) {n:34s} ${p if p else 'n/a':>7}  {rks}")
    print(f"\n  total listed USD (nulls excluded): ${tot:,.2f}")
    print("  Null usd (Reserved List / promo): re-query !\"Name\" with order=eur&unique=prints")


def deck_base_name(name):
    """Strip a trailing bracketed tag: 'Muldrotha [Bracket 3 Temp]' -> 'muldrotha'."""
    return re.sub(r"[\[\(][^\]\)]*[\]\)]", "", name or "").strip().lower()


def collapse_temps(use):
    """Section 2: a Temp is an alternative build of the SAME physical deck, so
    it does not compete for a card with its own main list. Counting both made
    every shared card look contended and turned an output into a phantom
    purchase line. Collapse a '[... Temp]' listing into the main it shares a
    base name with; a Temp with no main of its own stands alone.
    """
    mains = {deck_base_name(n) for n in use if "temp" not in n.lower()}
    out = {}
    for name, cards in use.items():
        if "temp" in name.lower() and deck_base_name(name) in mains:
            continue
        out[name] = cards
    return out


def report_contention(cmdr, entries, other_ids):
    owned = load_collection()
    use = {}
    for pid in other_ids:
        name, cmdrs, main = moxfield_deck(pid)
        use[name or pid] = set(k.lower() for k in list(main) + cmdrs)
        time.sleep(0.4)
    dropped = sorted(set(use) - set(collapse_temps(use)))
    use = collapse_temps(use)
    if dropped:
        print(f"\n  (collapsed into their main lists, not counted as separate "
              f"physical decks: {', '.join(dropped)})")
    print("\n=== CONTENTION (owned copies vs physical decks wanting the card) ===")
    hit = False
    for n in as_cmdrs(cmdr) + list(entries):
        o = owned.get(n.lower(), 0)
        if o == 0:
            continue
        others = [l for l, s in use.items() if n.lower() in s]
        if len(others) + 1 > o:
            hit = True
            print(f"  {n:30s} owned {o} | also in: {', '.join(sorted(others))}")
    if not hit:
        print("  none — every owned card here has enough copies")
    print("  (Contention is an OUTPUT. It never decides a slot.)")


def report_combos(cmdr, entries):
    res = spellbook(cmdr, entries)
    inc = res.get("included", [])
    almost = res.get("almostIncluded", [])
    deck = set(n.lower() for n in flat(cmdr, entries))
    print(f"\n=== COMMANDER SPELLBOOK ({time.strftime('%Y-%m-%d')}) ===")
    print(f"  in-deck combos: {len(inc)}")
    for v in inc:
        print("   *", " + ".join(u["card"]["name"] for u in v.get("uses", [])),
              "->", ", ".join(f["feature"]["name"] for f in v.get("produces", [])))
    print(f"  one card away: {len(almost)}")
    grp = defaultdict(list)
    for v in almost:
        us = [u["card"]["name"] for u in v.get("uses", [])]
        tmpl = [t["template"]["name"] for t in v.get("requires", [])]
        have = [u for u in us if u.lower() in deck]
        miss = [u for u in us if u.lower() not in deck]
        for h in have:
            grp[h].append((miss, len(us) + len(tmpl)))
    print("  grouped by the piece already in the deck:")
    for k, v in sorted(grp.items(), key=lambda x: -len(x[1])):
        twos = sorted({m[0] for m, sz in v if sz == 2 and len(m) == 1})
        print(f"    {k}: {len(v)}" + (f"   two-card: {', '.join(twos)}" if twos else ""))
    print("  Spellbook is a CANDIDATE GENERATOR. Verify every piece count against")
    print("  oracle text before believing it (otherPrerequisites is often empty).")


def report_diff(cmdr, entries, deck_id):
    """Section 3: changes are not real until imported, and a delta must be
    re-based on a fresh fetch before it is applied. This is that check."""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    name, live_cmdrs, live_main = moxfield_deck(deck_id)
    ol, ov, cc = diff_multiset(cmdr, entries, live_cmdrs, live_main)
    print(f"\n=== DIFF vs LIVE  (deck {deck_id}, '{name}', fetched {stamp}) ===")
    if cc:
        print(f"  COMMANDER DIFFERS: local {cc[0]} | live {cc[1]}")
    lt = len(as_cmdrs(cmdr)) + sum(entries.values())
    vt = len(live_cmdrs) + sum(live_main.values())
    print(f"  local {lt} cards | live {vt} cards")
    if not ol and not ov and not cc:
        print("  IDENTICAL -- the live list already matches this file.")
        return True
    for n, c in ov:
        print(f"  -{c} {n}      (in live, not in file)")
    for n, c in ol:
        print(f"  +{c} {n}      (in file, not in live)")
    print("  Paste as a delta only after confirming this is the base you built on.")
    return False


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


def report_calibrate(deck_ids, cache_path, sims, trials, user=None):
    """Regenerate the whole calibration table from LIVE decks in one pass.

    The table is a set of dated measurements, not a fact about a deck. It is
    wrong the moment a list changes, the moment the model changes, and it
    carries Monte Carlo noise besides. Regenerate it; never quote a stored row.
    """
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not deck_ids:
        deck_ids = [i for i, _n in moxfield_user_decks(user or "evansenter")]
    rows = []
    for did in deck_ids:
        try:
            name, cmdrs, main = moxfield_deck(did)
        except Exception as e:
            rows.append((did, f"FETCH FAILED: {e}", None)); continue
        if not cmdrs:
            continue
        cmdr = cmdrs
        entries = Counter(main)
        scry, nf = scry_fetch(flat(cmdr, entries), cache_path)
        if nf:
            print(f"  [{name}] Scryfall not found: {nf}")
        v = verify(cmdr, entries, scry)
        names = flat(cmdr, entries)[len(as_cmdrs(cmdr)):]
        lands = build_land_profiles(names, scry)
        accels = build_accel_profiles(names, scry)
        srows = worst_lines(names, scry, lands, accels, sims,
                            random.Random(17), top=1)
        lines = []
        for pr, turn, mv, req, cards in srows:
            lines.append((f"{cards[0]} T{turn}", mv,
                          "".join("{%s}" % x for x in req)))
        lines += commander_lines(cmdr, scry)
        res = playsim_report(lands, accels, 99, lines, trials, random.Random(17))

        worst = None
        for label, mv, pipstr in lines:
            if label not in res["play"]["lines"]:
                continue
            a, turn = res["play"]["lines"][label]
            g = res["play"]["generic"][turn]
            d = a - g
            if worst is None or a < worst[1]:
                worst = (label, a, res["draw"]["lines"][label][0], d,
                         "quantity" if d > -3.0 else "COLOUR")
        rows.append((name, v, worst))
        time.sleep(0.3)

    print(f"\n=== CALIBRATION (regenerated {stamp}) ===")
    print("  Monte Carlo: sources model %d sims, play sim %d trials, seed 17."
          % (sims, trials))
    print(f"  {'deck':34s} {'lands':>5} {'tap':>4} {'GC':>3}  worst line "
          "(on play / on draw, delta vs baseline)")
    for r in rows:
        if r[2] is None and not isinstance(r[1], dict):
            print(f"  {r[0][:34]:34s} {r[1]}")
            continue
        name, v, worst = r
        mb = f"{v['lands']}" + (f"+{v['mdfc_land_backs']}" if v["mdfc_land_backs"] else "")
        if worst is None:
            print(f"  {name[:34]:34s} {mb:>5} {len(v['truly_tapped']):>4} "
                  f"{len(v['game_changers']):>3}  (no coloured line)")
            continue
        label, a, b, d, diag = worst
        print(f"  {name[:34]:34s} {mb:>5} {len(v['truly_tapped']):>4} "
              f"{len(v['game_changers']):>3}  {label[:38]} — "
              f"{a:.1f}% / {b:.1f}%, {d:+.1f} ({diag})")
    print("\n  A line within ~3 points of its baseline is a QUANTITY problem and "
          "no land\n  swap will move it. Further below is a COLOUR problem and a "
          "filter land for\n  that pip is the answer. These rows are dated "
          "measurements: re-run, never quote.")
    return rows


# ============================================================ self-test
# Offline regression tests. No network, no collection file, no decklist.
# Every case below encodes a bug that ACTUALLY SHIPPED a wrong number.
# Run after any edit to this file, and before delivering it:  selftest

_FAILS = []


def _eq(label, got, want):
    if got != want:
        _FAILS.append(f"{label}: got {got!r}, want {want!r}")


def _raises(label, fn):
    try:
        fn()
    except AssertionError:
        return
    except Exception as e:
        _FAILS.append(f"{label}: raised {type(e).__name__}, want AssertionError")
        return
    _FAILS.append(f"{label}: did not raise")


def _raises_sysexit(label, fn):
    """Guards that must FAIL LOUDLY on a bad upstream response, not warn."""
    try:
        fn()
    except SystemExit:
        return
    except Exception as e:
        _FAILS.append(f"{label}: raised {type(e).__name__}, want SystemExit")
        return
    _FAILS.append(f"{label}: did not raise")


def _card(**kw):
    kw.setdefault("type_line", "Land")
    kw.setdefault("oracle_text", "")
    return kw


def _src(colours="", amount=1, filt=None, omni=None):
    return {"colours": frozenset(colours), "amount": amount,
            "filter": filt, "omni": omni}


def selftest():
    del _FAILS[:]

    # --- mana_amount -----------------------------------------------------
    # An "Add" clause lists ALTERNATIVES. Counting symbols across the whole
    # clause credited every dual with 2 mana and Jetmir's Garden with 3, which
    # inflated every play-simulation figure in a multicolour deck by ~15-25pts.
    for txt, want in [
        ("{T}: Add {R} or {G}.", 1),                       # any dual/shock/check
        ("{T}: Add {R}, {G}, or {W}.", 1),                 # Jetmir's Garden
        ("{T}: Add {C}{C}.", 2),                           # Ancient Tomb, Sol Ring
        ("{T}: Add {W}{U}.", 2),                           # Azorius Chancery (karoo)
        ("{T}: Add one mana of any color.", 1),            # Command Tower
        ("{T}: Add two mana of any one color.", 2),
        ("{T}: Add {G}.", 1),                              # basic
        ("{T}: Add {C}. {R/W}, {T}: Add {R}{R}, {R}{W}, or {W}{W}.", 2),  # filter
        ("", 1),
    ]:
        _eq(f"mana_amount({txt[:28]!r})", mana_amount(txt.lower()), want)

    # --- enters_tapped ---------------------------------------------------
    # Three classes, only one is a real cost. A classifier that greps
    # "enters tapped" flags all three; one that greps only "unless you control
    # a" flagged all six shocklands as unconditionally tapped. Note the
    # ORIGINAL-CASE text below: the function must lowercase before matching.
    for label, txt, want in [
        ("shock is conditional", "As Sacred Foundry enters, you may pay 2 life. If you "
                      "don't, it enters tapped.", (False, "you may pay 2 life")),
        ("battlebond", "Spire Garden enters tapped unless you have two or more "
                       "opponents.", (False, "unless you have two or more opponents")),
        ("checkland", "Rootbound Crag enters tapped unless you control a "
                      "Mountain or a Forest.", (False, "unless you control a")),
        ("lonely mountain (an)", "The Lonely Mountain enters tapped unless you "
                                 "control an Equipment.", (False, "unless you control an")),
        ("triome still truly tapped", "Jetmir's Garden enters tapped. Cycling {3}", (True, None)),
        ("basic", "{T}: Add {G}.", (False, None)),
    ]:
        _eq(f"tapped/{label}", enters_tapped(_card(oracle_text=txt), None), want)

    # The life figure VARIES. Hard-coding the shockland's 2 sent The Black Gate
    # to TRULY TAPPED, a wrong verdict that looked right and shipped in a
    # calibration table. VERBATIM Scryfall text below -- an earlier version of
    # this test fed the parser invented wording ("enters tapped unless you pay
    # 3 life"), which no printed card actually uses, so it proved nothing.
    black_gate = ("As The Black Gate enters, you may pay 3 life. If you don't, "
                  "it enters tapped.\n{T}: Add {B}.")
    _eq("tapped/Black Gate pays 3, still conditional",
        enters_tapped(_card(oracle_text=black_gate), None)[0], False)
    _eq("tapped/Black Gate marker is the matched text",
        enters_tapped(_card(oracle_text=black_gate), None)[1], "you may pay 3 life")
    # The whole Zendikar MDFC land-back cycle uses the same wording.
    mdfc_back = ("As this land enters, you may pay 3 life. If you don't, it "
                 "enters tapped.\n{T}: Add {B}.")
    for nm in ("Agadeem the Undercrypt", "Sea Gate Reborn",
               "Shatterskull the Hammer Pass", "Boggart Bog", "Soporific Springs"):
        _eq(f"tapped/{nm} is conditional",
            enters_tapped(_card(oracle_text=mdfc_back), None)[0], False)
    # Original case must still match -- the function lowercases before matching.
    _eq("tapped/original case still matches",
        enters_tapped(_card(oracle_text=black_gate.upper()), None)[0], False)

    # --- fetch_targets ---------------------------------------------------
    # produced_mana is EMPTY on a fetchland; a naive source count drops six.
    _eq("fetch/foothills",
        fetch_targets("search your library for a mountain or forest card"), {"R", "G"})
    _eq("fetch/prismatic vista",
        fetch_targets("search your library for a basic land card"),
        {"W", "U", "B", "R", "G"})
    _eq("fetch/not a fetch", fetch_targets("{t}: add {g}."), set())

    # --- DFC plumbing ----------------------------------------------------
    # power/toughness/mana_cost are ABSENT at top level on a DFC. A filter like
    # card.get('power','').isdigit() silently DROPS the card: Pantlaza's
    # creature power was reported as 148 when it is 155.
    mdfc = _card(type_line="Sorcery // Land",
                 card_faces=[{"type_line": "Sorcery", "power": None,
                              "mana_cost": "{X}{B}{B}{B}", "name": "Agadeem's Awakening"},
                             {"type_line": "Land", "oracle_text": "enters tapped "
                              "As this land enters, you may pay 3 life. If you don't, it enters tapped.", "name": "Agadeem, the Undercrypt"}])
    _eq("is_front_land/mdfc spell side", is_front_land(mdfc), False)
    _eq("has_land_back/mdfc", has_land_back(mdfc), True)
    _eq("front/mana_cost off face", front(mdfc, "mana_cost", ""), "{X}{B}{B}{B}")
    tdfc = _card(type_line="Creature — Dinosaur",
                 card_faces=[{"type_line": "Creature — Dinosaur", "power": "4",
                              "toughness": "4"},
                             {"type_line": "Creature — Phyrexian", "power": "7",
                              "toughness": "7"}])
    _eq("front/power off face", front(tdfc, "power"), "4")
    _eq("is_front_land/plain land", is_front_land(_card(type_line="Land — Forest")), True)
    _eq("has_land_back/plain land", has_land_back(_card(type_line="Land — Forest")), False)

    # --- pips_from_cost --------------------------------------------------
    _eq("pips/naya", pips_from_cost("{2}{R}{G}{W}"), ["R", "G", "W"])
    _eq("pips/X ignored", pips_from_cost("{X}{B}{B}{B}"), ["B", "B", "B"])
    _eq("pips/hybrid", pips_from_cost("{2}{R/W}"), ["RW"])
    _eq("pips/colourless", pips_from_cost("{4}"), [])

    # --- castable_faces --------------------------------------------------
    # Split cards carry a top-level cmc equal to the SUM of both halves --
    # right for the stack, wrong for "can I cast this on curve".
    split = _card(type_line="Instant // Sorcery", layout="split", cmc=10,
                  card_faces=[{"name": "Commit", "mana_cost": "{3}{U}"},
                              {"name": "Memory", "mana_cost": "{4}{U}{U}"}])
    _eq("castable_faces/split", sorted((n, mv) for n, _c, mv in castable_faces(split)),
        [("Commit", 4), ("Memory", 6)])
    _eq("castable_faces/normal",
        list(castable_faces(_card(type_line="Creature", cmc=5,
                                  mana_cost="{2}{R}{G}{W}", name="Pantlaza"))),
        [("Pantlaza", "{2}{R}{G}{W}", 5)])

    # --- castable / filter lands -----------------------------------------
    # A filter paired with a partner yields two pips OF ITS OWN TWO COLOURS,
    # not of whatever colour you happen to be measuring. Mystic Gate is W/U
    # and produces NO BLACK. On the Esper list this bug and the excluded-
    # accelerants bug nearly cancelled and hid each other.
    gate, plains, swamp = _src(filt="WU"), _src("W"), _src("B")
    _eq("castable/filter makes own pair", castable([gate, plains], ["W", "W"], 2), True)
    _eq("castable/filter makes no black", castable([gate, plains], ["B", "B"], 2), False)
    _eq("castable/lone filter taps for C", castable([gate], [], 1), True)
    _eq("castable/lone filter makes no pip", castable([gate], ["W"], 1), False)
    _eq("castable/no partner of its colours", castable([gate, swamp], ["W", "W"], 2), False)
    # Yavimaya/Urborg omni-typing applies to every land in play.
    _eq("castable/omni", castable([_src("R"), _src("G", omni="G")], ["G", "G"], 2), True)
    # Multi-mana sources count their full amount toward mv.
    _eq("castable/amount counts toward mv", castable([_src("C", amount=2)], [], 2), True)
    _eq("castable/insufficient total", castable([_src("R")], ["R"], 3), False)

    # --- hypergeometric --------------------------------------------------
    _eq("hypergeom/impossible", hypergeometric(3, 2, 7), 0.0)
    _eq("hypergeom/certain", round(hypergeometric(1, 99, 7, 99), 9), 1.0)

    # --- load_collection --------------------------------------------------
    # The obvious hand-rolled loader double-counts every non-DFC because both
    # keys are the same string. That shipped a contention report claiming two
    # copies of Deflecting Swat when one is owned.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                     encoding="utf-8-sig", newline="") as fh:
        fh.write("Name,Quantity\n"
                 "Sol Ring,2\n"
                 "Sol Ring,1\n"
                 "Agadeem's Awakening // Agadeem the Undercrypt,1\n")
        cpath = fh.name
    coll = load_collection(cpath)
    _eq("collection/sums quantities across printings", coll["sol ring"], 3)
    _eq("collection/no double count", coll["sol ring"], 3)
    _eq("collection/dfc full name", coll["agadeem's awakening // agadeem the undercrypt"], 1)
    _eq("collection/dfc front face", coll["agadeem's awakening"], 1)
    os.remove(cpath)

    # --- write_deck output contract --------------------------------------
    # A delivered .txt once did not contain a swap the message described, and
    # was imported to Moxfield in good faith. These asserts must RAISE, not warn.
    import io, contextlib
    tmp = tempfile.mkdtemp()
    good = Counter({f"Card {i}": 1 for i in range(99)})
    short = Counter({f"Card {i}": 1 for i in range(98)})

    def _quiet(fn):
        with contextlib.redirect_stdout(io.StringIO()):
            return fn()

    _eq("write_deck/valid 100",
        _quiet(lambda: write_deck("Cmdr", good, os.path.join(tmp, "a.txt"))), 100)
    _raises("write_deck/rejects 99 cards",
            lambda: _quiet(lambda: write_deck("Cmdr", short, os.path.join(tmp, "b.txt"))))
    _raises("write_deck/rejects missing add",
            lambda: _quiet(lambda: write_deck("Cmdr", good, os.path.join(tmp, "c.txt"),
                                              expect_adds=["Nonexistent Card"])))
    _raises("write_deck/rejects surviving cut",
            lambda: _quiet(lambda: write_deck("Cmdr", good, os.path.join(tmp, "d.txt"),
                                              expect_cuts=["Card 0"])))
    # Idempotency: writing twice must not duplicate. A swap script run twice
    # silently duplicated a card.
    _quiet(lambda: write_deck("Cmdr", good, os.path.join(tmp, "e.txt")))
    _eq("write_deck/idempotent",
        _quiet(lambda: write_deck("Cmdr", good, os.path.join(tmp, "e.txt"))), 100)

    # --- profile integration ---------------------------------------------
    scry = {
        "taiga": _card(name="Taiga", type_line="Land — Mountain Forest",
                       oracle_text="({T}: Add {R} or {G}.)", produced_mana=["R", "G"]),
        "ancient tomb": _card(name="Ancient Tomb", type_line="Land",
                              oracle_text="{T}: Add {C}{C}. Ancient Tomb deals 2 "
                                          "damage to you.", produced_mana=["C"]),
        "mystic gate": _card(name="Mystic Gate", type_line="Land",
                             oracle_text="{T}: Add {C}. {W/U}, {T}: Add {W}{W}, "
                                         "{W}{U}, or {U}{U}.", produced_mana=["C", "W", "U"]),
        "wooded foothills": _card(name="Wooded Foothills", type_line="Land",
                                  oracle_text="{T}, Pay 1 life, Sacrifice this land: "
                                              "Search your library for a Mountain or "
                                              "Forest card, put it onto the battlefield, "
                                              "then shuffle.", produced_mana=[]),
        "jetmir's garden": _card(name="Jetmir's Garden",
                                 type_line="Land — Mountain Forest Plains",
                                 oracle_text="Jetmir's Garden enters tapped. "
                                             "({T}: Add {R}, {G}, or {W}.) Cycling {3}",
                                 produced_mana=["R", "G", "W"]),
    }
    names = list(scry)
    profs = {p["name"]: p for p in build_land_profiles(names, scry)}
    _eq("profiles/count", len(profs), 5)
    _eq("profiles/dual amount is 1", profs["taiga"]["amount"], 1)
    _eq("profiles/triome amount is 1", profs["jetmir's garden"]["amount"], 1)
    _eq("profiles/ancient tomb amount is 2", profs["ancient tomb"]["amount"], 2)
    _eq("profiles/filter flagged", profs["mystic gate"]["filter"], "WU")
    _eq("profiles/filter amount is 1", profs["mystic gate"]["amount"], 1)
    _eq("profiles/fetch reaches typed lands",
        profs["wooded foothills"]["colours"], frozenset("RGW"))
    _eq("profiles/fetch never tapped", profs["wooded foothills"]["tapped"], False)
    _eq("profiles/triome truly tapped", profs["jetmir's garden"]["tapped"], True)

    # --- playsim sanity ---------------------------------------------------
    rng = random.Random(17)
    rounds = playsim([], [], 99, 3, False, 200, rng)
    _eq("playsim/no lands means no mana",
        max(sum(p.get("amount", 1) for p in s) for s in rounds[3]), 0)
    one = dict(profs["taiga"])
    rounds = playsim([one] * 99, [], 99, 3, False, 200, rng)
    _eq("playsim/all lands means N mana on turn N",
        min(sum(p.get("amount", 1) for p in s) for s in rounds[3]), 3)

    # --- roster walk ------------------------------------------------------
    # The roster is the section 6 enumeration; a missing or mis-keyed row is a
    # slot that never becomes a candidate, which is exactly the failure the
    # roster exists to prevent (six ABUR duals benched, rule never fired).
    _eq("pair_key/canonical order", pair_key("U", "W"), "WU")
    _eq("pair_key/already ordered", pair_key("B", "G"), "BG")
    _eq("identity_pairs/three colours",
        identity_pairs("BUG"), ["UB", "UG", "BG"])
    _eq("identity_pairs/mono has no pairs", identity_pairs("R"), [])
    _eq("identity_pairs/five colours", len(identity_pairs("WUBRG")), 10)
    for slot, table in PAIR_CYCLES:
        want = 6 if slot == "Horizon land" else 10
        _eq(f"roster/{slot} has {want} members", len(table), want)
        _eq(f"roster/{slot} keys canonical",
            sorted(table), sorted(pair_key(*k) for k in table))
        _eq(f"roster/{slot} members unique",
            len(set(table.values())), len(table))
    _eq("roster/horizon has no WU row", PAIR_CYCLES[3][1].get("WU"), None)
    _eq("roster/triple cycles cover ten shards", len(TRIPLE_CYCLES), 10)
    # status: IN beats owned, and benched is reported as benched, never as absent
    deck = {"bayou", "sunken ruins"}
    own = {"twilight mire": 1, "underground sea": 2, "bayou": 1}
    _eq("roster/in deck", roster_status("Bayou", deck, own), "IN")
    _eq("roster/owned but benched",
        roster_status("Twilight Mire", deck, own), "BENCH x1")
    _eq("roster/not owned", roster_status("Tundra", deck, own), "BUY")
    _eq("roster/case insensitive",
        roster_status("SUNKEN RUINS", deck, own), "IN")
    # a Sultai walk must generate the three filter lands of its pairs
    sultai = set(roster_names("BUG"))
    for n in ("Sunken Ruins", "Twilight Mire", "Flooded Grove", "Bayou",
              "Underground Sea", "Tropical Island", "Zagoth Triome"):
        _eq(f"roster/BUG generates {n}", n in sultai, True)
    _eq("roster/BUG excludes off-identity filter",
        "Mystic Gate" in sultai, False)
    _eq("roster/BUG keeps off-pair fetches",
        "Flooded Strand" in sultai, True)
    # mono-colour: no pair rows exist at all, but the identity-independent
    # and off-pair-fetch rows must still be generated (they are legal there).
    mono = set(roster_names("R"))
    _eq("roster/mono generates no filter land", "Graven Cairns" in mono, False)
    _eq("roster/mono keeps fetches", "Bloodstained Mire" in mono, True)
    _eq("roster/mono keeps legendary row", "Plaza of Heroes" in mono, True)

    # --- pips: colourless, Phyrexian, two-brid ----------------------------
    # {C} parsed to NOTHING, so four Forests "cast" Thought-Knot Seer and every
    # Eldrazi line in a colourless deck read as trivially castable.
    _eq("pips/colourless pip", pips_from_cost("{3}{C}"), ["C"])
    _eq("pips/double colourless", pips_from_cost("{C}{C}"), ["C", "C"])
    # {W/P} is payable with 2 life and is never a colour requirement; parsing
    # it as a hard pip understated Mental Misstep and Dismember.
    _eq("pips/phyrexian is free", pips_from_cost("{U/P}"), [])
    _eq("pips/phyrexian mixed", pips_from_cost("{1}{B/P}{B/P}"), [])
    # {2/W} is two-brid, payable with generic.
    _eq("pips/twobrid is generic", pips_from_cost("{2/W}{2/W}"), [])
    _eq("pips/snow is generic", pips_from_cost("{2}{S}"), [])
    forests = [_src("G")] * 4
    _eq("castable/forests cannot pay {C}",
        castable(forests, pips_from_cost("{3}{C}"), 4), False)
    _eq("castable/colourless source pays {C}",
        castable([_src("C", amount=2), _src("G"), _src("G")],
                 pips_from_cost("{3}{C}"), 4), True)
    _eq("castable/phyrexian off any source",
        castable([_src("G")], pips_from_cost("{U/P}"), 1), True)
    # A lone filter taps for {C} unaided -- it makes no coloured pip but it
    # does make colourless, which is what lets it cast Sol Ring on turn one.
    _eq("castable/lone filter pays {C}",
        castable([_src(filt="WU"), _src("G")], ["C"], 2), True)

    # --- profiles carry colourless production -----------------------------
    pscry = {
        "ancient tomb": _card(name="Ancient Tomb", type_line="Land",
                              oracle_text="{T}: Add {C}{C}.", produced_mana=["C"]),
        "sol ring": _card(name="Sol Ring", type_line="Artifact", cmc=1,
                          oracle_text="{T}: Add {C}{C}.", produced_mana=["C"]),
    }
    lp = {p["name"]: p for p in build_land_profiles(list(pscry), pscry)}
    ap_ = {p["name"]: p for p in build_accel_profiles(list(pscry), pscry)}
    _eq("profiles/land keeps colourless", "C" in lp["ancient tomb"]["colours"], True)
    _eq("profiles/accel keeps colourless", "C" in ap_["sol ring"]["colours"], True)

    # --- read_decklist -----------------------------------------------------
    # The front door for eight subcommands, previously untested. A partner deck
    # read as one commander is a silent 99-card deck whose second commander's
    # colours report as identity violations.
    def _dl(text):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(text)
            return fh.name

    f1 = _dl("# deck abc, fetched now\nAtraxa\n\n3 Forest\nSol Ring\n")
    c, e = read_decklist(f1)
    _eq("read/skips # header", c, ["Atraxa"])
    _eq("read/quantity parsed", e["Forest"], 3)
    _eq("read/bare line is one", e["Sol Ring"], 1)
    f2 = _dl("Tymna the Weaver\nThrasios, Triton Hero\n\n1 Sol Ring\n")
    c, e = read_decklist(f2)
    _eq("read/partner pair", c, ["Tymna the Weaver", "Thrasios, Triton Hero"])
    _eq("read/partner body intact", sum(e.values()), 1)
    f3 = _dl("Magda, Brazen Outlaw\n1 Sol Ring\n2 Mountain\n")
    c, e = read_decklist(f3)
    _eq("read/no blank line falls back", c, ["Magda, Brazen Outlaw"])
    _eq("read/fallback body", sum(e.values()), 3)
    for f in (f1, f2, f3):
        os.remove(f)

    # --- parse_moxfield ----------------------------------------------------
    # Highest blast radius in the file: a v3 shape change would yield a
    # plausible partial deck and nothing else would notice.
    fixture = {"name": "Test Deck", "boards": {
        "commanders": {"cards": {"aa1": {"quantity": 1, "card": {"name": "Tymna the Weaver"}}}},
        "partners": {"cards": {"bb2": {"quantity": 1, "card": {"name": "Thrasios, Triton Hero"}}}},
        "mainboard": {"cards": {"cc3": {"quantity": 1, "card": {"name": "Sol Ring"}},
                                "dd4": {"quantity": 9, "card": {"name": "Island"}}}},
        "sideboard": {"cards": {"ee5": {"quantity": 1, "card": {"name": "Ignore Me"}}}}}}
    nm, cm, mn = parse_moxfield(fixture)
    _eq("moxfield/name", nm, "Test Deck")
    _eq("moxfield/commanders and partners", cm,
        ["Tymna the Weaver", "Thrasios, Triton Hero"])
    _eq("moxfield/quantity not row count", mn["Island"], 9)
    _eq("moxfield/sideboard excluded", "Ignore Me" in mn, False)
    _raises_sysexit("moxfield/no boards raises", lambda: parse_moxfield({"name": "x"}))

    # --- verify on a synthetic 100 ----------------------------------------
    # "24 lands plus 75 non-land" in a 100-card deck is missing the commander,
    # and that arithmetic has shipped in a primer header.
    def _real(name, tl, ci, cmc=1, **kw):
        d = {"name": name, "type_line": tl, "color_identity": list(ci),
             "cmc": cmc, "oracle_text": "", "legalities": {"commander": "legal"}}
        d.update(kw)
        return d

    vscry = {
        "tymna the weaver": _real("Tymna the Weaver", "Legendary Creature", "WB", 3),
        "thrasios, triton hero": _real("Thrasios, Triton Hero", "Legendary Creature", "GU", 2),
        "island": _real("Island", "Basic Land — Island", "", 0),
        "sol ring": _real("Sol Ring", "Artifact", "", 1),
        "agadeem's awakening": _real(
            "Agadeem's Awakening // Agadeem, the Undercrypt", "Sorcery // Land", "B", 3,
            card_faces=[{"type_line": "Sorcery", "mana_cost": "{X}{B}{B}{B}"},
                        {"type_line": "Land", "oracle_text": "As this land enters, you may pay 3 life. If you don't, it enters tapped."}]),
    }
    # A BASIC LAND has an EMPTY colour identity, so a Forest cannot test this.
    # Use a green spell: it is legal here only because Thrasios contributes G.
    # Truncating the commander list to the first entry makes it a violation --
    # exactly the silent failure a partner deck would hit.
    vscry["llanowar elves"] = _real("Llanowar Elves", "Creature — Elf", "G", 1)
    ventries = Counter({"Island": 90, "Sol Ring": 6, "Llanowar Elves": 1,
                        "Agadeem's Awakening": 1})
    vv = verify(["Tymna the Weaver", "Thrasios, Triton Hero"], ventries, vscry)
    _eq("verify/partners counted in total", vv["total"], 100)
    _eq("verify/front-face lands", vv["lands"], 90)
    _eq("verify/identity is the UNION of both commanders",
        [n for n, _ in vv["ci_violations"]], [])
    _eq("verify/mdfc land-backs separate", vv["mdfc_land_backs"], 1)
    _eq("verify/nonland excludes both commanders", vv["nonland"], 8)
    _eq("verify/green card legal under the union", "G" in
        {c for cn in ("tymna the weaver", "thrasios, triton hero")
         for c in vscry[cn]["color_identity"]}, True)
    _eq("verify/arithmetic closes",
        vv["total"], 2 + vv["lands"] + vv["nonland"])
    _eq("verify/partner identity is the union", vv["ci_violations"], [])

    # --- write_deck with two commanders -----------------------------------
    two = Counter({f"Card {i}": 1 for i in range(98)})
    _eq("write_deck/partner pair is 100",
        _quiet(lambda: write_deck(["Tymna the Weaver", "Thrasios, Triton Hero"],
                                  two, os.path.join(tmp, "p.txt"))), 100)
    rc, re_ = read_decklist(os.path.join(tmp, "p.txt"))
    _eq("write_deck/partner round-trips", rc,
        ["Tymna the Weaver", "Thrasios, Triton Hero"])
    _eq("write_deck/partner body round-trips", sum(re_.values()), 98)

    # --- playable_set ------------------------------------------------------
    # You sequence tapped lands onto EARLIER turns, so one is only stuck if
    # every land you hold is tapped.
    tap = {"tapped": True, "colours": frozenset("G"), "amount": 1,
           "filter": None, "omni": None}
    uns = {"tapped": False, "colours": frozenset("G"), "amount": 1,
           "filter": None, "omni": None}
    _eq("playable/all tapped loses one", len(playable_set([tap, tap])), 1)
    _eq("playable/one untapped keeps all", len(playable_set([tap, uns])), 2)
    _eq("playable/empty", playable_set([]), [])

    # --- determinism -------------------------------------------------------
    # Without this a refactor silently moves every reported number.
    dl = [dict(profs["taiga"]) for _ in range(20)]
    p1 = probability(dl, [], 99, ["R", "G"], 3, 3, 500, random.Random(4))
    p2 = probability(dl, [], 99, ["R", "G"], 3, 3, 500, random.Random(4))
    _eq("determinism/probability", p1, p2)
    s1 = playsim(dl, [], 99, 3, False, 100, random.Random(4))
    s2 = playsim(dl, [], 99, 3, False, 100, random.Random(4))
    _eq("determinism/playsim", [len(x) for x in s1], [len(x) for x in s2])

    # --- diff_multiset -----------------------------------------------------
    # lastUpdatedAtUtc moves on a description edit, so the multiset is the only
    # honest test of whether a delta's base is still the base.
    ol, ov, cc = diff_multiset("A", Counter({"Sol Ring": 1, "Island": 9}),
                               ["A"], Counter({"Sol Ring": 1, "Island": 8,
                                               "Swamp": 1}))
    _eq("diff/only local", ol, [("Island", 1)])
    _eq("diff/only live", ov, [("Swamp", 1)])
    _eq("diff/commander same", cc, None)
    ol, ov, cc = diff_multiset("A", Counter({"X": 1}), ["B"], Counter({"X": 1}))
    _eq("diff/identical body", (ol, ov), ([], []))
    _eq("diff/commander change flagged", cc, (["A"], ["B"]))

    # --- contention: a Temp is not a separate physical deck ---------------
    _eq("temp/base name strips tag",
        deck_base_name("Muldrotha [Bracket 3 Temp]"), "muldrotha")
    use = {"Muldrotha [Bracket 3]": {"x"}, "Muldrotha [Bracket 3 Temp]": {"x"},
           "Teval [B4]": {"x"}}
    _eq("temp/collapses into its main", sorted(collapse_temps(use)),
        ["Muldrotha [Bracket 3]", "Teval [B4]"])
    _eq("temp/orphan temp stands alone",
        sorted(collapse_temps({"Sauron [Temp]": {"x"}})), ["Sauron [Temp]"])

    # --- report -----------------------------------------------------------
    print(f"\n=== SELF-TEST: {len(_FAILS)} failures ===")
    for f in _FAILS:
        print("  FAIL  " + f)
    if not _FAILS:
        print("  all checks passed")
    return 1 if _FAILS else 0


# ============================================================ land roster
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
    q = owned.get(low, 0) or owned.get(low.split(" // ")[0], 0)
    return f"BENCH x{q}" if q else "BUY"


def report_roster(cmdr, entries, scry, cache_path=None):
    ci = set()
    for cn in as_cmdrs(cmdr):
        if scry.get(cn.lower()):
            ci |= set(scry[cn.lower()]["color_identity"])
    ident = "".join(c for c in WUBRG if c in ci)
    deck_names = {n.lower() for n in entries} | {c.lower() for c in as_cmdrs(cmdr)}
    owned = load_collection()
    names = roster_names(ident)
    scry2, nf = scry_fetch(names, cache_path)
    scry2.update(scry)

    print(f"\n=== ROSTER WALK: {' + '.join(as_cmdrs(cmdr))} ({ident}) ===")
    if nf:
        print(f"  *** ROSTER NAME NOT ON SCRYFALL: {nf} ***")
    bad = [n for n in names
           if scry2.get(n.lower())
           and set(scry2[n.lower()]["color_identity"]) - set(ident)]
    if bad:
        print(f"  *** OFF-IDENTITY, ILLEGAL HERE: {bad} ***")

    def price(n):
        c = scry2.get(n.lower()) or {}
        p = (c.get("prices") or {}).get("usd")
        return f"${p}" if p else "-"

    empty = []
    if not identity_pairs(ident):
        # Section 6: in a mono-colour identity the two-colour cycles are
        # ILLEGAL, not merely unnecessary (Sunbaked Canyon is RW, every filter
        # land is two-colour). Say so; do not silently omit the rows.
        print(f"  {len(PAIR_CYCLES)} two-colour cycles "
              f"({', '.join(s for s, _ in PAIR_CYCLES)}) are off-identity "
              f"and ILLEGAL in {ident} -- no pair rows to walk.")
        print("  Fetchlands and any-colour painlands are legal here and "
              "strictly worse than a basic without shuffle payoffs: "
              "walked and skipped.")
    for pk in identity_pairs(ident):
        print(f"\n  --- {pk} ---")
        for slot, table in PAIR_CYCLES:
            name = table.get(pk)
            if not name:
                print(f"  {slot:18s} {'(no such card)':30s}")
                continue
            st = roster_status(name, deck_names, owned)
            extra = "" if st == "IN" else f"   {price(name)}"
            print(f"  {slot:18s} {name:30s} {st}{extra}")
            if st != "IN" and slot in ("ABUR dual", "Shockland", "Fetchland",
                                       "Filter land", "Painland",
                                       "Battlebond land", "Horizon land"):
                empty.append((pk, slot, name, st))

    print("\n  --- off-pair fetchlands (reach one colour of the identity) ---")
    for pk, name in PAIR_CYCLES[2][1].items():
        if set(pk) & set(ident) and not set(pk) <= set(ident):
            st = roster_status(name, deck_names, owned)
            print(f"  {pk:18s} {name:30s} {st}"
                  + ("" if st == "IN" else f"   {price(name)}"))

    if ident in TRIPLE_CYCLES:
        print("\n  --- three-colour (tapped; only if the rider is real) ---")
        for name in TRIPLE_CYCLES[ident]:
            st = roster_status(name, deck_names, owned)
            print(f"  {'Triome/tri-land':18s} {name:30s} {st}"
                  + ("" if st == "IN" else f"   {price(name)}"))

    print("\n  --- identity-independent ---")
    for slot, name in ANY_COLOUR:
        st = roster_status(name, deck_names, owned)
        print(f"  {slot:18s} {name:30s} {st}"
              + ("" if st == "IN" else f"   {price(name)}"))

    print(f"\n  PREMIUM SLOTS NOT IN THE LIST: {len(empty)}")
    for pk, slot, name, st in empty:
        print(f"    {pk} {slot:18s} {name:30s} {st}")
    print("  Ownership routes the purchase; it never decides the slot.")
    return empty


# ============================================================ CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["fetch", "verify", "mana", "variants", "combos",
                                    "own", "contention", "moxfield", "write", "audit",
                                    "roster", "diff", "selftest", "calibrate"])
    ap.add_argument("target", nargs="?", default=None,
                    help="decklist path, or deck id for `moxfield`; unused by `selftest`")
    ap.add_argument("--cache", default="scry.json")
    ap.add_argument("--sims", type=int, default=8000)
    ap.add_argument("--trials", type=int, default=20000)
    ap.add_argument("--out", default=None)
    ap.add_argument("--decks", default="", help="comma-separated Moxfield ids")
    ap.add_argument("--lands", default="-2,0,2",
                    help="land count deltas, e.g. -2,0,2 (leading minus needs --lands=-2,0,2)")
    ap.add_argument("--accel", default="0,2", help="accelerant count deltas")
    ap.add_argument("--adds", default="")
    ap.add_argument("--cuts", default="")
    a = ap.parse_args()

    if a.cmd == "selftest":
        sys.exit(selftest())
    if a.cmd == "calibrate":
        report_calibrate([x for x in a.decks.split(",") if x],
                         a.cache, a.sims, a.trials, user=a.target)
        return
    if not a.target:
        ap.error(f"`{a.cmd}` needs a target")

    if a.cmd == "moxfield":
        name, cmdrs, main = moxfield_deck(a.target)
        print(f"# {name}  (fetched {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})")
        out = list(cmdrs) + [""]
        out += [f"{q} {n}" for n, q in sorted(main.items(), key=lambda x: x[0].lower())]
        header = (f"# {name}  (deck {a.target}, fetched "
                  f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})")
        text = header + "\n" + "\n".join(out) + "\n"
        if a.out:
            open(a.out, "w", encoding="utf-8").write(text)
            print(f"wrote {a.out}")
        else:
            print(text)
        return

    cmdr, entries = read_decklist(a.target)
    if not cmdr:
        ap.error(f"no commander line found in {a.target}")
    if a.cmd == "diff":
        ids = [x for x in a.decks.split(",") if x]
        if len(ids) != 1:
            ap.error("`diff` needs exactly one --decks <publicId>")
        sys.exit(0 if report_diff(cmdr, entries, ids[0]) else 2)
    scry, nf = scry_fetch(flat(cmdr, entries), a.cache)
    if nf:
        print("SCRYFALL NOT FOUND (front-face names only!):", nf)

    if a.cmd in ("verify", "audit"):
        v = verify(cmdr, entries, scry)
        print(f"\n=== VERIFY: {cmdr} ===")
        print(f"  {v['total']} cards = 1 commander + {v['nonland']} non-land "
              f"+ {v['lands']} lands  ({v['mdfc_land_backs']} MDFC land-backs)")
        print(f"  average non-land MV {v['avg_mv']:.2f}")
        print(f"  Game Changers ({len(v['game_changers'])}, Scryfall game_changer): "
              f"{v['game_changers']}")
        print(f"  illegal: {v['illegal'] or 'none'}")
        print(f"  colour identity violations: {v['ci_violations'] or 'none'}")
        if v["total"] != 100:
            print(f"  *** DECK IS {v['total']} CARDS, COMMANDER IS 100 ***")
    if a.cmd in ("mana", "audit"):
        report_mana(cmdr, entries, scry, a.sims, a.trials)
    if a.cmd in ("roster", "audit"):
        report_roster(cmdr, entries, scry, a.cache)
    if a.cmd == "variants":
        report_variants(cmdr, entries, scry,
                        [int(x) for x in a.lands.split(",")],
                        [int(x) for x in a.accel.split(",")], a.trials)
    if a.cmd in ("combos", "audit"):
        report_combos(cmdr, entries)
    if a.cmd in ("own", "audit"):
        report_own(cmdr, entries, scry)
    if a.cmd == "contention":
        report_contention(cmdr, entries, [x for x in a.decks.split(",") if x])
    if a.cmd == "write":
        write_deck(cmdr, entries, a.out or "final_deck.txt",
                   [x for x in a.adds.split(",") if x],
                   [x for x in a.cuts.split(",") if x])


if __name__ == "__main__":
    main()