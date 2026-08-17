"""The floor audit: what is IN the list that the population is not playing.

`ceiling` prices an addition. Nothing priced a CUT, so every cut was decided by
hand -- and by hand it proposed four in one session with the inclusion figure
pulled for none of them. Two of those four were at 75.5% and 64.5% under that
commander and were put back a day later.

The whole command turns on one distinction, and most of the cases below are
about it: EDHREC ranks the TOP of each cardlist and stops, so a card it does
not rank is of UNKNOWN inclusion, bounded by how deep that particular list
went. Each list stops somewhere different -- on the captured page Instants ran
to 5.1% and Creatures only to 5.8% because it hit the 50-row cap -- so a single
number for the whole page throws away most of what absence is worth.

Two ways that goes wrong, and there is a case for each:

  * rendering a bound as a figure, so "we did not look this deep" reads as
    "the population does not play this";
  * bounding against a cardlist that is a SELECTION rather than a type. "New
    Cards", "High Synergy Cards" and "Game Changers" filter on recency,
    synergy skew and the bracket list rather than on inclusion, and on the
    captured page they stop at 8.2%, 73.9% and 74.5%. Read as display floors
    they would report Sol Ring as abandoned. "Top Cards" is a real bound at
    68.7% and excluded because it is a uselessly weak one.

floor.rec.json is a real EDHREC commander page (thrasios-triton-hero-tymna-
the-weaver, captured 2026-08-16) projected down to the fields this path reads.
Its cardlist LENGTHS are the signal, exactly as ceiling.rec.json's 50-entry
Creatures list is: trimming any of them changes the floor being asserted.
"""
import json
import os
import subprocess

import pytest

from conftest import FIXTURES

REC = os.path.join(FIXTURES, "floor.rec.json")
TOP16 = os.path.join(FIXTURES, "ceiling.top16.json")
PARTNER = os.path.join(FIXTURES, "partner.txt")
PAIR = ["Tymna the Weaver", "Thrasios, Triton Hero"]


def _page():
    with open(REC, encoding="utf-8") as f:
        return list(json.load(f).values())[0]


def _partner(mm):
    cmdr, entries = mm.read_decklist(PARTNER)
    with open(os.path.join(FIXTURES, "partner.scry.json"), encoding="utf-8") as f:
        return cmdr, entries, json.load(f)


@pytest.fixture
def no_network(monkeypatch):
    """A cache key that does not match what the code asks for sends the suite
    to the live endpoint and every assertion still passes. `_no_network` in
    test_ceiling.py was written after exactly that; same guard here."""
    def boom(*a, **kw):
        raise AssertionError(
            "the offline suite tried to reach the network -- a fixture cache "
            "key probably does not match what the code asks for")
    monkeypatch.setattr(subprocess, "run", boom)


# --- reading the depths off the page ----------------------------------
def test_each_cardlist_has_its_own_display_floor(mm):
    """The premise of the whole command. If one number described the page,
    `floor` could report absence as a single bound and this module would not
    need to exist -- so the spread is asserted, not assumed."""
    f = mm.display_floors(_page())
    assert f["Instants"]["floor"] == pytest.approx(5.06, abs=0.01)
    assert f["Enchantments"]["floor"] == pytest.approx(5.34, abs=0.01)
    assert f["Sorceries"]["floor"] == pytest.approx(5.36, abs=0.01)
    assert f["Utility Artifacts"]["floor"] == pytest.approx(5.55, abs=0.01)
    assert f["Creatures"]["floor"] == pytest.approx(5.80, abs=0.01)
    assert f["Utility Lands"]["floor"] == pytest.approx(6.02, abs=0.01)
    # The captured page's own lengths, which are what set those floors.
    assert f["Instants"]["entries"] == 42
    assert f["Utility Artifacts"]["entries"] == 6


def test_the_floor_of_a_capped_list_is_where_the_cap_fell(mm):
    """Creatures came back at exactly 50 rows, so its floor says where EDHREC
    stopped printing, not where the population stopped playing. The report has
    to be able to say which of the two it is looking at."""
    f = mm.display_floors(_page())
    assert f["Creatures"]["entries"] == mm.PAGE_CAP
    assert f["Creatures"]["capped"] is True
    assert f["Instants"]["capped"] is False
    # And the capped list is the SHALLOWEST of the type lists here -- absence
    # from it is worth the least, which is the opposite of what a reader
    # would guess from it being the longest.
    types = ["Instants", "Sorceries", "Enchantments", "Utility Artifacts"]
    assert all(f["Creatures"]["floor"] > f[t]["floor"] for t in types)


