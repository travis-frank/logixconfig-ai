"""LangGraph pipeline: description to planned equipment, tags, validation, and a narrative.

The graph only builds data in memory. Writing files is left to the caller.
"""

from enum import Enum
from functools import partial
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from logixconfig.llm import LLM, LLMError
from logixconfig.models import Equipment, PlannerOutput, Tag
from logixconfig.templates import tags_for
from logixconfig.validator import Issue, Severity, has_errors, validate, validate_equipment

MAX_PLANNER_CALLS = 3


class Status(str, Enum):
    PLANNING = "planning"
    PLANNED = "planned"
    RETRYING = "retrying"
    VALID = "valid"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PipelineState(TypedDict):
    description: str
    equipment: list[Equipment]
    tags: list[Tag]
    issues: list[Issue]
    retries: int
    narrative: str
    unsupported: list[str]
    assumptions: list[str]
    status: Status


def initial_state(description: str) -> PipelineState:
    return PipelineState(
        description=description,
        equipment=[],
        tags=[],
        issues=[],
        retries=0,
        narrative="",
        unsupported=[],
        assumptions=[],
        status=Status.PLANNING,
    )


def planner_calls(state: PipelineState) -> int:
    return state["retries"] + 1


def plan_node(state: PipelineState, llm: LLM) -> dict:
    is_retry = state["status"] is Status.RETRYING
    previous = (
        PlannerOutput(equipment=state["equipment"], assumptions=state["assumptions"], unsupported=state["unsupported"])
        if is_retry
        else None
    )
    try:
        result = llm.plan(state["description"], state["issues"] if is_retry else [], previous)
    except LLMError as error:
        return {"status": Status.FAILED, "issues": [llm_issue("Planner", error)]}
    return {
        "equipment": result.equipment,
        "assumptions": result.assumptions,
        "unsupported": result.unsupported,
        "retries": state["retries"] + 1 if is_retry else state["retries"],
        "status": Status.PLANNED,
    }


def make_tags_node(state: PipelineState) -> dict:
    return {"tags": [tag for item in state["equipment"] for tag in tags_for(item)]}


def validate_node(state: PipelineState) -> dict:
    issues = validate_equipment(state["equipment"])
    if not has_errors(issues):
        issues += validate(state["tags"])
    if not has_errors(issues):
        status = Status.VALID
    elif planner_calls(state) < MAX_PLANNER_CALLS:
        status = Status.RETRYING
    else:
        status = Status.FAILED
    return {"issues": issues, "status": status}


def document_node(state: PipelineState, llm: LLM) -> dict:
    try:
        narrative = llm.write_narrative(state["equipment"], state["tags"])
    except LLMError as error:
        return {"status": Status.FAILED, "issues": state["issues"] + [llm_issue("Narrative", error)]}
    return {"narrative": narrative, "status": Status.SUCCEEDED}


def llm_issue(step: str, error: LLMError) -> Issue:
    return Issue(name="", severity=Severity.ERROR, rule="llm_error", message=f"{step} LLM call failed: {error}")


def route_after_plan(state: PipelineState) -> str:
    return END if state["status"] is Status.FAILED else "make_tags"


def route_after_validate(state: PipelineState) -> str:
    routes = {Status.VALID: "document", Status.RETRYING: "plan", Status.FAILED: END}
    return routes[state["status"]]


def build_graph(llm: LLM):
    graph = StateGraph(PipelineState)
    graph.add_node("plan", partial(plan_node, llm=llm))
    graph.add_node("make_tags", make_tags_node)
    graph.add_node("validate", validate_node)
    graph.add_node("document", partial(document_node, llm=llm))
    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", route_after_plan, ["make_tags", END])
    graph.add_edge("make_tags", "validate")
    graph.add_conditional_edges("validate", route_after_validate, ["document", "plan", END])
    graph.add_edge("document", END)
    return graph.compile()


def run_pipeline(description: str, llm: LLM) -> PipelineState:
    return build_graph(llm).invoke(initial_state(description))
