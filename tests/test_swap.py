"""Named swaps: `variants --swap="Cut->Add"`.

`variants` sweeps COUNTS. It could not answer "what does swapping these three
checklands for these three filter lands do", which is the question nearly
every time a manabase is questioned -- so it was being answered by regex
substitution against the raw .txt, outside the package and with no assertions.

The guards are the point of these cases. A swap naming a card the deck does
not have must RAISE, because a silent no-op reports "this change moves
nothing" -- indistinguishable from the genuine finding that a swap moves
nothing because the deck has no unmet pip. That finding is the one thing this
command exists to produce, so it must not also be its failure mode.
"""
import json
import os

import pytest

from conftest import FIXTURES, deck_args, run_cli

CMDR = ["Tymna the Weaver", "Thrasios, Triton Hero"]


def _partner(mm):
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "partner.txt"))
    with open(os.path.join(FIXTURES, "partner.scry.json"), encoding="utf-8") as f:
        scry = json.load(f)
    return cmdr, entries, scry


# --- parsing ----------------------------------------------------------
@pytest.mark.parametrize("spec,want", [
    ("", []),
    ("   ", []),
    ("A->B", [("A", "B")]),
    ("A->B,C->D", [("A", "B"), ("C", "D")]),
    ("  A -> B , C -> D  ", [("A", "B"), ("C", "D")]),
    ("A->B;C->D", [("A", "B"), ("C", "D")]),
], ids=["swap/empty is no swaps", "swap/blank is no swaps", "swap/one pair",
        "swap/two pairs", "swap/whitespace is trimmed",
        "swap/semicolon separates"])
def test_parse_swaps(mm, spec, want):
    assert mm.parse_swaps(spec) == want


def test_semicolon_wins_so_a_comma_can_live_in_a_name(mm):
    """'Muldrotha, the Gravetide' has a comma in it.

    A comma is therefore not a safe pair separator, and the semicolon is the
    escape hatch. Splitting this on the comma would try to cut a card called
    'Muldrotha' and add one called 'the Gravetide->X', neither of which
    exists -- and the resulting error would name cards the user never typed.
    """
    got = mm.parse_swaps("Muldrotha, the Gravetide->Sol Ring;Island->Swamp")
    assert got == [("Muldrotha, the Gravetide", "Sol Ring"), ("Island", "Swamp")]


# --- the same separator rule, for the flags that take bare names ------
@pytest.mark.parametrize("spec,want", [
    ("", []),
    ("   ", []),
    ("A", ["A"]),
    ("A,B", ["A", "B"]),
    ("  A , B  ", ["A", "B"]),
    ("A,,B", ["A", "B"]),
    ("A;B", ["A", "B"]),
], ids=["names/empty is no names", "names/blank is no names", "names/one name",
        "names/two names", "names/whitespace is trimmed",
        "names/empty segment is dropped", "names/semicolon separates"])
def test_split_names(mm, spec, want):
    assert mm.split_names(spec) == want


def test_split_names_keeps_a_comma_inside_a_name(mm):
    """names/a comma in a name survives

    'Ghalta, Primal Hunger' is one card. --adds and --cuts split on ',' alone,
    so it arrived at write_deck as two names, and the read-back assertion
    failed with "MISSING ADD: Ghalta" -- an error naming a card the user never
    typed, about a name they spelled correctly.

    Asserted as one element rather than as a substring: 'Ghalta' is a prefix of
    the full name, so `any("Ghalta" in n for n in got)` passes on the split
    output too and would have caught nothing.
    """
    got = mm.split_names("Ghalta, Primal Hunger;Sol Ring")
    assert got == ["Ghalta, Primal Hunger", "Sol Ring"]


def test_the_two_name_flags_agree_on_the_separator(mm):
    """names/--swap and --adds split alike

    The bug was a divergence: --swap had the ';' escape hatch and --adds/--cuts
    did not, so the same card name could be swapped in but not added. Both go
    through _sep now, and this is where they would disagree again first.
    """
    name = "Ghalta, Primal Hunger"
    assert mm.split_names(f"{name};Sol Ring") == [name, "Sol Ring"]
    assert mm.parse_swaps(f"Island->{name};Sol Ring->Swamp") == [
        ("Island", name), ("Sol Ring", "Swamp")]


@pytest.mark.parametrize("spec", ["Mystic Gate", "A->B->C", "->B", "A->"],
                         ids=["swap/no arrow", "swap/two arrows",
                              "swap/empty cut", "swap/empty add"])
