from types import SimpleNamespace
from typing import Any

import httpx2
import openai
import pytest

from conftest import CANNED_NARRATIVE, FakeLLM
from logixconfig.llm import (
    LLM,
    LLMError,
    OpenAILLM,
    PlannedEquipment,
    PlannerResponse,
    remove_em_dashes,
)
from logixconfig.models import Equipment, EquipmentType, PlannerOutput
from logixconfig.templates import tags_for
from logixconfig.validator import validate_equipment

FAKE_KEY = "sk-test-not-a-real-key-1234"
REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/responses")
PUMP = Equipment(name="P101", type="pump", description="Crude transfer pump A")


def plan_result(*names: str) -> PlannerOutput:
    return PlannerOutput(equipment=[Equipment(name=name, type="pump") for name in names])


def planner_response(*names: str) -> PlannerResponse:
    return PlannerResponse(
        equipment=[PlannedEquipment(name=name, type=EquipmentType.PUMP, description="Pump") for name in names],
        assumptions=["Assumed one pump"],
        unsupported=["mixer"],
    )


def api_response(parsed: Any = None, text: str = "", status: str = "completed", content_type: str = "output_text"):
    content = SimpleNamespace(type=content_type, refusal="I can't help with that")
    message = SimpleNamespace(type="message", content=[content])
    return SimpleNamespace(
        status=status,
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        output=[message],
        output_parsed=parsed,
        output_text=text,
    )


class FakeResponses:
    """Records calls and returns or raises queued results, in order."""

    def __init__(self, *results: Any) -> None:
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    def _next(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    parse = _next
    create = _next


def openai_llm(*results: Any) -> tuple[OpenAILLM, FakeResponses]:
    responses = FakeResponses(*results)
    return OpenAILLM(SimpleNamespace(responses=responses), model="test-model"), responses


def bad_request(message: str, param: str | None = None) -> openai.BadRequestError:
    return openai.BadRequestError(message, response=httpx2.Response(400, request=REQUEST), body={"param": param})


# FakeLLM


def test_fake_llm_satisfies_the_protocol(fake_llm: FakeLLM) -> None:
    assert isinstance(fake_llm, LLM)


def test_fake_llm_returns_queued_plans_in_order(fake_llm: FakeLLM) -> None:
    fake_llm.queue(plan_result("P101_"), plan_result("P101"))
    issues = validate_equipment(plan_result("P101_").equipment)
    assert fake_llm.plan("desc", []).equipment[0].name == "P101_"
    assert fake_llm.plan("desc", issues).equipment[0].name == "P101"
    assert fake_llm.plan_calls == [("desc", [], None), ("desc", issues, None)]


def test_fake_llm_raises_queued_errors(fake_llm: FakeLLM) -> None:
    fake_llm.queue(LLMError("boom"))
    with pytest.raises(LLMError, match="boom"):
        fake_llm.plan("desc", [])


def test_fake_llm_fails_loudly_when_queue_is_empty(fake_llm: FakeLLM) -> None:
    with pytest.raises(AssertionError):
        fake_llm.plan("desc", [])


def test_fake_llm_narrative_records_inputs(fake_llm: FakeLLM) -> None:
    tags = tags_for(PUMP)
    assert fake_llm.write_narrative([PUMP], tags) == CANNED_NARRATIVE
    assert fake_llm.narrative_calls == [([PUMP], tags)]


# Environment configuration


def test_missing_model_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    with pytest.raises(LLMError, match="OPENAI_MODEL is not set") as error:
        OpenAILLM.from_env()
    assert FAKE_KEY not in str(error.value)


def test_missing_key_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    with pytest.raises(LLMError, match="OPENAI_API_KEY is not set"):
        OpenAILLM.from_env()


def test_blank_values_count_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "   ")
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    with pytest.raises(LLMError, match="OPENAI_MODEL is not set"):
        OpenAILLM.from_env()


def test_both_missing_reports_model_first() -> None:
    with pytest.raises(LLMError, match="OPENAI_MODEL"):
        OpenAILLM.from_env()


def test_from_env_builds_client_without_exposing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    llm = OpenAILLM.from_env(timeout=5.0)
    assert repr(llm) == "OpenAILLM(model='test-model')"
    assert FAKE_KEY not in repr(llm)
    assert llm._client.timeout == 5.0


# OpenAI implementation, with a fake client (no network)


def test_plan_returns_planner_output() -> None:
    llm, responses = openai_llm(api_response(parsed=planner_response("P101", "P102")))
    result = llm.plan("Two pumps", [])
    assert [item.name for item in result.equipment] == ["P101", "P102"]
    assert result.assumptions == ["Assumed one pump"]
    assert result.unsupported == ["mixer"]
    call = responses.calls[0]
    assert call["model"] == "test-model"
    assert call["temperature"] == 0
    assert call["store"] is False
    assert call["text_format"] is PlannerResponse