def test_the_ranked_depth_counts_only_rows_that_carried_a_ratio(mm):
    """`floor` is measured over the rows with a ratio; `entries` and `capped`
    describe what the page displayed. They are different sets whenever a
    cardview comes back without one, so both are carried and the report
    quotes the one the bound actually rests on.

    Collapsing them would print "50 rows" as the evidence for a floor read
    off however many of those rows happened to be scoreable -- the one number
    in an unranked row a reader can check the bound against.
    """
    page = {"container": {"json_dict": {"cardlists": [{
        "header": "Instants",
        "cardviews": [
            {"name": "Swan Song", "num_decks": 5, "potential_decks": 10},
            {"name": "Mana Crypt"},
            {"name": "Chrome Mox", "num_decks": 5, "potential_decks": 0}]}]}}}
    f = mm.display_floors(page)["Instants"]
    assert f["entries"] == 3
    assert f["ranked"] == 1
    assert f["floor"] == pytest.approx(50.0)


def test_a_cardlist_with_no_ratios_is_dropped_not_floored_at_zero(mm):
    """A floor of 0.0 reads as "everything is below 0%" -- the strongest
    possible claim from the weakest possible evidence, and the same mistake
    parse_commander_page refuses to make on a cardview with no ratio."""
    page = {"container": {"json_dict": {"cardlists": [
        {"header": "Empty", "cardviews": []},
        {"header": "No ratios", "cardviews": [{"name": "Mana Crypt"}]},
        {"header": "Instants", "cardviews": [
            {"name": "Swan Song", "num_decks": 5, "potential_decks": 10}]}]}}}
    f = mm.display_floors(page)
    assert set(f) == {"Instants"}
    assert f["Instants"]["floor"] == pytest.approx(50.0)


# --- which cardlist is allowed to bound a card ------------------------
def test_a_card_is_bounded_by_the_list_for_its_own_type(mm):
    f = mm.display_floors(_page())
    b = mm.display_floor_bound("Instant", f)
    assert b["header"] == "Instants"
    assert b["floor"] == pytest.approx(5.06, abs=0.01)


def test_sorceries_is_not_spelled_sorcery(mm):
    """The header for Sorcery is "Sorceries", which does not contain the word
    "Sorcery" anywhere in it. A `type in header` test therefore bounds no
    sorcery on any page and does it silently -- every sorcery in the list
    comes back "no cardlist could have held it", which reads as a page
    problem rather than as a matching bug."""
    b = mm.display_floor_bound("Sorcery", mm.display_floors(_page()))
    assert b is not None, "no sorcery would ever be bounded"
    assert b["header"] == "Sorceries"


@pytest.mark.parametrize("header,depth", [
    ("New Cards", 8.21), ("Top Cards", 68.67),
    ("High Synergy Cards", 73.87), ("Game Changers", 74.47),
], ids=["selection/New Cards holds only recent printings",
        "selection/Top Cards holds only the head of the page",
        "selection/High Synergy Cards holds only what the commander skews",
        "selection/Game Changers holds only what the bracket list names"])
def test_a_selection_cardlist_never_bounds_anything(mm, header, depth):
    """THE case this feature can get catastrophically wrong.

    Three of these four filter on something that is not inclusion at all, so
    absence from one says nothing whatever; "Top Cards" is ranked on inclusion
    and is a real bound, excluded because at 68.7% it is a uselessly weak one
    that would win the weakest-bound rule against every type list. Their real
    depths on the captured page are the second parameter -- read as display
    floors they would put Sol Ring, at 96.6% inclusion, "below 74.5%" and rank
    it as the safest cut in the deck.

    Asserted two ways: the depth is real (so this is not testing a list that
    happens to be missing), and no card is ever bounded at it.
    """
    f = mm.display_floors(_page())
    assert f[header]["floor"] == pytest.approx(depth, abs=0.01)
    for type_line in ("Instant", "Sorcery", "Creature — Human",
                      "Artifact", "Enchantment", "Land"):
        b = mm.display_floor_bound(type_line, f)
        assert b is None or b["header"] != header, (type_line, header)


def test_where_two_lists_could_hold_a_card_the_weaker_bound_wins(mm):
    """An Artifact Creature is a creature to EDHREC and a Sorcery // Land is
    filed under Lands, but nothing in the payload says which face a page
    filed a card by. Guessing turns a filing convention into a claim about
    the card, so the highest floor -- the weakest statement -- is taken.
    """
    floors = {"Creatures": {"header": "Creatures", "entries": 50,
                            "floor": 15.1, "capped": True},
              "Mana Artifacts": {"header": "Mana Artifacts", "entries": 16,
                                 "floor": 5.4, "capped": False}}
    b = mm.display_floor_bound("Artifact Creature — Golem", floors)
    assert b["header"] == "Creatures"
    assert b["floor"] == pytest.approx(15.1)
    # ...and a plain rock is bounded tightly, so the rule above is doing
    # something rather than always answering "Creatures".
    assert mm.display_floor_bound("Artifact", floors)["header"] == "Mana Artifacts"


