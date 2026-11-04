"""HTTP API for the planner pipeline.

Run with `logixconfig-api` (binds to 127.0.0.1:8000 by default). If LOGIXCONFIG_API_TOKEN
is set, every request must send `Authorization: Bearer <token>`.
"""

import argparse
import logging
import os
import secrets
from collections.abc import Callable, Iterator
from datetime import datetime
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session, sessionmaker

from logixconfig.db import (
    GenerationRecord,
    create_generation,
    get_generation,
    init_db,
    make_engine,
    prune_old,
    session_factory,
)
from logixconfig.graph import Status, run_pipeline
from logixconfig.io import render_docs, render_tags_csv
from logixconfig.io_list import io_rows, render_io_list
from logixconfig.l5x import build_l5x
from logixconfig.llm import LLM, LLMError, OpenAILLM
from logixconfig.models import Equipment, Tag
from logixconfig.validator import Issue, name_issues

logger = logging.getLogger(__name__)

TOKEN_ENV_VAR = "LOGIXCONFIG_API_TOKEN"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_CONTROLLER_NAME = "Controller1"
MAX_DESCRIPTION_LENGTH = 2000


def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get(TOKEN_ENV_VAR)
    if not expected:
        return
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Missing or invalid API token", headers={"WWW-Authenticate": "Bearer"}
        )


app = FastAPI(title="logixconfig-ai", dependencies=[Depends(require_token)])


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_LENGTH)
    controller_name: str = DEFAULT_CONTROLLER_NAME

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description must not be blank")
        return value

    @field_validator("controller_name")
    @classmethod
    def controller_name_is_valid(cls, value: str) -> str:
        issues = name_issues(value, label="Controller name")
        if issues:
            raise ValueError("; ".join(issue.message for issue in issues))
        return value


class GenerationResponse(BaseModel):
    id: str
    created_at: datetime
    controller_name: str
    status: str
    equipment: list[Equipment]
    tags: list[Tag]
    assumptions: list[str]
    unsupported: list[str]
    issues: list[Issue]
    narrative: str | None
    files: list[str]


@lru_cache(maxsize=1)
def default_sessions() -> sessionmaker[Session]:
    engine = make_engine()
    init_db(engine)
    return session_factory(engine)


def get_session() -> Iterator[Session]:
    with default_sessions()() as session:
        yield session


def get_llm() -> LLM:
    try:
        return OpenAILLM.from_env()
    except LLMError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"LLM is not configured: {error}") from None


@app.post("/generate", response_model=GenerationResponse)
def generate(
    request: GenerateRequest, session: Session = Depends(get_session), llm: LLM = Depends(get_llm)
) -> GenerationResponse | JSONResponse:
    state = run_pipeline(request.description, llm)
    succeeded = state["status"] is Status.SUCCEEDED
    record = create_generation(
        session,
        description=request.description,
        controller_name=request.controller_name,
        status=state["status"].value,
        equipment=state["equipment"] if succeeded else [],
        tags=state["tags"] if succeeded else [],
        assumptions=state["assumptions"] or [],
        unsupported=state["unsupported"] or [],
        issues=state["issues"],
        narrative=(state["narrative"] or None) if succeeded else None,
    )
    prune_old(session)
    if not succeeded:
        return failure_response(record)
    return to_response(record)


@app.get("/generations/{generation_id}", response_model=GenerationResponse)
def read_generation(generation_id: str, session: Session = Depends(get_session)) -> GenerationResponse:
    return to_response(require_generation(session, generation_id))


@app.get("/generations/{generation_id}/download/{filename}")
def download(generation_id: str, filename: str, session: Session = Depends(get_session)) -> Response:
    record = require_generation(session, generation_id)
    renderers = download_renderers(record)
    if filename not in renderers:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown file")
    if record.status != Status.SUCCEEDED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Generation failed, no files available")
    render, media_type = renderers[filename]
    return Response(
        render(), media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


def download_renderers(record: GenerationRecord) -> dict[str, tuple[Callable[[], bytes], str]]:
    return {
        "tags.csv": (lambda: render_tags_csv(record.tags).encode(), "text/csv; charset=utf-8"),
        "docs.md": (
            lambda: render_docs(record.equipment, record.tags, record.narrative).encode(),
            "text/markdown; charset=utf-8",
        ),
        "io_list.csv": (lambda: render_io_list(io_rows(record.tags)).encode(), "text/csv; charset=utf-8"),
        f"{record.controller_name}.L5X": (lambda: build_l5x(record.tags, record.controller_name), "application/xml"),
    }


def require_generation(session: Session, generation_id: str) -> GenerationRecord:
    record = get_generation(session, generation_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generation not found")
    return record


def to_response(record: GenerationRecord) -> GenerationResponse:
    files = list(download_renderers(record)) if record.status == Status.SUCCEEDED.value else []
    return GenerationResponse(
        id=record.id,
        created_at=record.created_at,
        controller_name=record.controller_name,
        status=record.status,
        equipment=record.equipment,
        tags=record.tags,
        assumptions=record.assumptions,
        unsupported=record.unsupported,
        issues=record.issues,
        narrative=record.narrative,
        files=files,
    )


def failure_response(record: GenerationRecord) -> JSONResponse:
    content = {
        "detail": "Could not produce a valid equipment list",
        "id": record.id,
        "status": record.status,
        "issues": [issue.model_dump(mode="json") for issue in record.issues],
    }
    return JSONResponse(content, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def main(argv: list[str] | None = None) -> None:
    import uvicorn
    from dotenv import find_dotenv, load_dotenv

    parser = argparse.ArgumentParser(prog="logixconfig-api", description="Run the logixconfig HTTP API.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Address to bind (default {DEFAULT_HOST}, local only)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port (default {DEFAULT_PORT})")
    args = parser.parse_args(argv)

    load_dotenv(find_dotenv(usecwd=True), override=False)
    if args.host != DEFAULT_HOST and not os.environ.get(TOKEN_ENV_VAR):
        logger.warning("Binding to %s without %s set; anyone on the network can call the API", args.host, TOKEN_ENV_VAR)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
