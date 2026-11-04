from collections import deque

import pytest

from logixconfig.llm import API_KEY_ENV_VAR, MODEL_ENV_VAR, LLMError
from logixconfig.models import Equipment, PlannerOutput, Tag
from logixconfig.validator import Issue

CANNED_NARRATIVE = "Canned control narrative for tests."


class FakeLLM:
    """Offline stand-in for an LLM. Planner results are returned (or raised) in queue order."""

    def __init__(self, plans: list[PlannerOutput | LLMError] | None = None, narrative: str = CANNED_NARRATIVE) -> None:
        self.plans: deque[PlannerOutput | LLMError] = deque(plans or [])
        self.narrative = narrative
        self.plan_calls: list[tuple[str, list[Issue], PlannerOutput | None]] = []
        self.narrative_calls: list[tuple[list[Equipment], list[Tag]]] = []

    def queue(self, *results: PlannerOutput | LLMError) -> None:
        self.plans.extend(results)

    def plan(self, description: str, issues: list[Issue], previous: PlannerOutput | None = None) -> PlannerOutput:
        self.plan_calls.append((description, list(issues), previous))
        if not self.plans:
            raise AssertionError("FakeLLM.plan was called with no queued results")
        result = self.plans.popleft()
        if isinstance(result, LLMError):
            raise result
        return result

    def write_narrative(self, equipment: list[Equipment], tags: list[Tag]) -> str:
        self.narrative_calls.append((list(equipment), list(tags)))
        return self.narrative


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture(autouse=True)
def no_openai_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    monkeypatch.delenv(MODEL_ENV_VAR, raising=False)