def test_a_modal_card_is_bounded_by_every_face(mm):
    """The one comparison here that does NOT reduce to the front face.

    Agadeem's Awakening is `Sorcery // Land — Cave` and EDHREC files it under
    Lands. Bounded on its front alone it would be quoted against the
    Sorceries floor, which is a tighter claim than the page supports.

    The type line is verbatim Scryfall text, from this repo's own partner
    fixture cache.
    """
    f = mm.display_floors(_page())
    b = mm.display_floor_bound("Sorcery // Land — Cave", f)
    assert b["header"] == "Utility Lands"
    assert b["floor"] > f["Sorceries"]["floor"]


def test_a_type_the_page_never_ranked_gets_no_bound_at_all(mm):
    """None, not a number and not a blank. "The page ranked no list this card
    could be on" is a different statement from "below the floor", and only one
    of them is evidence for a cut."""
    floors = {"Instants": {"header": "Instants", "entries": 42,
                           "floor": 5.06, "capped": False}}
    assert mm.display_floor_bound("Creature — Human Wizard", floors) is None


# --- the audit --------------------------------------------------------
def _audit(mm, **kw):
    cmdr, entries, scry = _partner(mm)
    return mm.floor_audit(cmdr, entries, *_rows_and_floors(mm), scry, **kw)


def _rows_and_floors(mm):
    page = _page()
    rows, _capped = mm.parse_commander_page(page)
    return rows, mm.display_floors(page)


def test_lands_are_excluded_rather_than_scored(mm):
    """EDHREC's land data reflects a budget population, so inclusion is the
    wrong instrument for a land; `roster` is the right one and already walks
    every slot. Excluded, not silently absent -- the count is reported."""
    a = _audit(mm)
    scored = {r["name"] for r in a["below"] + a["above"]}
    scored |= {u["name"] for u in a["unranked"]}
    assert a["lands"], "the partner fixture runs lands"
    assert "Command Tower" in a["lands"]
    assert not (scored & set(a["lands"]))


def test_the_commander_is_never_a_cut_candidate(mm):
    a = _audit(mm)
    named = {r["name"] for r in a["below"] + a["above"]} | \
            {u["name"] for u in a["unranked"]} | set(a["lands"])
    for c in PAIR:
        assert c not in named


def test_every_card_lands_in_exactly_one_group(mm):
    """A card in no group is a card the report neither prints nor counts, and
    a shorter table reads as less work to do. floor_audit asserts this
    itself; the case pins the arithmetic the report prints from."""
    cmdr, entries, scry = _partner(mm)
    a = _audit(mm)
    c = a["counts"]
    # Derived from the DECKLIST, not by re-adding the audit's own figures.
    # Summing c["lands"] + c["below"] + ... and comparing it to c["cards"]
    # compares one loop against its own arithmetic and cannot fail; this
    # compares the audit against the file it was handed.
    want = sum(q for n, q in entries.items()
               if mm.front_name(n).lower() not in
               {mm.front_name(x).lower() for x in mm.as_cmdrs(cmdr)})
    assert c["cards"] == want
    assert (c["lands"] + c["below"] + c["above"] + c["unranked"]
            + c["unresolved"]) == want
    assert c["nonland"] == c["below"] + c["above"] + c["unranked"]


def test_the_counts_are_cards_and_reconcile_with_verify(mm):
    """The figures are printed under a [checked] marker, which reads as "this
    reconciles with the deck" -- so it has to.

    `entries` is a Counter and every other command here counts the quantity:
    `verify` sums it to reach 100 and `deck_skeleton` asserts against that
    total. Counted by distinct NAME instead, the partner fixture's four
    duplicate basics dropped out of both the total and the land count --
    "94 cards ... 34 lands" against verify's "100 cards = 2 commanders + 60
    non-land + 38 lands" on the same file. The non-land half agreed exactly,
    which is what made it hard to see rather than easy.

    Asserted against verify's own numbers rather than against literals, so
    the two cannot drift apart without this failing.
    """
    cmdr, entries, scry = _partner(mm)
    v = mm.verify(cmdr, entries, scry)
    c = _audit(mm)["counts"]
    assert c["cards"] + len(mm.as_cmdrs(cmdr)) == v["total"]
    assert c["lands"] == v["lands"]
    assert c["nonland"] == v["nonland"]
    # And the thing that made the bug invisible: distinct names really is a
    # different number here, so this is not asserting two spellings of one.
    assert len(a_lands := _audit(mm)["lands"]) < c["lands"], a_lands