def test_plan_sends_issues_on_retry() -> None:
    llm, responses = openai_llm(api_response(parsed=planner_response("P101")))
    issues = validate_equipment([Equipment(name="P101_", type="pump")])
    llm.plan("One pump", issues)
    assert issues[0].message in responses.calls[0]["input"][-1]["content"]


def test_plan_sends_previous_output_on_retry() -> None:
    llm, responses = openai_llm(api_response(parsed=planner_response("P101")))
    previous = plan_result("P101_")
    llm.plan("One pump", validate_equipment(previous.equipment), previous)
    roles = [message["role"] for message in responses.calls[0]["input"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert '"P101_"' in responses.calls[0]["input"][2]["content"]


def test_planner_schema_has_no_unsupported_constraints() -> None:
    schema_text = str(PlannerResponse.model_json_schema())
    for keyword in ("minLength", "maxLength", "default"):
        assert keyword not in schema_text


def test_temperature_is_dropped_if_model_rejects_it() -> None:
    llm, responses = openai_llm(
        bad_request("Unsupported parameter: 'temperature'", param="temperature"),
        api_response(parsed=planner_response("P101")),
    )
    llm.plan("One pump", [])
    assert "temperature" in responses.calls[0]
    assert "temperature" not in responses.calls[1]


def test_other_bad_requests_are_not_retried() -> None:
    llm, responses = openai_llm(bad_request("Invalid schema", param="text.format"))
    with pytest.raises(LLMError, match="BadRequestError"):
        llm.plan("One pump", [])
    assert len(responses.calls) == 1


def test_refusal_becomes_llm_error() -> None:
    llm, _ = openai_llm(api_response(content_type="refusal"))
    with pytest.raises(LLMError, match="refused"):
        llm.plan("One pump", [])


def test_incomplete_response_becomes_llm_error() -> None:
    llm, _ = openai_llm(api_response(status="incomplete"))
    with pytest.raises(LLMError, match="incomplete .*max_output_tokens"):
        llm.plan("One pump", [])


def test_missing_parsed_output_becomes_llm_error() -> None:
    llm, _ = openai_llm(api_response(parsed=None))
    with pytest.raises(LLMError, match="no structured output"):
        llm.plan("One pump", [])


def test_parse_failure_becomes_llm_error() -> None:
    llm, _ = openai_llm(ValueError("Invalid JSON"))
    with pytest.raises(LLMError, match="could not be parsed"):
        llm.plan("One pump", [])


def test_empty_equipment_name_from_model_becomes_llm_error() -> None:
    llm, _ = openai_llm(api_response(parsed=planner_response("  ")))
    with pytest.raises(LLMError, match="invalid equipment"):
        llm.plan("One pump", [])


def test_timeout_becomes_llm_error() -> None:
    llm, _ = openai_llm(openai.APITimeoutError(request=REQUEST))
    with pytest.raises(LLMError, match="timed out"):
        llm.plan("One pump", [])


def test_authentication_error_never_echoes_the_key() -> None:
    error = openai.AuthenticationError(
        f"Incorrect API key provided: {FAKE_KEY}", response=httpx2.Response(401, request=REQUEST), body=None
    )
    llm, _ = openai_llm(error)
    with pytest.raises(LLMError) as raised:
        llm.plan("One pump", [])
    assert FAKE_KEY not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__


def test_other_api_errors_are_redacted() -> None:
    llm, _ = openai_llm(bad_request(f"Something mentioned {FAKE_KEY}"))
    with pytest.raises(LLMError) as raised:
        llm.plan("One pump", [])
    assert FAKE_KEY not in str(raised.value)
    assert "sk-[redacted]" in str(raised.value)


def test_write_narrative_returns_text_without_em_dashes() -> None:
    llm, responses = openai_llm(api_response(text="P101 runs \u2014 when commanded."))
    assert llm.write_narrative([PUMP], tags_for(PUMP)) == "P101 runs, when commanded."
    assert responses.calls[0]["temperature"] == 0
    assert "text_format" not in responses.calls[0]


def test_empty_narrative_becomes_llm_error() -> None:
    llm, _ = openai_llm(api_response(text="   "))
    with pytest.raises(LLMError, match="empty"):
        llm.write_narrative([PUMP], tags_for(PUMP))


def test_narrative_refusal_becomes_llm_error() -> None:
    llm, _ = openai_llm(api_response(content_type="refusal"))
    with pytest.raises(LLMError, match="refused"):
        llm.write_narrative([PUMP], tags_for(PUMP))


def test_remove_em_dashes() -> None:
    assert remove_em_dashes("A\u2014B and C \u2014 D") == "A, B and C, D"
