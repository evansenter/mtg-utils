"""The collection-ceiling audit: what is above the inclusion bar and missing.

Run by hand outside the package this analysis found nine missing cards on one
deck -- a bigger improvement than every manabase finding on it combined -- and
it also shipped a wrong answer, by keying the deck on the full DFC name while
EDHREC returns front faces only. It reported a card as missing that was in the
list. `cards.py` exists to centralise exactly that, which is why the audit
belongs in here rather than in a scratch script.

The two ranking sources disagree about names in opposite directions, verified
against both live endpoints:

    EDHREC     "Agadeem's Awakening"                     -- front face only
    edhtop16   "Sink into Stupor // Soporific Springs"   -- full name

so a comparison that handles one is wrong against the other. Everything is
reduced to the front face.

The other guarded behaviours are all "do not turn an absence of data into a
confident zero": a capped cardlist, a redirect page, and a tournament sample
too small to quote.
"""
import json
import os
import shutil

import pytest

from conftest import FIXTURES, load_fixture_collection

REC = os.path.join(FIXTURES, "ceiling.rec.json")
TOP16 = os.path.join(FIXTURES, "ceiling.top16.json")
SCRY = os.path.join(FIXTURES, "ceiling.scry.json")
PAIR = ["Tymna the Weaver", "Thrasios, Triton Hero"]


def _rec_page():
    with open(REC, encoding="utf-8") as f:
        return list(json.load(f).values())[0]


def _top16_data():
    with open(TOP16, encoding="utf-8") as f:
        return list(json.load(f).values())[0]


def _scry():
    with open(SCRY, encoding="utf-8") as f:
        return json.load(f)


# --- the slug ---------------------------------------------------------
@pytest.mark.parametrize("name,want", [
    ("Tymna the Weaver", "tymna-the-weaver"),
    ("Y'shtola, Night's Blessed", "yshtola-nights-blessed"),
    ("Kroxa, Titan of Death's Hunger", "kroxa-titan-of-deaths-hunger"),
    ("Agadeem's Awakening // Agadeem, the Undercrypt", "agadeems-awakening"),
], ids=["slug/plain", "slug/apostrophes are DROPPED not hyphenated",
        "slug/possessive inside a word", "slug/DFC uses the front face"])
def test_edhrec_slug(mm, name, want):
    """The apostrophe rule is the expensive one.

    `y-shtola-nights-blessed` -- what a naive punctuation-to-hyphen rule
    builds -- returns 403, not 404. The failure therefore reads as "EDHREC is
    blocking us" rather than as "that slug is wrong", which is a much longer
    afternoon. Both forms were checked against the live endpoint.
    """
    assert mm.edhrec_slug(name) == want


def test_partner_slug_is_alphabetical(mm):
    """A pair slug in the wrong order is NOT a 404.

    It answers 200 with {"redirect": ...} and no cardlists. Parsed as a page
    that ranks zero cards, and an audit over zero cards reports nothing
    missing -- a silent all-clear for a deck nobody actually checked.
    """
    assert mm.edhrec_slug(PAIR) == "thrasios-triton-hero-tymna-the-weaver"


# --- parsing the commander page ---------------------------------------
def test_inclusion_is_computed_not_read(mm):
    """There is no `inclusion` field on a cardview.

    Reading one gives None, and None formatted into a percent column reads as
    0% -- a card everybody plays would be reported as a card nobody plays.
    """
    rows, _capped = mm.parse_commander_page(_rec_page())
    assert rows
    for r in rows:
        assert r["inclusion"] == pytest.approx(
            100.0 * r["num_decks"] / r["potential_decks"])
    assert rows == sorted(rows, key=lambda r: -r["inclusion"])


def test_a_full_cardlist_is_marked_capped(mm):
    """EDHREC truncates each list at 50, so absence from a capped list is not
    evidence a card is unplayed. The fixture keeps 'Creatures' at its real
    length of exactly 50 for this reason -- trimming it would destroy the
    signal being tested."""
    rows, capped = mm.parse_commander_page(_rec_page())
    assert "Creatures" in capped
    page = _rec_page()
    lengths = {cl["header"]: len(cl["cardviews"])
               for cl in page["container"]["json_dict"]["cardlists"]}
    assert lengths["Creatures"] == mm.PAGE_CAP
    for header, n in lengths.items():
        assert (header in capped) == (n >= mm.PAGE_CAP), (header, n)