def test_two_decklist_lines_for_one_card_keep_both_quantities(mm):
    """`Agadeem's Awakening` and `Agadeem's Awakening // Agadeem, the
    Undercrypt` reduce to one front face and so to one row. The second line's
    copies must be added to that row, not dropped with the duplicate name --
    losing them is the same failure as losing the duplicate basics, one layer
    down."""
    short = "Agadeem\u2019s Awakening"
    full = short + " // Agadeem, the Undercrypt"
    scry = {short.lower(): {"type_line": "Sorcery // Land \u2014 Cave"}}
    a = mm.floor_audit("Cmdr", {short: 2, full: 3}, [], {}, scry)
    assert len(a["unranked"]) == 1
    assert a["unranked"][0]["qty"] == 5
    assert a["counts"]["cards"] == 5
    # And the row prints under the FULL spelling. Taking whichever the loop
    # reached first took whichever sorted first, and the front face is a
    # PREFIX of the full name, so the short form always won -- the exact
    # spelling the row comment says a reader cannot search their list for.
    assert a["unranked"][0]["name"] == full


def test_the_bar_splits_ranked_rows_and_nothing_else(mm):
    a = _audit(mm, threshold=50.0)
    assert a["below"] and a["above"]
    assert all(r["inclusion"] < 50.0 for r in a["below"])
    assert all(r["inclusion"] >= 50.0 for r in a["above"])


def test_a_high_inclusion_card_in_the_list_is_reported_not_dropped(mm):
    """The incident, in miniature. Two cards at 75.5% and 64.5% were proposed
    as cuts because nothing put a number beside them. A row above the bar is
    not a finding, but it has to be FINDABLE -- omitted, its absence from the
    table is indistinguishable from "safe to cut"."""
    a = _audit(mm, threshold=50.0)
    by = {r["name"]: r for r in a["above"]}
    assert "Sol Ring" in by
    assert by["Sol Ring"]["inclusion"] > 90.0


def test_an_unranked_card_carries_a_bound_and_never_a_percentage(mm):
    a = _audit(mm)
    assert a["unranked"]
    by = {u["name"]: u for u in a["unranked"]}
    # An instant the page stopped short of, bounded against Instants -- not
    # against the deepest list on the page and not at 0%.
    assert by["Negate"]["bound"]["header"] == "Instants"
    assert "inclusion" not in by["Negate"]
    for u in a["unranked"]:
        assert "inclusion" not in u, u["name"]


def test_ordering_is_ascending_so_the_safest_cut_is_first(mm):
    a = _audit(mm)
    assert [r["inclusion"] for r in a["below"]] == \
        sorted(r["inclusion"] for r in a["below"])
    assert [r["inclusion"] for r in a["above"]] == \
        sorted(r["inclusion"] for r in a["above"])
    bounded = [u for u in a["unranked"] if u["bound"]]
    assert [u["bound"]["floor"] for u in bounded] == \
        sorted(u["bound"]["floor"] for u in bounded)


def test_sorting_by_synergy_is_also_ascending(mm):
    """Ascending, not descending as in `ceiling`: the most NEGATIVE synergy is
    the most off-plan card, which is the end of the axis a cut list wants."""
    a = _audit(mm, sort="synergy")
    syn = [r["synergy"] for r in a["below"] if r["synergy"] is not None]
    assert syn == sorted(syn)
    assert syn[0] < 0 < syn[-1], "the fixture should span zero synergy"


def test_a_row_with_no_synergy_sorts_last_rather_than_at_zero(mm):
    """Zero is a MEASURED synergy -- what a card played at the same rate
    everywhere scores -- so an unknown floated through the middle of the
    table on a 0.0 it was never measured at is a specific wrong claim. Sorted
    last, because "we do not know" is not evidence for a cut."""
    rows = [{"name": "Known Low", "num_decks": 1, "potential_decks": 100,
             "inclusion": 1.0, "synergy": -0.5, "cardlist": "Instants"},
            {"name": "Unknown", "num_decks": 2, "potential_decks": 100,
             "inclusion": 2.0, "synergy": None, "cardlist": "Instants"},
            {"name": "Known High", "num_decks": 3, "potential_decks": 100,
             "inclusion": 3.0, "synergy": 0.5, "cardlist": "Instants"}]
    names = ("Known Low", "Unknown", "Known High")
    scry = {n.lower(): {"type_line": "Instant"} for n in names}
    a = mm.floor_audit("Cmdr", {n: 1 for n in names}, rows, {}, scry,
                       threshold=50.0, sort="synergy")
    assert [r["name"] for r in a["below"]] == ["Known Low", "Known High",
                                               "Unknown"]