def test_parse_swaps_rejects_a_malformed_pair(mm, spec):
    """Mis-splitting is worse than refusing: a mis-split swap cuts a card
    nobody asked to cut and then reports the result as a measurement, so the
    wrong number arrives looking like an answer."""
    with pytest.raises(SystemExit):
        mm.parse_swaps(spec)


# --- applying ---------------------------------------------------------
def test_apply_swaps_cuts_and_adds_keeping_the_total(mm):
    """write_deck's contract, enforced up front instead of after the fact."""
    entries = {"Island": 3, "Mystic Gate": 1, "Sol Ring": 1}
    got = mm.apply_swaps("Cmdr", entries, [("Mystic Gate", "Wooded Bastion")])
    assert got["Wooded Bastion"] == 1
    assert "Mystic Gate" not in got
    assert sum(got.values()) == sum(entries.values())
    assert entries["Mystic Gate"] == 1, "the input must not be mutated"


def test_apply_swaps_decrements_a_multiple_rather_than_removing_it(mm):
    """Cutting one Island of three leaves two.

    Basics are the only entries above one in a singleton deck, and they are
    exactly what a manabase swap cuts, so this is the common case rather than
    an edge case.
    """
    got = mm.apply_swaps("Cmdr", {"Island": 3, "Sol Ring": 1},
                         [("Island", "Wooded Bastion")])
    assert got["Island"] == 2
    assert got["Wooded Bastion"] == 1
    assert sum(got.values()) == 4


def test_apply_swaps_matches_case_insensitively_but_keeps_deck_spelling(mm):
    got = mm.apply_swaps("Cmdr", {"Mystic Gate": 1, "Island": 1},
                         [("mystic GATE", "Wooded Bastion")])
    assert "Mystic Gate" not in got and "mystic GATE" not in got
    assert got["Wooded Bastion"] == 1


def test_swapping_a_card_the_deck_lacks_raises(mm):
    """The acceptance criterion. A silent no-op here would print "nothing
    moved", which is exactly what a correct run prints when a swap genuinely
    changes nothing -- so the failure would be indistinguishable from the
    finding."""
    with pytest.raises(SystemExit) as e:
        mm.apply_swaps("Cmdr", {"Island": 1}, [("Mystic Gate", "Wooded Bastion")])
    assert "Mystic Gate" in str(e.value)


def test_adding_a_card_the_deck_already_has_raises(mm):
    """Commander is singleton, so this would build an illegal deck and
    measure it."""
    with pytest.raises(SystemExit) as e:
        mm.apply_swaps("Cmdr", {"Island": 1, "Sol Ring": 1},
                       [("Island", "Sol Ring")])
    assert "Sol Ring" in str(e.value)


def test_swapping_a_commander_raises(mm):
    """The commander is not part of the 99 and swapping it changes the
    deck's colour identity -- a different question than this measures, and
    one that would silently invalidate every colour figure in the table."""
    with pytest.raises(SystemExit) as e:
        mm.apply_swaps(CMDR, {"Island": 1},
                       [("Tymna the Weaver", "Wooded Bastion")])
    assert "commander" in str(e.value).lower()


def test_swapping_a_card_for_itself_raises(mm):
    with pytest.raises(SystemExit):
        mm.apply_swaps("Cmdr", {"Island": 1}, [("Island", "island")])


# --- comparing --------------------------------------------------------
def test_an_unresolvable_add_raises_rather_than_scoring_zero(mm):
    """A card the cache cannot resolve builds no profile at all, so it is
    modelled as producing nothing -- and the table would report a large drop
    that reads as a catastrophic result rather than as a misspelling."""
    cmdr, entries, scry = _partner(mm)
    with pytest.raises(SystemExit) as e:
        mm.compare_swap(cmdr, entries, scry,
                        [("Mystic Gate", "Wodoed Bastion")], sims=20, trials=20)
    assert "Wodoed Bastion" in str(e.value)


def test_both_sides_are_measured_on_the_same_lines(mm):
    """The base deck picks the lines and the swapped deck is handed them.

    Letting each side choose its own worst five would compare different
    questions: the tables would look like a before and an after while
    actually describing two different sets of cards, and a "change" could be
    nothing but a change of subject.
    """
    cmdr, entries, scry = _partner(mm)
    c = mm.compare_swap(cmdr, entries, scry, [("Mystic Gate", "Wooded Bastion")],
                        sims=200, trials=400)
    assert c["base"]["lines"] == c["after"]["lines"]
    assert c["sources"], "no shared sources-model rows to compare"
    assert c["play"], "no play-simulation rows to compare"
    for r in c["sources"] + c["play"]:
        assert r["delta"] == pytest.approx(r["after"] - r["before"])


