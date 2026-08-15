"""The original in-file regression harness, moved verbatim. Superseded by tests/ in the next commit."""
import os
import random
from collections import Counter

from mtg_utils import *          # noqa: F401,F403 -- superseded by tests/ next commit

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