# --- the source distinction -------------------------------------------
def test_an_edhtop16_card_the_source_never_ranked_is_a_measured_zero(mm):
    """The opposite rule from EDHREC, and it has to be, because edhtop16
    counts WHOLE decklists. A card it does not rank appeared in zero of them,
    which is a real 0% with a real denominator -- bounding it instead would
    understate the one source that can actually say "nobody plays this"."""
    with open(TOP16, encoding="utf-8") as f:
        rows, n = mm.parse_edhtop16(list(json.load(f).values())[0])
    cmdr, entries, scry = _partner(mm)
    a = mm.floor_audit(cmdr, entries, rows, {}, scry, threshold=50.0,
                       exhaustive=True, sample=n)
    assert a["unranked"] == [], "an exhaustive source leaves nothing unranked"
    zeros = [r for r in a["below"] if r["inclusion"] == 0.0]
    assert zeros
    for r in zeros:
        assert r["num_decks"] == 0
        # The sample the zero came from, printed beside it. At six entries a
        # 0% is a much weaker statement than at six hundred.
        assert r["potential_decks"] == n


def test_the_same_card_is_bounded_on_edhrec_and_zeroed_on_edhtop16(mm):
    """The two rules side by side on one card, so neither can quietly become
    the other. Reading edhtop16's convention onto EDHREC invents a 0% for
    every card the page merely stopped short of."""
    rows = [{"name": "Sol Ring", "num_decks": 6, "potential_decks": 6,
             "inclusion": 100.0, "synergy": None, "cardlist": "x"}]
    floors = {"Instants": {"header": "Instants", "entries": 42,
                           "floor": 5.06, "capped": False}}
    entries = {"Sol Ring": 1, "Negate": 1}
    scry = {"sol ring": {"type_line": "Artifact"},
            "negate": {"type_line": "Instant"}}

    rec = mm.floor_audit("Cmdr", entries, rows, floors, scry)
    assert [u["name"] for u in rec["unranked"]] == ["Negate"]
    assert rec["below"] == []

    top = mm.floor_audit("Cmdr", entries, rows, {}, scry, exhaustive=True)
    assert top["unranked"] == []
    assert [(r["name"], r["inclusion"]) for r in top["below"]] == [("Negate", 0.0)]


# --- the report -------------------------------------------------------
def _run(mm, **kw):
    import io
    from contextlib import redirect_stdout
    cmdr, entries, scry = _partner(mm)
    buf = io.StringIO()
    with redirect_stdout(buf):
        a = mm.report_floor(cmdr, entries, scry, **kw)
    return a, buf.getvalue()


def test_the_report_prints_a_bound_as_a_bound(mm, no_network):
    """The acceptance criterion. A card absent from a cardlist is of unknown
    inclusion; printing it as 0%, or as a blank cell, is a number the tool
    could not have retrieved."""
    a, out = _run(mm, rec_cache=REC)
    assert "FLOOR vs EDHREC" in out
    assert "<=5.1%" in out
    assert "display floor" in out
    assert "0.0%" not in out
    assert a["unranked"]


def test_the_report_names_the_list_each_bound_came_from(mm, no_network):
    """A bound with no list beside it is unfalsifiable: the reader cannot see
    that a creature's 5.8% is a 50-row cap and an instant's 5.1% is not."""
    _a, out = _run(mm, rec_cache=REC)
    assert "'Instants' display floor" in out
    assert "'Creatures' display floor" in out
    assert "at the 50-row cap" in out


def test_the_report_prints_the_rows_above_the_bar(mm, no_network):
    """See test_a_high_inclusion_card_in_the_list_is_reported_not_dropped:
    counted away, a row above the bar is indistinguishable from a row that was
    never considered, and the reader learns that absence means "cut it"."""
    _a, out = _run(mm, rec_cache=REC)
    assert "AT OR ABOVE THE BAR" in out
    assert "NOT cut candidates" in out
    assert "Sol Ring" in out


def test_the_report_prints_no_bound_as_a_question_mark(mm, no_network):
    """A page that ranked no list a card could be on says NOTHING about it,
    and that has to render as neither a number nor an empty cell -- an empty
    cell in a column of "<=5.1%" reads as a smaller bound, which is the
    strongest possible claim from no evidence at all.

    Driven off ceiling.rec.json, which carries three cardlists rather than
    fourteen, so every instant and sorcery in the list is unbounded. That the
    two fixtures disagree here IS the point: how much absence is worth is a
    property of the page fetched, not of the card.
    """
    _a, out = _run(mm, rec_cache=os.path.join(FIXTURES, "ceiling.rec.json"))
    assert "no ranked cardlist on this page could have held it" in out
    assert "      ?  no ranked cardlist" in out