def test_a_card_in_two_cardlists_is_counted_once(mm):
    """'Agadeem's Awakening' appears under both Lands and Utility Lands on a
    real page. Counted twice it makes one absent card look like two, and the
    buy total double-counts its price."""
    rows, _ = mm.parse_commander_page(_rec_page())
    names = [r["name"].lower() for r in rows]
    assert len(names) == len(set(names)), "duplicate card across cardlists"


def test_a_cardview_without_a_ratio_is_skipped_not_zeroed(mm):
    """No ratio means no percentage. Emitting 0.0 is how a missing field
    becomes a confident wrong number in a printed table."""
    page = {"container": {"json_dict": {"cardlists": [{
        "header": "Top Cards",
        "cardviews": [{"name": "Sol Ring", "num_decks": 9, "potential_decks": 10},
                      {"name": "Mana Crypt"},
                      {"name": "Chrome Mox", "num_decks": 5, "potential_decks": 0}]}]}}}
    rows, _ = mm.parse_commander_page(page)
    assert [r["name"] for r in rows] == ["Sol Ring"]


# --- the front-face rule, in both directions --------------------------
def test_a_dfc_in_the_deck_is_not_reported_missing(mm):
    """THE bug this command was written to stop.

    EDHREC says "Commit". The decklist says "Commit // Memory". Compared as
    written they are different strings, and the audit reports a card the deck
    is holding as one it needs to buy.

    Both names are verbatim: `Commit // Memory` is the entry in this repo's
    own multi fixture, and `Commit` is its front face as EDHREC returns it.
    """
    entries = {"Commit // Memory": 1, "Sol Ring": 1}
    rows = [{"name": "Commit", "num_decks": 9, "potential_decks": 10,
             "inclusion": 90.0, "cardlist": "Top Cards"}]
    a = mm.ceiling_audit("Cmdr", entries, rows, [], {}, {}, threshold=50.0)
    assert a["missing"] == [], "an in-deck DFC was reported missing"


def test_a_ranked_row_with_a_full_dfc_name_still_matches_the_deck(mm):
    """The mirror of the case above, for the source side.

    edhtop16 ranks "Sink into Stupor // Soporific Springs". parse_edhtop16
    front-faces it, but ceiling_audit must not depend on having been handed
    already-normalised rows -- a future third source with a third convention
    would otherwise report every DFC in the deck as missing. Both sides are
    reduced, so either convention works on either side.
    """
    entries = {"Sink into Stupor // Soporific Springs": 1}
    rows = [{"name": "Sink into Stupor // Soporific Springs", "num_decks": 9,
             "potential_decks": 10, "inclusion": 90.0, "cardlist": "x"}]
    a = mm.ceiling_audit("Cmdr", entries, rows, [], {}, {}, threshold=50.0)
    assert a["missing"] == []


def test_edhtop16_full_names_are_reduced_to_the_front_face(mm):
    """edhtop16 has the OPPOSITE convention from EDHREC -- it returns
    "Sink into Stupor // Soporific Springs" where EDHREC returns
    "Agadeem's Awakening". Keying both to the front face is what lets one
    comparison work against either."""
    rows, n = mm.parse_edhtop16(_top16_data())
    assert n >= mm.MIN_ENTRIES
    assert rows
    assert not any(" // " in r["name"] for r in rows), \
        [r["name"] for r in rows if " // " in r["name"]]


def test_edhtop16_counts_entries_not_copies(mm):
    """A card is in a decklist or it is not; a second copy is not a second
    deck. Counting copies would push a card past 100% inclusion."""
    rows, n = mm.parse_edhtop16(_top16_data())
    for r in rows:
        assert r["num_decks"] <= n
        assert r["inclusion"] <= 100.0


def test_two_copies_in_one_list_are_one_deck(mm):
    """Built by hand because the committed fixture cannot show this: cEDH
    lists at this level run no basic lands, so no entry in it holds two cards
    of the same name and counting copies is indistinguishable from counting
    entries. A deck with two Islands makes the difference visible -- counted
    by copy, Island lands at 200%.
    """
    data = {"entries": {"edges": [
        {"node": {"maindeck": [{"name": "Island"}, {"name": "Island"},
                               {"name": "Sol Ring"}]}},
        {"node": {"maindeck": [{"name": "Sol Ring"}]}}]}}
    rows, n = mm.parse_edhtop16(data)
    by = {r["name"]: r for r in rows}
    assert n == 2
    assert by["Island"]["num_decks"] == 1
    assert by["Island"]["inclusion"] == pytest.approx(50.0)
    assert by["Sol Ring"]["inclusion"] == pytest.approx(100.0)


