"""Monte Carlo noise is reported, not left to be inferred.

Before this, nothing in the output said how stable a figure was, so a
0.4-point gap between two manabase variants read exactly like a 4-point one.
Deciding which of those was real meant running several seeds by hand and
computing the spread outside the tool -- the hand-arithmetic-in-a-document
pattern this repo exists to stop.

The cases here pin the three properties that make the +/- trustworthy:

  * it is the wobble of the REPORTED figure, not of one replicate
  * turning it on re-slices the existing budget rather than tripling it
  * at reps=1 the numbers are exactly what the pre-replicate code produced
"""
import json
import math
import os
import random

import pytest

from conftest import DECKS, FIXTURES, deck_args, run_cli


def _deck(mm, name):
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, f"{name}.txt"))
    with open(os.path.join(FIXTURES, f"{name}.scry.json"), encoding="utf-8") as f:
        scry = json.load(f)
    return cmdr, entries, scry


# --- splitting the budget ---------------------------------------------
@pytest.mark.parametrize("total,reps", [(20000, 3), (8000, 3), (20000, 1),
                                        (100, 7), (10, 10)],
                         ids=["budget/20000 over 3", "budget/8000 over 3",
                              "budget/20000 over 1", "budget/100 over 7",
                              "budget/10 over 10"])
def test_split_budget_preserves_the_total(mm, total, reps):
    """The budget is divided, never multiplied.

    If this ever multiplies instead, --trials silently stops meaning what it
    says and every default run gets `reps` times slower -- which is how a
    feature that costs nothing turns into a suite that takes a minute and a
    half.
    """
    parts = mm.split_budget(total, reps)
    assert len(parts) == reps
    assert sum(parts) == total
    assert min(parts) >= 1


def test_split_budget_at_one_rep_is_the_whole_budget(mm):
    """reps=1 hands the entire budget to a single replicate.

    This is what lets the reps=1 case below be a byte-for-byte comparison
    against the pre-replicate code rather than an approximate one.
    """
    assert mm.split_budget(20000, 1) == [20000]


def test_split_budget_refuses_an_impossible_split(mm):
    """Fail by name rather than running replicates of zero trials.

    playsim over zero trials divides by zero several frames later, which
    reads as a crash in the simulator rather than as "you asked for more
    replicates than you have trials".
    """
    with pytest.raises(SystemExit) as e:
        mm.split_budget(2, 3)
    assert "replicate" in str(e.value)


# --- what the +/- actually measures -----------------------------------
def test_spread_is_the_error_of_the_mean_not_of_the_replicates(mm):
    """The reported figure is the MEAN of the replicates, so the bar beside
    it must be the mean's error -- stdev/sqrt(n), not stdev.

    Reporting the replicate spread instead would overstate the uncertainty
    of the printed number by exactly sqrt(n), and would do it plausibly:
    every bar would simply look a bit wider, which is precisely the kind of
    wrong-but-believable figure the golden suite exists to prevent. At n=3
    the factor is 1.73, comfortably enough to change whether a gap reads as
    real.
    """
    vals = [70.0, 72.0, 74.0]
    mean, spread = mm.mean_spread(vals)
    assert mean == pytest.approx(72.0)
    stdev = math.sqrt(sum((v - 72.0) ** 2 for v in vals) / 2)
    assert spread == pytest.approx(stdev / math.sqrt(3))
    assert spread == pytest.approx(2.0 / math.sqrt(3))
    assert spread != pytest.approx(stdev)


def test_spread_of_a_single_replicate_is_zero(mm):
    """One replicate measures no spread -- and must say 0.0 rather than
    guess, raise, or omit the field. `mana --reps=1` still has to print a
    complete row."""
    mean, spread = mm.mean_spread([61.5])
    assert (mean, spread) == (61.5, 0.0)


# --- the re-slicing property ------------------------------------------
def test_reps_split_the_budget_rather_than_multiplying_it(mm, monkeypatch):
    """Three replicates do the work of one run, not three.

    Asserted on what analyse_mana actually passes down, because the wall
    clock is too noisy to assert on and a 3x regression in the default run
    is exactly the kind of thing that gets noticed only in CI months later.
    """
    import mtg_utils.analysis as an

    seen = []
    real = an.playsim_report
    monkeypatch.setattr(
        an, "playsim_report",
        lambda l, a, ds, li, tr, *args, **kw: (seen.append(tr) or
                                               real(l, a, ds, li, tr, *args, **kw)))
    cmdr, entries, scry = _deck(mm, "mono")
    an.analyse_mana(cmdr, entries, scry, sims=90, trials=900, reps=3)

    # playsim_report is called once per replicate per side (play and draw are
    # one call), so the trials handed out must sum to the budget asked for.
    assert len(seen) == 3, seen
    assert sum(seen) == 900, seen