def _run_synthetic(mm, tmp_path, cardlists, entries, scry, **kw):
    """Drive report_floor over a hand-built page and a hand-built list.

    The committed fixture is a real page and a real deck, which is what makes
    it worth snapshotting -- and it is exactly why it cannot exercise a page
    shaped wrongly, or a name longer than any card in it.
    """
    import io
    from contextlib import redirect_stdout
    cache = os.path.join(str(tmp_path), "synthetic.json")
    with open(cache, "w", encoding="utf-8") as f:
        json.dump({"commanders/cmdr":
                   {"container": {"json_dict": {"cardlists": cardlists}}}}, f)
    buf = io.StringIO()
    with redirect_stdout(buf):
        mm.report_floor("Cmdr", entries, scry, cache, **kw)
    return buf.getvalue()


def test_the_report_quotes_the_ranked_depth_not_the_displayed_count(
        mm, no_network, tmp_path):
    """The bound rests on the rows that carried a ratio, so that is the number
    printed beside it. Quoting the displayed count would hand the reader a
    larger number as the one piece of evidence they can check."""
    out = _run_synthetic(
        mm, tmp_path,
        [{"header": "Instants", "cardviews": [
            {"name": "Swan Song", "num_decks": 5, "potential_decks": 10},
            {"name": "Fierce Guardianship", "num_decks": 4,
             "potential_decks": 10},
            {"name": "Mana Crypt"}, {"name": "Mox Diamond"}]}],
        {"Negate": 1}, {"negate": {"type_line": "Instant"}})
    assert "(2 ranked rows" in out
    assert "4 ranked" not in out


def test_a_single_row_cardlist_is_not_pluralised(mm, no_network, tmp_path):
    """Reachable on the very page this repo captured: Battles came back with
    exactly one row, at 5.44%. Any deck running a battle would read "below the
    'Battles' display floor (1 ranked rows)". It stays out of the committed
    snapshots only because partner.txt runs no battle."""
    out = _run_synthetic(
        mm, tmp_path,
        [{"header": "Battles", "cardviews": [
            {"name": "Invasion of Ikoria", "num_decks": 5,
             "potential_decks": 92}]}],
        {"Invasion of Alara": 1},
        {"invasion of alara": {"type_line": "Battle — Siege"}})
    assert "(1 ranked row)" in out
    assert "1 ranked rows" not in out


def _fifty(mm):
    return [{"name": f"Card {i}", "num_decks": 50 - i, "potential_decks": 100}
            for i in range(mm.PAGE_CAP)]


def test_a_capped_selection_list_gets_no_cap_note(mm, no_network, tmp_path):
    """`capped` carries every capped cardlist on the page because that is what
    `ceiling` needs. Here a selection list bounds nothing, so a caveat about
    "its floor" would sit under a table in which no row was measured against
    it -- and the captured page has Top Cards at 10 rows, so no snapshot shows
    this."""
    out = _run_synthetic(
        mm, tmp_path,
        [{"header": "Top Cards", "cardviews": _fifty(mm)},
         {"header": "Instants", "cardviews": _fifty(mm)}],
        {"Negate": 1}, {"negate": {"type_line": "Instant"}})
    assert "'Instants' came back at the" in out
    assert "Top Cards" not in out


def test_a_cap_note_only_fires_for_a_floor_a_printed_row_rests_on(
        mm, no_network, tmp_path):
    """The note says "its floor is where the cap fell", so it has to be about
    a floor some row was actually bounded by. Filtering to cardlists that
    COULD bound this card's type is too weak: a deck whose creatures all
    happen to be ranked gets a caveat about the Creatures floor under a table
    where no row rests on it.

    Here Swan Song is IN the list and ranked, so nothing is bounded against
    Instants, while the enchantment is.
    """
    out = _run_synthetic(
        mm, tmp_path,
        [{"header": "Instants", "cardviews": _fifty(mm)},
         {"header": "Enchantments", "cardviews": _fifty(mm)}],
        {"Card 0": 1, "Propaganda": 1},
        {"card 0": {"type_line": "Instant"},
         "propaganda": {"type_line": "Enchantment"}})
    assert "'Enchantments' came back at the" in out
    assert "'Instants' came back at the" not in out


def test_one_header_capped_twice_prints_its_note_once(mm, no_network, tmp_path):
    """parse_commander_page appends to `capped` per CARDLIST while
    display_floors keys per HEADER, so a page carrying one header twice puts
    the string in `capped` twice and printed the caveat twice."""
    out = _run_synthetic(
        mm, tmp_path,
        [{"header": "Instants", "cardviews": _fifty(mm)},
         {"header": "Instants", "cardviews": _fifty(mm)}],
        {"Negate": 1}, {"negate": {"type_line": "Instant"}})
    assert out.count("'Instants' came back at the") == 1