def test_a_partner_pair_is_one_commander_on_edhtop16(mm):
    """Querying one half alone resolves to a commander with ZERO entries,
    which reads as "no cEDH data for Thrasios" rather than as "wrong name".
    The pair is joined with ' / ' and sorted."""
    assert mm.edhtop16_commander_name(PAIR) == \
        "Thrasios, Triton Hero / Tymna the Weaver"
    assert mm.edhtop16_commander_name("Kinnan, Bonder Prodigy") == \
        "Kinnan, Bonder Prodigy"


# --- the audit --------------------------------------------------------
def test_the_commander_is_never_reported_missing(mm):
    rows = [{"name": "Tymna the Weaver", "num_decks": 9, "potential_decks": 10,
             "inclusion": 90.0, "cardlist": "Top Cards"}]
    a = mm.ceiling_audit(PAIR, {"Sol Ring": 1}, rows, [], {}, {})
    assert a["missing"] == []


def test_the_audit_attaches_ownership_and_price(mm):
    """The question is not just "what is missing" but "do I already own it" --
    an owned card is a deckbuilding decision and an unowned one is a purchase.
    """
    rows = [{"name": "Thassa's Oracle", "num_decks": 9, "potential_decks": 10,
             "inclusion": 90.0, "cardlist": "Top Cards"},
            {"name": "Force of Will", "num_decks": 8, "potential_decks": 10,
             "inclusion": 80.0, "cardlist": "Top Cards"}]
    owned = {"thassa's oracle": 2}
    scry = {"thassa's oracle": {"prices": {"usd": "20.86"}, "type_line": "Creature"},
            "force of will": {"prices": {"usd": "59.20"}, "type_line": "Instant"}}
    a = mm.ceiling_audit("Cmdr", {"Sol Ring": 1}, rows, [], owned, scry)
    by = {m["name"]: m for m in a["missing"]}
    assert by["Thassa's Oracle"]["owned"] == 2
    assert by["Force of Will"]["price"] == pytest.approx(59.20)
    assert a["owned_count"] == 1
    # An owned card is not a purchase, so it stays out of the buy total.
    assert a["buy_total"] == pytest.approx(59.20)


def test_the_bar_excludes_what_is_below_it(mm):
    rows = [{"name": "A", "num_decks": 9, "potential_decks": 10,
             "inclusion": 90.0, "cardlist": "x"},
            {"name": "B", "num_decks": 3, "potential_decks": 10,
             "inclusion": 30.0, "cardlist": "x"}]
    a = mm.ceiling_audit("Cmdr", {}, rows, [], {}, {}, threshold=50.0)
    assert [m["name"] for m in a["missing"]] == ["A"]


# --- the report -------------------------------------------------------
def _no_network(monkeypatch):
    """Make any outbound call a test failure, not a slow pass.

    Written after a case here silently went to the live endpoint: the
    edhtop16 cache key carries the `first` value, the fixture had been built
    at first=30, and the lookup at the default first=100 missed and fetched.
    Every other assertion in that test still passed, against 100 live entries
    instead of the 6 committed ones -- so the case was green, non-
    deterministic, and not testing the fixture at all.
    """
    import subprocess

    def boom(*a, **kw):
        raise AssertionError(
            "the offline suite tried to reach the network -- a fixture cache "
            "key probably does not match what the code asks for")

    # Every source module calls subprocess.run through the shared module
    # object, so one patch covers curl wherever it is invoked from.
    monkeypatch.setattr(subprocess, "run", boom)


