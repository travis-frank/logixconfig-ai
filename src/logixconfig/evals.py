"""Run the planner pipeline against evaluation cases using the real LLM.

Usage: python -m logixconfig.evals [--cases evals/cases.json]

Each case runs once. This costs API calls and is not part of pytest.
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


def print_result(result: EvalResult) -> None:
    print(f"{'PASS' if result.passed else 'FAIL'}  {result.name}")
    for difference in result.differences:
        print(f"      {difference}")


def pass_rate(results: list[EvalResult]) -> float:
    return sum(result.passed for result in results) / len(results) if results else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m logixconfig.evals", description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="Path to the cases JSON file")
    args = parser.parse_args(argv)

    load_dotenv(find_dotenv(usecwd=True), override=False)
    try:
        llm = OpenAILLM.from_env()
    except LLMError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    results = []
    for case in load_cases(args.cases):
        result = run_case(case, llm)
        print_result(result)
        results.append(result)
    passed = sum(result.passed for result in results)
    print(f"\nPassed {passed}/{len(results)} ({pass_rate(results):.0%})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