def test_a_name_longer_than_the_column_is_not_truncated(mm, no_network,
                                                        tmp_path):
    """Any fixed width cuts some name down to something that matches nothing
    the reader can search for, and picking one by eye got it wrong: 44 was
    chosen to fit the 46-character `Agadeem's Awakening // Agadeem, the
    Undercrypt` and truncated it. The fixtures cannot catch that -- partner.txt
    spells its MDFC with the front face only.

    Both names here are verbatim, from this repo's own fixture caches.
    """
    long_name = "Shatterskull Smashing // Shatterskull, the Hammer Pass"
    agadeem = "Agadeem’s Awakening // Agadeem, the Undercrypt"
    out = _run_synthetic(
        mm, tmp_path,
        [{"header": "Instants", "cardviews": [
            {"name": "Swan Song", "num_decks": 5, "potential_decks": 100}]}],
        {long_name: 1, agadeem: 1, "Negate": 1},
        {long_name.lower(): {"type_line": "Sorcery // Land"},
         agadeem.lower(): {"type_line": "Sorcery // Land — Cave"},
         "negate": {"type_line": "Instant"}})
    assert long_name in out
    assert agadeem in out
    # And the column still lines up under its heading, which is the half a
    # padding-only format spec does NOT give for free: `{name:44s}` pads a
    # short name but never truncates a long one, so a name past the width
    # silently shoves its own row's columns right and the table goes ragged
    # while every name is still fully printed. Measured against the header,
    # so this fails on a fixed width without depending on what it is.
    lines = out.splitlines()
    head = next(l for l in lines if l.strip().startswith("card "))
    want = head.index("what the page shows")
    rows = [l for l in lines
            if "display floor" in l or "no ranked cardlist" in l]
    assert len(rows) == 3, rows
    for l in rows:
        col = l.index("below the") if "display floor" in l \
            else l.index("no ranked cardlist")
        assert col == want, (col, want, l)


def test_a_repeated_card_prints_its_quantity(mm, no_network, tmp_path):
    """The counts beside every heading are CARDS, so a block headed (4) over a
    single row would otherwise be unexplained. Written as a decklist line,
    which is the form the reader is holding -- and absent entirely at one
    copy, so an ordinary singleton list is unchanged."""
    out = _run_synthetic(
        mm, tmp_path,
        [{"header": "Sorceries", "cardviews": [
            {"name": "Swan Song", "num_decks": 5, "potential_decks": 100}]}],
        {"Dragon's Approach": 4, "Negate": 1},
        {"dragon's approach": {"type_line": "Sorcery"},
         "negate": {"type_line": "Instant"}})
    assert "4 Dragon's Approach" in out
    assert "  Negate" in out and "1 Negate" not in out
    assert "NOT RANKED ON THIS PAGE (5)" in out
    assert "5 cards (commanders aside) = 0 lands + 0 below + 5 unranked" in out


def test_an_unresolved_name_is_counted_in_cards_like_everything_else(
        mm, no_network, tmp_path):
    """The identity line counts cards; this line counted distinct names. With
    `3 Bogus Card` in the list the two disagreed one line apart -- "+ 3
    unresolved   [checked]" and then "1 card in no group". Same units mismatch
    as the distinct-names bug, and nothing reached this branch before."""
    out = _run_synthetic(
        mm, tmp_path,
        [{"header": "Instants", "cardviews": [
            {"name": "Swan Song", "num_decks": 5, "potential_decks": 100}]}],
        {"Bogus Card": 3, "Negate": 1}, {"negate": {"type_line": "Instant"}})
    assert "+ 3 unresolved   [checked]" in out
    assert "3 cards in no group at all" in out
    assert "1 card in no group" not in out
    # Rendered as the decklist line it came from, like every other row.
    assert "3 Bogus Card" in out


def test_a_fractional_bar_is_printed_unrounded(mm, no_network):
    """--bar is a float. Rounded to `.0f` for printing, `--bar 47.5` announced
    "bar is 48% inclusion" and then filed a 47.1% row under BELOW THE BAR --
    below the bar it was measured against, above the bar the report named."""
    a, out = _run(mm, rec_cache=REC, threshold=47.5)
    assert "bar is 47.5% inclusion" in out
    assert "48%" not in out
    below = {r["name"]: r["inclusion"] for r in a["below"]}
    assert below["An Offer You Can't Refuse"] < 47.5


def test_the_report_says_lands_are_excluded(mm, no_network):
    _a, out = _run(mm, rec_cache=REC)
    assert "LANDS ARE EXCLUDED" in out
    assert "roster" in out
    assert "EDHREC land data reflects a budget population" in out