def _run_ceiling(mm, monkeypatch, tmp_path, spellbook=None, **kw):
    import mtg_utils.report as report
    monkeypatch.setattr(report, "load_collection", load_fixture_collection)
    # The Commander Spellbook cross-check is ON by default, so EVERY report
    # test now drives it. Patched here rather than in each case: left to the
    # no-network guard it would surface as an AssertionError from inside
    # curl, several frames from the cause, in tests about something else.
    monkeypatch.setattr(report, "spellbook",
                        spellbook or (lambda c, e: _combos()))
    _no_network(monkeypatch)
    # scry_fetch rewrites its cache on every run, so the committed fixture is
    # copied first -- the same trap the golden harness already handles.
    scry_copy = os.path.join(str(tmp_path), "ceiling.scry.json")
    shutil.copyfile(SCRY, scry_copy)
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "partner.txt"))
    return report.report_ceiling(cmdr, entries, _scry(), scry_copy, **kw)


def test_a_capped_list_is_reported_as_below_cutoff_never_as_zero(mm, monkeypatch,
                                                                tmp_path, capsys):
    """The acceptance criterion. A card absent from a truncated list is of
    UNKNOWN inclusion; printing it as 0% would be a number the tool could not
    have retrieved."""
    _run_ceiling(mm, monkeypatch, tmp_path, rec_cache=REC, threshold=75.0)
    out = capsys.readouterr().out
    assert "display cutoff" in out
    assert "Creatures" in out
    assert "UNKNOWN inclusion, not 0%" in out
    assert "0.0%" not in out


def test_the_report_lists_missing_cards_with_their_ratio(mm, monkeypatch,
                                                        tmp_path, capsys):
    a = _run_ceiling(mm, monkeypatch, tmp_path, rec_cache=REC, threshold=75.0)
    out = capsys.readouterr().out
    assert "CEILING vs EDHREC" in out
    assert a["missing"], "the fixture should have cards above a 75% bar"
    for m in a["missing"]:
        assert m["name"][:34] in out
        # The ratio is printed beside the percentage so a reader can see the
        # sample it came from rather than trusting the percent alone.
        assert f"{m['num_decks']}/{m['potential_decks']}" in out


def test_an_empty_page_refuses_to_report_an_all_clear(mm, monkeypatch, tmp_path):
    """A redirect page ranks zero cards. Falling through, the audit finds
    nothing missing and the deck reads as needing no work -- the most
    reassuring possible output from a page that told us nothing."""
    redirect_cache = os.path.join(str(tmp_path), "redirect.json")
    with open(redirect_cache, "w", encoding="utf-8") as f:
        json.dump({"commanders/thrasios-triton-hero-tymna-the-weaver":
                   {"redirect": "/commanders/somewhere-else"}}, f)
    with pytest.raises(SystemExit) as e:
        _run_ceiling(mm, monkeypatch, tmp_path, rec_cache=redirect_cache)
    assert "ranked no cards" in str(e.value)


def test_a_thin_edhtop16_sample_prints_the_count_and_quotes_nothing(
        mm, monkeypatch, tmp_path, capsys):
    """The acceptance criterion. Below five entries every card is 25%, 50%,
    75% or 100%, and a table of those reads like a strong signal."""
    thin = os.path.join(str(tmp_path), "thin.json")
    data = _top16_data()
    data["entries"]["edges"] = data["entries"]["edges"][:4]
    with open(thin, "w", encoding="utf-8") as f:
        json.dump({"edhtop16/100/Thrasios, Triton Hero / Tymna the Weaver": data}, f)
    got = _run_ceiling(mm, monkeypatch, tmp_path, rec_cache=thin, cedh=True)
    out = capsys.readouterr().out
    assert got is None
    assert "4 tournament entries counted" in out
    assert "FEWER THAN 5 ENTRIES" in out
    assert "%" not in out.split("entries counted")[1]


def test_a_sufficient_edhtop16_sample_does_quote_percentages(
        mm, monkeypatch, tmp_path, capsys):
    """The mirror of the case above: the refusal must be about the sample
    size, not a report that never quotes anything."""
    got = _run_ceiling(mm, monkeypatch, tmp_path, rec_cache=TOP16, cedh=True,
                       threshold=90.0)
    out = capsys.readouterr().out
    assert "CEILING vs edhtop16" in out
    assert "6 tournament entries counted" in out
    assert "FEWER THAN" not in out
    assert got is not None and got["missing"]


