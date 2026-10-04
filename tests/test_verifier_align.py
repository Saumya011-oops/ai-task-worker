from agent.types import Verdict
from agent.verifier import align


def test_reworded_criterion_is_matched_not_failed():
    crit = ["A CSV file exists in `workspace/outputs/` containing all unpaid bills due in October 2026."]
    got = [Verdict(criterion="A CSV file exists in workspace/outputs/ containing all unpaid bills due in October 2026", passed=True, evidence="e")]
    out = align(crit, got)
    assert len(out) == 1 and out[0].passed and out[0].criterion == crit[0]


def test_missing_or_empty_verdicts_fail():
    crit = ["Bill exists with the right amount", "No duplicate exists"]
    assert [v.passed for v in align(crit, [])] == [False, False]                      # empty list is never 'all passed'
    out = align(crit, [Verdict(criterion="no duplicate exists", passed=True, evidence="x")])
    assert [v.passed for v in out] == [False, True]