def test_the_swapped_deck_is_the_swapped_deck(mm):
    """compare_swap must measure the deck the swap describes -- asserted on
    the entries it actually built, not inferred from the numbers moving."""
    cmdr, entries, scry = _partner(mm)
    c = mm.compare_swap(cmdr, entries, scry, [("Mystic Gate", "Wooded Bastion")],
                        sims=20, trials=20)
    after = c["entries_after"]
    assert "Mystic Gate" not in after
    assert after["Wooded Bastion"] == 1
    assert sum(after.values()) == sum(entries.values())


def test_sources_rows_are_percentages_like_the_play_rows(mm):
    """Both tables land in the same column of the same report.

    The sources model works in 0..1 and the play simulation in 0..100; two
    adjacent numbers in different units is a bug this repo has already had
    once, with tapped-land counts against land counts.
    """
    cmdr, entries, scry = _partner(mm)
    c = mm.compare_swap(cmdr, entries, scry, [("Mystic Gate", "Wooded Bastion")],
                        sims=200, trials=400)
    for r in c["sources"]:
        assert 1.0 < r["before"] <= 100.0, r
        assert 1.0 < r["after"] <= 100.0, r


def test_one_replicate_never_claims_anything_moved(mm):
    """With reps=1 there is no spread, so nothing can be shown to have moved.

    Reporting MOVES off a zero error bar would mark every rounding difference
    as a finding -- the most confident possible output from the least
    informative possible run.
    """
    cmdr, entries, scry = _partner(mm)
    c = mm.compare_swap(cmdr, entries, scry, [("Mystic Gate", "Wooded Bastion")],
                        sims=200, trials=400, reps=1)
    rows = c["sources"] + c["play"]
    assert rows
    assert all(r["noise"] == 0.0 for r in rows)
    assert not any(r["beyond_noise"] for r in rows)


def test_the_verdict_multiplier_widens_as_replicates_shrink(mm):
    """Three replicates estimate the spread from three numbers, so the
    familiar 1.96 is far too tight: the difference of two three-replicate
    means has df=4 and wants 2.78. A flat multiplier over-calls MOVES, and a
    false MOVES is the expensive direction -- it sends someone to rebuild a
    manabase over noise.
    """
    assert mm.t95(4) == pytest.approx(2.776, abs=0.001)
    assert mm.t95(2) > mm.t95(4) > mm.t95(30) >= 1.96
    assert mm.t95(10_000) == pytest.approx(1.96)


def test_a_delta_inside_the_multiplied_noise_is_not_called_moved(mm):
    """The verdict is delta vs t*noise, not delta vs noise."""
    cmdr, entries, scry = _partner(mm)
    c = mm.compare_swap(cmdr, entries, scry, [("Mystic Gate", "Wooded Bastion")],
                        sims=200, trials=400)
    crit = mm.t95(2 * (3 - 1))
    for r in c["sources"] + c["play"]:
        assert r["beyond_noise"] == (abs(r["delta"]) > crit * r["noise"]), r


# --- end to end -------------------------------------------------------
def test_cli_swap_prints_before_and_after(mm, tmp_path):
    out = run_cli(mm, deck_args("partner", "variants",
                                ["--swap=Mystic Gate->Wooded Bastion",
                                 "--trials=900", "--sims=300"]), str(tmp_path))
    assert "=== NAMED SWAP" in out
    assert "cut Mystic Gate  ->  add Wooded Bastion" in out
    assert "sources model (colour): before -> after" in out
    assert "play simulation: before -> after" in out
    # The count sweep answers a different question and is not run. Skipping it
    # silently would read as a sweep that found nothing.
    assert "count sweep not run" in out
    assert "VARIANTS SWEEP" not in out


def test_cli_swap_of_a_card_not_in_the_deck_fails_loudly(mm, tmp_path):
    out = run_cli(mm, deck_args("partner", "variants",
                                ["--swap=Not A Real Card->Wooded Bastion",
                                 "--trials=200", "--sims=100"]), str(tmp_path))
    assert "cannot cut" in out and "Not A Real Card" in out
    assert "before -> after" not in out


def test_variants_without_swap_still_sweeps_counts(mm, tmp_path):
    """--swap is additive. Without it, `variants` is what it always was."""
    out = run_cli(mm, deck_args("partner", "variants",
                                ["--trials=400", "--lands=0", "--accel=0"]),
                  str(tmp_path))
    assert "VARIANTS SWEEP" in out
    assert "NAMED SWAP" not in out