# --- synergy ----------------------------------------------------------
# Inclusion alone cannot separate a commander-specific card from generic
# goodstuff: Sol Ring is 80% in every deck ever built and says nothing about
# THIS commander. EDHREC ships the discriminator in the same payload and it
# was being dropped at parse time -- the column exists to stop the tool
# ranking on the axis nobody was choosing on.
def test_synergy_is_carried_from_the_payload(mm):
    """It is in every cardview and was being discarded by parse_commander_page.

    Pinned to the committed fixture's real value, so dropping the field again
    fails here rather than reading as a formatting change downstream.
    """
    rows, _ = mm.parse_commander_page(_rec_page())
    by = {r["name"]: r for r in rows}
    assert by["Birds of Paradise"]["synergy"] == pytest.approx(0.47119880)
    assert all(r["synergy"] is not None for r in rows)


def test_a_cardview_without_synergy_is_none_not_zero(mm):
    """Zero is a MEASURED synergy -- it is exactly what a card played at the
    same rate everywhere scores. A missing field defaulted to 0.0 is therefore
    not a harmless placeholder: it is a specific, wrong, plausible claim about
    the one card the column had no data for."""
    page = {"container": {"json_dict": {"cardlists": [{
        "header": "Top Cards",
        "cardviews": [{"name": "Sol Ring", "num_decks": 9,
                       "potential_decks": 10},
                      {"name": "Mystic Remora", "num_decks": 8,
                       "potential_decks": 10, "synergy": 0.0}]}]}}}
    rows, _ = mm.parse_commander_page(page)
    by = {r["name"]: r for r in rows}
    assert by["Sol Ring"]["synergy"] is None
    assert by["Mystic Remora"]["synergy"] == 0.0


def test_edhtop16_rows_report_synergy_as_unknown(mm):
    """synergy is an EDHREC statistic. edhtop16 does not carry it, and the key
    must still be present and None so --sort=synergy against --cedh ranks
    nothing visibly rather than ranking everything at a fabricated zero."""
    rows, n = mm.parse_edhtop16(_top16_data())
    assert rows and n == 6
    assert all(r["synergy"] is None for r in rows)


def test_the_dedup_keeps_the_synergy_of_the_row_it_keeps(mm):
    """A card in two cardlists is kept once, at its HIGHEST inclusion. Its
    synergy has to travel with the row that survived: keeping 88%'s inclusion
    beside 30%'s synergy is a figure that appears on no EDHREC page."""
    page = {"container": {"json_dict": {"cardlists": [
        {"header": "Lands",
         "cardviews": [{"name": "Ancient Tomb", "num_decks": 3,
                        "potential_decks": 10, "synergy": 0.1}]},
        {"header": "Utility Lands",
         "cardviews": [{"name": "Ancient Tomb", "num_decks": 9,
                        "potential_decks": 10, "synergy": 0.9}]}]}}}
    rows, _ = mm.parse_commander_page(page)
    assert len(rows) == 1
    assert rows[0]["inclusion"] == pytest.approx(90.0)
    assert rows[0]["synergy"] == pytest.approx(0.9)


def _syn_rows():
    """Goodstuff ranks above the signal card on inclusion and below it on
    synergy, so the two orderings are not the same list."""
    return [
        {"name": "Goodstuff", "num_decks": 9, "potential_decks": 10,
         "inclusion": 90.0, "synergy": 0.02, "cardlist": "x"},
        {"name": "Signal", "num_decks": 6, "potential_decks": 10,
         "inclusion": 60.0, "synergy": 0.55, "cardlist": "x"},
        {"name": "Fringe", "num_decks": 1, "potential_decks": 10,
         "inclusion": 10.0, "synergy": 0.95, "cardlist": "x"},
    ]


def test_sort_by_synergy_reorders_the_table(mm):
    a = mm.ceiling_audit("Cmdr", {}, _syn_rows(), [], {}, {}, sort="synergy")
    assert [m["name"] for m in a["missing"]] == ["Signal", "Goodstuff"]


def test_sorting_by_synergy_does_not_move_the_bar(mm):
    """The bar stays on inclusion whichever way the table is sorted. Fringe
    has the highest synergy on the page and is played in one deck in ten:
    letting the sort key double as the filter is how a --sort flag turns into
    a silent change of what the audit reports."""
    for sort in ("inclusion", "synergy"):
        a = mm.ceiling_audit("Cmdr", {}, _syn_rows(), [], {}, {}, sort=sort)
        assert "Fringe" not in [m["name"] for m in a["missing"]], sort
        assert len(a["missing"]) == 2, sort


