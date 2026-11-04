from pathlib import Path

import pytest

from conftest import CANNED_NARRATIVE, FakeLLM
from logixconfig.graph import MAX_PLANNER_CALLS, Status, build_graph, run_pipeline
from logixconfig.llm import LLMError
from logixconfig.models import Equipment, PlannerOutput

DESCRIPTION = "A crude tank TK-100 with a level transmitter feeds transfer pump P101."


def plan(*items: tuple[str, str], assumptions: list[str] | None = None, unsupported: list[str] | None = None):
    return PlannerOutput(
        equipment=[Equipment(name=name, type=kind, description=f"{name} description") for name, kind in items],
        assumptions=assumptions or [],
        unsupported=unsupported or [],
    )


VALID_PLAN = plan(("P101", "pump"), ("LT101", "level_transmitter"))
INVALID_PLAN = plan(("P101_", "pump"), ("LT101", "level_transmitter"))


def run(fake_llm: FakeLLM, *results: PlannerOutput | LLMError) -> dict:
    fake_llm.queue(*results)
    return run_pipeline(DESCRIPTION, fake_llm)


def test_success(fake_llm: FakeLLM) -> None:
    state = run(fake_llm, VALID_PLAN)
    assert state["status"] is Status.SUCCEEDED
    assert [item.name for item in state["equipment"]] == ["P101", "LT101"]
    assert len(state["tags"]) == 3 + 5
    assert state["narrative"] == CANNED_NARRATIVE
    assert state["issues"] == []
    assert state["retries"] == 0
    assert len(fake_llm.plan_calls) == 1


def test_first_call_gets_no_issues_and_no_previous(fake_llm: FakeLLM) -> None:
    run(fake_llm, VALID_PLAN)
    assert fake_llm.plan_calls == [(DESCRIPTION, [], None)]


def test_narrative_gets_validated_equipment_and_tags_only(fake_llm: FakeLLM) -> None:
    state = run(fake_llm, VALID_PLAN)
    [(equipment, tags)] = fake_llm.narrative_calls
    assert equipment == state["equipment"]
    assert tags == state["tags"]


def test_invalid_then_valid_retries_with_issues_and_previous(fake_llm: FakeLLM) -> None:
    state = run(fake_llm, INVALID_PLAN, VALID_PLAN)
    assert state["status"] is Status.SUCCEEDED
    assert state["retries"] == 1
    assert len(fake_llm.plan_calls) == 2
    _, retry_issues, previous = fake_llm.plan_calls[1]
    assert [(issue.rule, issue.name) for issue in retry_issues] == [("trailing_underscore", "P101_")]
    assert previous == INVALID_PLAN


def test_invalid_three_times_fails_after_three_calls(fake_llm: FakeLLM) -> None:
    state = run(fake_llm, INVALID_PLAN, INVALID_PLAN, INVALID_PLAN)
    assert state["status"] is Status.FAILED
    assert len(fake_llm.plan_calls) == MAX_PLANNER_CALLS == 3
    assert state["retries"] == 2
    assert [issue.rule for issue in state["issues"]] == ["trailing_underscore"]
    assert state["narrative"] == ""
    assert fake_llm.narrative_calls == []


def test_planner_is_never_called_a_fourth_time(fake_llm: FakeLLM) -> None:
    state = run(fake_llm, INVALID_PLAN, INVALID_PLAN, INVALID_PLAN, VALID_PLAN)
    assert state["status"] is Status.FAILED
    assert len(fake_llm.plan_calls) == 3
    assert len(fake_llm.plans) == 1


def test_third_call_can_still_succeed(fake_llm: FakeLLM) -> None:
    state = run(fake_llm, INVALID_PLAN, INVALID_PLAN, VALID_PLAN)
    assert state["status"] is Status.SUCCEEDED
    assert state["retries"] == 2


def test_empty_equipment_fails(fake_llm: FakeLLM) -> None:
    empty = PlannerOutput(equipment=[])
    state = run(fake_llm, empty, empty, empty)
    assert state["status"] is Status.FAILED
    assert [issue.rule for issue in state["issues"]] == ["no_equipment"]
    assert len(fake_llm.plan_calls) == 3


def test_planner_llm_error_fails_cleanly(fake_llm: FakeLLM) -> None:
    state = run(fake_llm, LLMError("OpenAI request timed out"))
    assert state["status"] is Status.FAILED
    [issue] = state["issues"]
    assert issue.rule == "llm_error"
    assert issue.message == "Planner LLM call failed: OpenAI request timed out"
    assert state["tags"] == []
    assert fake_llm.narrative_calls == []


def test_llm_error_on_retry_fails_cleanly(fake_llm: FakeLLM) -> None:
    state = run(fake_llm, INVALID_PLAN, LLMError("rate limited"))
    assert state["status"] is Status.FAILED
    assert [issue.rule for issue in state["issues"]] == ["llm_error"]
    assert len(fake_llm.plan_calls) == 2


def test_narrative_llm_error_fails_cleanly(fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_narrative(equipment, tags):
        raise LLMError("Model refused the request")

    monkeypatch.setattr(fake_llm, "write_narrative", broken_narrative)
    state = run(fake_llm, VALID_PLAN)
    assert state["status"] is Status.FAILED
    assert state["issues"][-1].message == "Narrative LLM call failed: Model refused the request"
    assert len(state["tags"]) == 8


def test_unsupported_and_assumptions_are_carried_through(fake_llm: FakeLLM) -> None:
    result = plan(
        ("P101", "pump"),
        assumptions=["Assumed one transfer pump"],
        unsupported=["mixer M-1", "flow meter"],
    )
    state = run(fake_llm, result)
    assert state["status"] is Status.SUCCEEDED
    assert state["assumptions"] == ["Assumed one transfer pump"]
    assert state["unsupported"] == ["mixer M-1", "flow meter"]


def test_assumptions_come_from_the_final_plan(fake_llm: FakeLLM) -> None:
    first = plan(("P101_", "pump"), assumptions=["first guess"])
    second = plan(("P101", "pump"), assumptions=["corrected guess"])
    state = run(fake_llm, first, second)
    assert state["assumptions"] == ["corrected guess"]
    assert fake_llm.plan_calls[1][2].assumptions == ["first guess"]


def test_tag_errors_from_valid_equipment_trigger_retry(fake_llm: FakeLLM) -> None:
    long_description = plan(("P101", "pump"))
    long_description.equipment[0].description = "x" * 520
    state = run(fake_llm, long_description, VALID_PLAN)
    assert state["status"] is Status.SUCCEEDED
    retry_rules = {issue.rule for issue in fake_llm.plan_calls[1][1]}
    assert retry_rules == {"description_too_long"}


def test_graph_writes_nothing_to_disk(fake_llm: FakeLLM, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    run(fake_llm, VALID_PLAN)
    assert list(tmp_path.iterdir()) == []


def test_graph_has_expected_nodes(fake_llm: FakeLLM) -> None:
    nodes = set(build_graph(fake_llm).get_graph().nodes)
    assert {"plan", "make_tags", "validate", "document"} <= nodes
