"""Run the planner pipeline against evaluation cases using the real LLM.

Usage: python -m logixconfig.evals [--cases evals/cases.json] [--runs 3]

Each case runs N times and passes only if every run passes. This costs API calls and is not part of pytest.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel

from logixconfig.graph import PipelineState, Status, run_pipeline
from logixconfig.llm import LLM, LLMError, OpenAILLM
from logixconfig.models import EquipmentType

DEFAULT_CASES = Path("evals/cases.json")


class EvalCase(BaseModel):
    name: str
    description: str
    expected: dict[EquipmentType, int | tuple[int, int]]
    expect_unsupported: bool = False
    expect_assumption: bool = False


class EvalResult(BaseModel):
    name: str
    passed: bool
    differences: list[str]


def load_cases(path: Path) -> list[EvalCase]:
    return [EvalCase.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]


def count_by_type(state: PipelineState) -> Counter[EquipmentType]:
    return Counter(item.type for item in state["equipment"])


def count_differences(case: EvalCase, counts: Counter[EquipmentType]) -> list[str]:
    differences = []
    for equipment_type in EquipmentType:
        expected = case.expected.get(equipment_type, 0)
        low, high = expected if isinstance(expected, tuple) else (expected, expected)
        actual = counts.get(equipment_type, 0)
        if not low <= actual <= high:
            wanted = f"{low} to {high}" if low != high else str(low)
            differences.append(f"{equipment_type.value}: expected {wanted}, got {actual}")
    return differences


def case_differences(case: EvalCase, state: PipelineState) -> list[str]:
    if state["status"] is not Status.SUCCEEDED:
        reasons = "; ".join(issue.message for issue in state["issues"]) or "no issues reported"
        return [f"pipeline status {state['status'].value}: {reasons}"]
    differences = count_differences(case, count_by_type(state))
    if case.expect_unsupported and not state["unsupported"]:
        differences.append("expected unsupported items, got none")
    if case.expect_assumption and not state["assumptions"]:
        differences.append("expected an assumption to be recorded, got none")
    return differences


def run_case(case: EvalCase, llm: LLM) -> EvalResult:
    differences = case_differences(case, run_pipeline(case.description, llm))
    return EvalResult(name=case.name, passed=not differences, differences=differences)


class CaseSummary(BaseModel):
    name: str
    runs: list[EvalResult]

    @property
    def passes(self) -> int:
        return sum(run.passed for run in self.runs)

    @property
    def passed(self) -> bool:
        return bool(self.runs) and self.passes == len(self.runs)


def run_case_repeatedly(case: EvalCase, llm: LLM, runs: int) -> CaseSummary:
    return CaseSummary(name=case.name, runs=[run_case(case, llm) for _ in range(runs)])


def print_summary(summary: CaseSummary) -> None:
    print(f"{'PASS' if summary.passed else 'FAIL'}  {summary.name} {summary.passes}/{len(summary.runs)}")
    for number, run in enumerate(summary.runs, start=1):
        for difference in run.differences:
            print(f"      run {number}: {difference}")


def pass_rate(results: list[EvalResult]) -> float:
    return sum(result.passed for result in results) / len(results) if results else 0.0


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m logixconfig.evals", description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="Path to the cases JSON file")
    parser.add_argument("--runs", type=positive_int, default=3, help="Runs per case (default 3)")
    args = parser.parse_args(argv)

    load_dotenv(find_dotenv(usecwd=True), override=False)
    try:
        llm = OpenAILLM.from_env()
    except LLMError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    summaries = []
    for case in load_cases(args.cases):
        summary = run_case_repeatedly(case, llm, args.runs)
        print_summary(summary)
        summaries.append(summary)

    all_runs = [run for summary in summaries for run in summary.runs]
    runs_passed = sum(run.passed for run in all_runs)
    cases_passed = sum(summary.passed for summary in summaries)
    print(f"\nRuns passed {runs_passed}/{len(all_runs)} ({pass_rate(all_runs):.0%})")
    print(f"Cases passed (all {args.runs} runs) {cases_passed}/{len(summaries)}")
    return 0 if cases_passed == len(summaries) else 1


if __name__ == "__main__":
    sys.exit(main())