def test_unknown_synergy_sorts_last_not_at_zero(mm):
    """A --cedh row has no synergy at all. Sorted as 0.0 it lands ABOVE every
    card with a measured negative synergy -- so the rows the tool knows least
    about would outrank the ones it measured and found wanting."""
    rows = [{"name": "Measured", "num_decks": 9, "potential_decks": 10,
             "inclusion": 90.0, "synergy": -0.2, "cardlist": "x"},
            {"name": "Unknown", "num_decks": 8, "potential_decks": 10,
             "inclusion": 80.0, "synergy": None, "cardlist": "x"}]
    a = mm.ceiling_audit("Cmdr", {}, rows, [], {}, {}, sort="synergy")
    assert [m["name"] for m in a["missing"]] == ["Measured", "Unknown"]


def test_the_report_prints_synergy_and_says_how_it_sorted(mm, monkeypatch,
                                                          tmp_path, capsys):
    _run_ceiling(mm, monkeypatch, tmp_path, rec_cache=REC, threshold=75.0,
                 sort="synergy")
    out = capsys.readouterr().out
    assert "sorted by synergy" in out
    # Signed, so a negative synergy cannot be mistaken for a positive one at
    # a glance in a column of small decimals.
    assert "+0.579" in out
    # The whole point, on real data: Deathrite Shaman has the LOWEST inclusion
    # of the four rows above the bar and the highest synergy, so it sorts
    # first here and last under --sort=inclusion. If the two orderings ever
    # agree on this fixture the case has stopped discriminating.
    rows = [l for l in out.split("\n") if "%" in l and "bar is" not in l]
    assert "Deathrite Shaman" in rows[0]
    assert "75.6%" in rows[0]


def test_the_report_prints_unknown_synergy_as_a_dash(mm, monkeypatch, tmp_path,
                                                     capsys):
    """--cedh has no synergy for any row, and 0.000 down the column would read
    as a measured finding that every tournament card is pure goodstuff."""
    _run_ceiling(mm, monkeypatch, tmp_path, rec_cache=TOP16, cedh=True,
                 threshold=90.0)
    out = capsys.readouterr().out
    assert "0.000" not in out


# --- the combo cross-check --------------------------------------------
# A ceiling row is ranked on how often other people play the card. That says
# nothing about what it does with THIS list. On the deck that prompted this,
# the two rows that form infinites with cards already in the deck sit at 7.9%
# and 6.8% inclusion -- below any default bar, reachable only by lowering it,
# which is exactly when nobody thinks to add a flag. Hence: on by default.
COMBOS = os.path.join(FIXTURES, "ceiling.combos.json")


def _combos():
    with open(COMBOS, encoding="utf-8") as f:
        return json.load(f)


def test_a_completion_is_keyed_on_the_front_face(mm):
    """Spellbook is the THIRD naming convention here -- it returns full DFC
    names, where EDHREC returns front faces. Unnormalised, a DFC combo piece
    never joins to the ceiling row it belongs to and the annotation silently
    never appears."""
    res = {"almostIncluded": [{"uses": [
        {"card": {"name": "Sink into Stupor // Soporific Springs"}},
        {"card": {"name": "Sol Ring"}}]}]}
    got = mm.combo_completions(res, "Cmdr", {"Sol Ring": 1})
    assert list(got) == ["sink into stupor"]
    assert got["sink into stupor"][0]["with"] == ["Sol Ring"]


def test_a_dfc_the_deck_holds_is_not_offered_as_a_completion(mm):
    """The other half of the front-face rule, and the one with teeth.

    The decklist spells out "Commit // Memory"; Spellbook names the piece
    "Commit". Compare those as written and a card sitting in the deck reads as
    a card that would COMPLETE a combo -- so the row is annotated with an
    interaction the deck already has, and the count of interacting rows goes
    up by one for a purchase nobody needs to make.

    Distinct from the keying case above: that one pins the dict key, this one
    pins the membership test, and a fix to either alone leaves the other
    broken.
    """
    res = {"almostIncluded": [{"uses": [{"card": {"name": "Commit"}},
                                        {"card": {"name": "Basalt Monolith"}}]}]}
    got = mm.combo_completions(res, "Cmdr", {"Commit // Memory": 1})
    assert list(got) == ["basalt monolith"]
    assert got["basalt monolith"][0]["with"] == ["Commit"]