def test_the_lands_caveat_does_not_cite_edhrec_under_cedh(mm, no_network):
    """38 of 98 cards drop out of a --cedh run, and the reason printed for it
    was a fact about the OTHER source: edhtop16 counts tournament decklists,
    where a land's inclusion is as measured as anything else. Same shape as
    the two absence conventions this feature keeps apart -- each is wrong
    applied to the other source."""
    _a, out = _run(mm, rec_cache=TOP16, cedh=True)
    assert "LANDS ARE EXCLUDED" in out
    assert "roster" in out
    # The claim that was wrong here, specifically. Naming EDHREC as the other
    # mode is fine and is what the replacement does -- citing its population
    # as the REASON these 38 cards were dropped is not.
    assert "budget population" not in out
    assert "a choice rather than a limit of the data" in out
    # ...and the EDHREC run still gives the EDHREC reason, so this is a branch
    # rather than the argument being dropped from both.
    _a2, out2 = _run(mm, rec_cache=REC)
    assert "budget population" in out2
    assert "a choice rather than a limit of the data" not in out2


def test_an_empty_page_refuses_to_price_a_cut(mm, no_network, tmp_path):
    """A redirect page ranks zero cards. Falling through, every card in the
    list comes back unranked and unbounded -- a report that reads as a deck of
    pure filler, produced from a page that told us nothing."""
    cache = os.path.join(str(tmp_path), "redirect.json")
    with open(cache, "w", encoding="utf-8") as f:
        json.dump({"commanders/thrasios-triton-hero-tymna-the-weaver":
                   {"redirect": "/commanders/somewhere-else"}}, f)
    with pytest.raises(SystemExit) as e:
        _run(mm, rec_cache=cache)
    assert "ranked no cards" in str(e.value)


def test_an_edhtop16_sample_carrying_no_decklists_is_refused(
        mm, no_network, tmp_path):
    """The guard that could not reach this source.

    Five or more entries whose maindecks all come back empty PASS the
    MIN_ENTRIES check and rank nothing, so the empty-payload guard has to
    cover both sources -- as an `elif` on the EDHREC branch it could not. Left
    to fall through, every card in the list prints at a measured 0% against a
    denominator read off a ranked row that does not exist: `0/None`, the whole
    deck, from a payload that told us nothing.
    """
    cache = os.path.join(str(tmp_path), "hollow.json")
    data = {"entries": {"edges": [{"node": {"maindeck": []}} for _ in range(6)]}}
    with open(cache, "w", encoding="utf-8") as f:
        json.dump({"edhtop16/100/Thrasios, Triton Hero / Tymna the Weaver":
                   data}, f)
    with pytest.raises(SystemExit) as e:
        _run(mm, rec_cache=cache, cedh=True)
    assert "ranked no cards" in str(e.value)
    # Names the shape, so the message is actionable rather than just a stop.
    assert "6 entries" in str(e.value)


def test_the_zero_denominator_is_the_sample_not_a_ranked_row(mm):
    """A zero row is exactly the case where there may be no ranked row to read
    a denominator off, so the sample is passed in rather than inferred. Given
    one, it wins over any row: the number of decklists counted is what a 0%
    is a fraction of."""
    rows = [{"name": "Sol Ring", "num_decks": 6, "potential_decks": 99,
             "inclusion": 100.0, "synergy": None, "cardlist": "x"}]
    a = mm.floor_audit("Cmdr", {"Negate": 1}, rows, {},
                       {"negate": {"type_line": "Instant"}},
                       exhaustive=True, sample=6)
    zero = a["below"][0]
    assert (zero["name"], zero["num_decks"], zero["potential_decks"]) == \
        ("Negate", 0, 6)


def test_a_thin_edhtop16_sample_quotes_nothing(mm, no_network, tmp_path):
    """Same refusal `ceiling` makes, for the same reason: below five entries
    every card is 25%, 50%, 75% or 100%, and an ascending table of those reads
    like a list of cards to cut."""
    thin = os.path.join(str(tmp_path), "thin.json")
    with open(TOP16, encoding="utf-8") as f:
        data = list(json.load(f).values())[0]
    data["entries"]["edges"] = data["entries"]["edges"][:4]
    with open(thin, "w", encoding="utf-8") as f:
        json.dump({"edhtop16/100/Thrasios, Triton Hero / Tymna the Weaver": data}, f)
    got, out = _run(mm, rec_cache=thin, cedh=True)
    assert got is None
    assert "4 tournament entries counted" in out
    assert "FEWER THAN 5 ENTRIES" in out
    assert "%" not in out.split("entries counted")[1]