@pytest.mark.parametrize("deck", DECKS)
def test_reps_one_reproduces_the_pre_replicate_measurement(mm, deck):
    """At reps=1 and the same seed, every number is what the code produced
    before replicates existed.

    This is the property that makes the +/- an accounting change rather than
    a change of method. Without it, every figure recorded before this commit
    would silently stop being comparable to one recorded after, and there
    would be no way to tell whether a moved number came from the new error
    bar or from a real change in the model.

    Rebuilt here by calling worst_lines and playsim_report directly, the way
    analyse_mana called them before, rather than by comparing against a
    stored snapshot -- a snapshot would drift with the fixtures.
    """
    cmdr, entries, scry = _deck(mm, deck)
    got = mm.analyse_mana(cmdr, entries, scry, sims=400, trials=800, reps=1)

    names = mm.flat(cmdr, entries)[len(mm.as_cmdrs(cmdr)):]
    lands = mm.build_land_profiles(names, scry)
    accels = mm.build_accel_profiles(names, scry)
    # No rituals here, on purpose: the sources model is not told about them,
    # so these rows must reproduce from lands and accelerants alone. On the
    # two fixtures that run a ritual this is also the assertion that the two
    # models still disagree by design -- feed rituals to `probability` and it
    # fails.
    want_rows = mm.worst_lines(names, scry, lands, accels, 400,
                               random.Random(17), deck_size=len(names))
    assert [r[:5] for r in got["rows"]] == want_rows
    assert all(r[5] == 0.0 for r in got["rows"])

    rituals = mm.build_ritual_profiles(names, scry)
    want = mm.playsim_report(lands, accels, len(names), got["lines"], 800,
                             random.Random(17), rituals=rituals)
    for side in ("play", "draw"):
        for t, pct in want[side]["generic"].items():
            assert got["sim"][side]["generic"][t] == (pct, 0.0), (deck, side, t)
        for label, (pct, turn) in want[side]["lines"].items():
            assert got["sim"][side]["lines"][label] == (pct, turn, 0.0), (deck, label)


def test_replicates_are_actually_different_measurements(mm):
    """Replicate i must use seed+i, not seed.

    Seeding every replicate the same way produces three identical numbers, a
    spread of exactly 0.0 on every line, and an error bar that is present,
    plausible and meaningless -- the tool would print a bar beside every
    figure and read as MORE trustworthy than before while measuring nothing.

    This case exists because every other case in this file passes with a
    constant seed: they check that a bar is printed, that it is formatted,
    and that reps=1 gives 0.0. None of them check that reps=3 gives anything
    else. Found by mutating `random.Random(seed + i)` to `random.Random(seed)`
    and watching the suite stay green.
    """
    cmdr, entries, scry = _deck(mm, "mono")
    got = mm.analyse_mana(cmdr, entries, scry, sims=600, trials=1200, reps=3)

    # `any`, not `all`: a line pinned at 0% or 100% legitimately has no
    # spread, and asserting on every row would make this flaky rather than
    # strict.
    assert any(r[5] > 0 for r in got["rows"]), "every sources-model spread was zero"
    for side in ("play", "draw"):
        generic = got["sim"][side]["generic"].values()
        labelled = got["sim"][side]["lines"].values()
        assert any(sp > 0 for _, sp in generic), f"{side}: every baseline spread was zero"
        assert any(t[2] > 0 for t in labelled), f"{side}: every line spread was zero"


# --- the acceptance criterion, read off the real output ----------------
def _table_lines(out):
    """The two tables that carry probabilities, without their headers."""
    body = out.split("--- sources model (colour), worst lines")[1]
    sources, rest = body.split("--- play simulation", 1)
    sources = [l for l in sources.splitlines()[1:] if l.strip()]
    play = rest.split("Diagnosis")[0].splitlines()
    play = [l for l in play[2:] if l.strip()]
    return sources, play


@pytest.mark.parametrize("deck", DECKS)
def test_every_reported_probability_carries_a_spread(mm, deck, tmp_path):
    """No figure ships unlabelled. This is the acceptance criterion stated
    as a test rather than as a line in a README, because the failure mode is
    a future format change quietly dropping the bar from one column and
    leaving the other three -- which reads as deliberate.
    """
    out = run_cli(mm, deck_args(deck, "mana", ["--trials=900", "--sims=300"]),
                  str(tmp_path))
    sources, play = _table_lines(out)
    assert sources and play, out
    for line in sources + play:
        assert "±" in line, f"{deck}: probability with no spread beside it: {line}"
        # Every percentage on the line must be the left half of a +/- pair:
        # count them, so a column added later without a bar is caught.
        assert line.count("±") == line.count("%"), line


def test_provenance_names_the_seed_and_the_rep_count(mm, tmp_path):
    """A figure copied into a primer has to be reproducible from the output
    alone. Trials were already printed; the seed was not, and there was no
    flag to vary it -- so a reader could not have re-run the number even in
    principle.

    Asserted on each table's OWN header rather than on the output as a whole.
    The two tables are copied separately -- a colour finding and an on-curve
    figure land in different paragraphs of a primer -- so a seed present in
    one header and missing from the other leaves half the report
    unreproducible while a whole-output check still passes.
    """
    out = run_cli(mm, deck_args("mono", "mana", ["--trials=900", "--sims=300",
                                                 "--seed=5", "--reps=3"]),
                  str(tmp_path))
    lines = out.splitlines()
    sources_hdr = next(l for l in lines if "sources model (colour)" in l)
    play_hdr = next(l for l in lines if "--- play simulation" in l)
    for hdr in (sources_hdr, play_hdr):
        assert "seed 5" in hdr, hdr
        assert "3 reps" in hdr, hdr
    assert "300 sims" in sources_hdr
    assert "900 trials" in play_hdr


def test_one_rep_says_rep_not_reps(mm, tmp_path):
    """'1 reps' in a provenance line reads as a bug in the tool, and the
    provenance line is the part people copy."""
    out = run_cli(mm, deck_args("mono", "mana", ["--trials=900", "--sims=300",
                                                 "--reps=1"]),
                  str(tmp_path))
    assert "1 rep," in out and "1 reps" not in out
    sources, play = _table_lines(out)
    assert all("±0.0" in l for l in sources + play), "reps=1 must still print a bar"