def test_a_card_already_in_the_deck_is_not_a_completion(mm):
    """It is a piece the deck HOLDS. Listed as a completion it would annotate
    a ceiling row that, by construction, cannot exist -- and inflate the count
    of rows that interact."""
    res = {"almostIncluded": [{"uses": [{"card": {"name": "Sol Ring"}},
                                        {"card": {"name": "Basalt Monolith"}}]}]}
    got = mm.combo_completions(res, "Cmdr", {"Sol Ring": 1})
    assert list(got) == ["basalt monolith"]


def test_a_combo_needing_two_more_cards_says_so(mm):
    """"Almost included" means at LEAST one piece missing, not exactly one. A
    row annotated COMBO that in fact needs two more cards overstates a case
    the reader cannot check from the table."""
    res = {"almostIncluded": [{"uses": [{"card": {"name": "Sol Ring"}},
                                        {"card": {"name": "Displacer Kitten"}},
                                        {"card": {"name": "Dark Ritual"}}]}]}
    got = mm.combo_completions(res, "Cmdr", {"Sol Ring": 1})
    assert got["displacer kitten"][0]["also_missing"] == ["Dark Ritual"]
    assert got["dark ritual"][0]["also_missing"] == ["Displacer Kitten"]


def test_a_template_counts_as_a_piece(mm):
    """"Permanent Castable for {C}" is a real card the deck has to supply.
    Left out of the count, a three-piece line reads as a two-card combo --
    which is the difference between a plan and a coincidence."""
    res = {"almostIncluded": [{
        "uses": [{"card": {"name": "Sol Ring"}},
                 {"card": {"name": "Hullbreaker Horror"}}],
        "requires": [{"template": {"name": "Permanent Castable for {C}"}}]}]}
    got = mm.combo_completions(res, "Cmdr", {"Sol Ring": 1})
    assert got["hullbreaker horror"][0]["pieces"] == 3
    assert got["hullbreaker horror"][0]["templates"] == \
        ["Permanent Castable for {C}"]


def test_combos_this_card_finishes_alone_sort_first(mm):
    """A combo the card completes on its own is a different proposition from
    one that needs two more purchases, and the first line under a row is the
    one that gets read."""
    res = {"almostIncluded": [
        {"uses": [{"card": {"name": "Kitten"}}, {"card": {"name": "Sol Ring"}},
                  {"card": {"name": "Absent Two"}}]},
        {"uses": [{"card": {"name": "Kitten"}}, {"card": {"name": "Sol Ring"}}]}]}
    got = mm.combo_completions(res, "Cmdr", {"Sol Ring": 1})["kitten"]
    assert got[0]["also_missing"] == []
    assert got[1]["also_missing"] == ["Absent Two"]


def test_the_audit_attaches_combos_to_the_right_row(mm):
    rows = [{"name": "Hullbreaker Horror", "num_decks": 9, "potential_decks": 10,
             "inclusion": 90.0, "synergy": 0.1, "cardlist": "x"},
            {"name": "Force of Will", "num_decks": 8, "potential_decks": 10,
             "inclusion": 80.0, "synergy": 0.1, "cardlist": "x"}]
    completions = {"hullbreaker horror": [{"with": ["Sol Ring"], "templates": [],
                                           "also_missing": [], "produces": [],
                                           "pieces": 2}]}
    a = mm.ceiling_audit("Cmdr", {}, rows, [], {}, {}, completions=completions)
    by = {m["name"]: m for m in a["missing"]}
    assert len(by["Hullbreaker Horror"]["combos"]) == 1
    assert by["Force of Will"]["combos"] == []
    assert a["combo_rows"] == 1


def test_the_fixture_deck_has_the_two_real_intersections(mm):
    """Verbatim find-my-combos output for the partner fixture deck. Both rows
    are FAR below the 50% default bar, which is the whole argument for the
    check being on by default rather than behind a flag."""
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "partner.txt"))
    got = mm.combo_completions(_combos(), cmdr, entries)
    rows, _ = mm.parse_commander_page(_rec_page())
    ranked = {r["name"].lower(): r["inclusion"] for r in rows}
    hits = {k: ranked[k] for k in got if k in ranked}
    assert set(hits) == {"displacer kitten", "hullbreaker horror"}
    assert all(v < 50.0 for v in hits.values()), hits
    # Hullbreaker Horror + Sol Ring is real, and Sol Ring is in the fixture
    # deck.
    assert "Sol Ring" in got["hullbreaker horror"][0]["with"]


