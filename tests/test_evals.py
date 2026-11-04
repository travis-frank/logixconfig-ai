"""Offline checks of the eval cases file and scoring. The real LLM eval run is not part of pytest."""

from collections import Counter
from pathlib import Path

from logixconfig.evals import EvalCase, case_differences, count_differences, load_cases, pass_rate, EvalResult
from logixconfig.graph import Status, initial_state
from logixconfig.models import Equipment, EquipmentType
from logixconfig.validator import Issue, Severity

CASES = Path(__file__).parent.parent / "evals" / "cases.json"


def test_cases_file_has_required_coverage() -> None:
    cases = load_cases(CASES)
    assert len(cases) == 8
    assert len({case.name for case in cases}) == 8
    assert sum(case.expect_unsupported for case in cases) == 2
    ambiguous = [case for case in cases if case.expect_assumption]
    assert len(ambiguous) == 1
    assert "a few pumps" in ambiguous[0].description.lower()


def make_case(**expected) -> EvalCase:
    return EvalCase(name="case", description="d", expected=expected)


def succeeded_state(*types: str, unsupported=(), assumptions=()):
    state = initial_state("d")
    state["equipment"] = [Equipment(name=f"EQ{i}", type=kind) for i, kind in enumerate(types)]
    state["unsupported"] = list(unsupported)
    state["assumptions"] = list(assumptions)
    state["status"] = Status.SUCCEEDED
    return state


def test_exact_counts_pass() -> None:
    assert count_differences(make_case(pump=2), Counter({EquipmentType.PUMP: 2})) == []


def test_count_mismatch_and_unexpected_types_are_reported() -> None:
    counts = Counter({EquipmentType.PUMP: 3, EquipmentType.VALVE: 1})
    assert count_differences(make_case(pump=2), counts) == ["pump: expected 2, got 3", "valve: expected 0, got 1"]


def test_range_counts() -> None:
    case = make_case(pump=(2, 3))
    assert count_differences(case, Counter({EquipmentType.PUMP: 3})) == []
    assert count_differences(case, Counter({EquipmentType.PUMP: 4})) == ["pump: expected 2 to 3, got 4"]


def test_missing_unsupported_and_assumption_are_reported() -> None:
    case = EvalCase(name="c", description="d", expected={"pump": 1}, expect_unsupported=True, expect_assumption=True)
    assert case_differences(case, succeeded_state("pump")) == [
        "expected unsupported items, got none",
        "expected an assumption to be recorded, got none",
    ]
    assert case_differences(case, succeeded_state("pump", unsupported=["heater"], assumptions=["one pump"])) == []


def test_failed_pipeline_is_a_failed_case() -> None:
    state = initial_state("d")
    state["status"] = Status.FAILED
    state["issues"] = [Issue(name="", severity=Severity.ERROR, rule="llm_error", message="timed out")]
    assert case_differences(make_case(pump=1), state) == ["pipeline status failed: timed out"]


def test_pass_rate() -> None:
    results = [EvalResult(name="a", passed=True, differences=[]), EvalResult(name="b", passed=False, differences=["x"])]
    assert pass_rate(results) == 0.5
    assert pass_rate([]) == 0.0
