"""LLM interface for planning equipment and writing control narratives, plus an OpenAI implementation."""

import os
import re
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

import openai
from pydantic import BaseModel, ValidationError

from logixconfig.models import Equipment, EquipmentType, PlannerOutput, Tag
from logixconfig.prompts import narrative_messages, planner_messages
from logixconfig.validator import Issue

MODEL_ENV_VAR = "OPENAI_MODEL"
API_KEY_ENV_VAR = "OPENAI_API_KEY"
REQUEST_TIMEOUT_SECONDS = 60.0

_KEY_LIKE = re.compile(r"sk-[A-Za-z0-9_\-*]+")
_EM_DASH = re.compile(r"\s*\u2014\s*")


class LLMError(Exception):
    """Any failure getting a usable answer from the LLM: configuration, API, parsing, or refusal."""


@runtime_checkable
class LLM(Protocol):
    def plan(self, description: str, issues: list[Issue]) -> PlannerOutput: ...

    def write_narrative(self, equipment: list[Equipment], tags: list[Tag]) -> str: ...


# Structured output schemas must not use minLength or field defaults, so the model fills
# this plain shape and the result is converted to Equipment afterwards.
class PlannedEquipment(BaseModel):
    name: str
    type: EquipmentType
    description: str


class PlannerResponse(BaseModel):
    equipment: list[PlannedEquipment]
    assumptions: list[str]
    unsupported: list[str]


def to_planner_output(response: PlannerResponse) -> PlannerOutput:
    try:
        return PlannerOutput(
            equipment=[Equipment(**item.model_dump()) for item in response.equipment],
            assumptions=response.assumptions,
            unsupported=response.unsupported,
        )
    except ValidationError as error:
        raise LLMError(f"Planner returned invalid equipment: {error.error_count()} problem(s)") from None


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise LLMError(f"Environment variable {name} is not set")
    return value


def remove_em_dashes(text: str) -> str:
    return _EM_DASH.sub(", ", text)


def redact(text: str) -> str:
    return _KEY_LIKE.sub("sk-[redacted]", text)


class OpenAILLM:
    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_env(cls, timeout: float = REQUEST_TIMEOUT_SECONDS) -> "OpenAILLM":
        model = require_env(MODEL_ENV_VAR)
        client = openai.OpenAI(api_key=require_env(API_KEY_ENV_VAR), timeout=timeout)
        return cls(client, model)

    def __repr__(self) -> str:
        return f"OpenAILLM(model={self._model!r})"

    def plan(self, description: str, issues: list[Issue]) -> PlannerOutput:
        response = self._request(
            self._client.responses.parse,
            input=planner_messages(description, issues),
            text_format=PlannerResponse,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise LLMError("Planner response contained no structured output")
        return to_planner_output(parsed)

    def write_narrative(self, equipment: list[Equipment], tags: list[Tag]) -> str:
        response = self._request(self._client.responses.create, input=narrative_messages(equipment, tags))
        text = (response.output_text or "").strip()
        if not text:
            raise LLMError("Narrative response was empty")
        return remove_em_dashes(text)

    def _request(self, method: Callable[..., Any], **kwargs: Any) -> Any:
        try:
            response = self._call_with_temperature_fallback(method, **kwargs)
        except openai.AuthenticationError:
            raise LLMError("OpenAI rejected the API key (authentication failed)") from None
        except openai.APITimeoutError:
            raise LLMError("OpenAI request timed out") from None
        except openai.OpenAIError as error:
            raise LLMError(f"OpenAI request failed ({type(error).__name__}): {redact(str(error))}") from None
        except (ValidationError, ValueError):
            raise LLMError("OpenAI response could not be parsed into the expected format") from None
        check_complete(response)
        check_not_refused(response)
        return response

    def _call_with_temperature_fallback(self, method: Callable[..., Any], **kwargs: Any) -> Any:
        try:
            return method(model=self._model, temperature=0, store=False, **kwargs)
        except openai.BadRequestError as error:
            if not _is_unsupported_temperature(error):
                raise
            return method(model=self._model, store=False, **kwargs)


def check_complete(response: Any) -> None:
    if getattr(response, "status", None) == "incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None) or "unknown reason"
        raise LLMError(f"OpenAI response was incomplete ({reason})")


def check_not_refused(response: Any) -> None:
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", None) or []:
            if getattr(content, "type", None) == "refusal":
                raise LLMError(f"Model refused the request: {content.refusal}")


def _is_unsupported_temperature(error: openai.BadRequestError) -> bool:
    return error.param == "temperature" or "temperature" in str(error).lower()