# --- the report -------------------------------------------------------
def test_the_report_flags_a_combo_row_inline(mm, monkeypatch, tmp_path, capsys):
    """The acceptance criterion: the annotation sits under the row it belongs
    to, so it cannot be read as applying to a different card."""
    _run_ceiling(mm, monkeypatch, tmp_path, rec_cache=REC, threshold=6.0)
    out = capsys.readouterr().out.split("\n")
    i = next(n for n, l in enumerate(out) if "Hullbreaker Horror" in l)
    assert "COMBO with Sol Ring" in out[i + 1]
    assert "Permanent Castable for {C} (template)" in out[i + 1]
    assert "Infinite colorless mana" in out[i + 1]


def test_the_report_never_calls_a_combo_a_recommendation(mm, monkeypatch,
                                                         tmp_path, capsys):
    """The interaction that prompted this feature was a card forming a FORCED
    DRAW with two cards already in the deck. Whether a combo argues for or
    against a card is not Spellbook's to say, and a tool that phrased it as a
    recommendation would have recommended the draw."""
    _run_ceiling(mm, monkeypatch, tmp_path, rec_cache=REC, threshold=6.0)
    out = capsys.readouterr().out
    assert "a fact, not a recommendation" in out
    assert "recommended" not in out.lower().replace("not a recommendation", "")


def test_a_row_with_many_combos_says_how_many_it_dropped(mm, monkeypatch,
                                                         tmp_path, capsys):
    """No silent caps. "2 combos" on a row that has nine is a smaller number
    than the truth, printed with confidence."""
    res = {"almostIncluded": [
        {"uses": [{"card": {"name": "Deathrite Shaman"}},
                  {"card": {"name": f"Piece {i}"}},
                  {"card": {"name": "Sol Ring"}}]} for i in range(5)]}
    _run_ceiling(mm, monkeypatch, tmp_path, spellbook=lambda c, e: res,
                 rec_cache=REC, threshold=75.0)
    out = capsys.readouterr().out
    assert "...and 3 more combos" in out


def test_a_spellbook_outage_is_announced_not_silently_clean(mm, monkeypatch,
                                                            tmp_path, capsys):
    """An unrun check and a clean result are the same empty column. This is
    the same rule the capped-cardlist note follows: absence of data is never
    reported as a finding of none."""
    def boom(cmdr, entries):
        raise SystemExit("Commander Spellbook find-my-combos failed after retries")
    a = _run_ceiling(mm, monkeypatch, tmp_path, spellbook=boom,
                     rec_cache=REC, threshold=75.0)
    out = capsys.readouterr().out
    assert "COMBO CROSS-CHECK DID NOT RUN" in out
    assert "NOT known to be free of combos" in out
    # and the audit still produced its rows -- an outage in one source must
    # not take the whole command down
    assert a["missing"]


def test_no_combos_skips_the_call_without_claiming_a_clean_result(
        mm, monkeypatch, tmp_path, capsys):
    """--no-combos must not print the "0 rows interact" line: the check did
    not run, and saying nothing interacts would be the claim it declined to
    make."""
    def boom(cmdr, entries):
        raise AssertionError("--no-combos still called Commander Spellbook")

    _run_ceiling(mm, monkeypatch, tmp_path, spellbook=boom, rec_cache=REC,
                 threshold=75.0, combos=False)
    out = capsys.readouterr().out
    assert "interact with cards already in the list" not in out
    assert "COMBO CROSS-CHECK DID NOT RUN" not in out


def test_a_clean_cross_check_says_it_ran(mm, monkeypatch, tmp_path, capsys):
    """The mirror of the outage case: "0 rows interact" is a result, and it
    has to be distinguishable from the check not running."""
    _run_ceiling(mm, monkeypatch, tmp_path,
                 spellbook=lambda c, e: {"almostIncluded": []},
                 rec_cache=REC, threshold=75.0)
    out = capsys.readouterr().out
    assert "0 rows interact with cards already in the list" in out
    assert "COMBO CROSS-CHECK DID NOT RUN" not in out
