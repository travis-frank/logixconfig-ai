from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from lxml import etree
from sqlalchemy.orm import Session, sessionmaker

from conftest import CANNED_NARRATIVE, FakeLLM
from logixconfig import api, db
from logixconfig.llm import LLMError
from logixconfig.models import Equipment, PlannerOutput

VALID_PLAN = PlannerOutput(
    equipment=[
        Equipment(name="P101", type="pump", description="Transfer pump"),
        Equipment(name="LT101", type="level_transmitter", description="Tank 1 level transmitter"),
    ],
    assumptions=["Assumed one transfer pump"],
    unsupported=["tank"],
)
INVALID_PLAN = PlannerOutput(equipment=[Equipment(name="P101_", type="pump")])
DESCRIPTION = "Tank 1 has a level transmitter and one transfer pump."
FAKE_KEY = "sk-test-never-return-0123456789abcdef"


@pytest.fixture(autouse=True)
def no_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(api.TOKEN_ENV_VAR, raising=False)


@pytest.fixture
def sessions() -> sessionmaker[Session]:
    engine = db.make_engine("sqlite://")
    db.init_db(engine)
    return db.session_factory(engine)


@pytest.fixture
def client(sessions: sessionmaker[Session], fake_llm: FakeLLM) -> Iterator[TestClient]:
    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    api.app.dependency_overrides[api.get_session] = override_session
    api.app.dependency_overrides[api.get_llm] = lambda: fake_llm
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def generate(client: TestClient, **body) -> dict:
    response = client.post("/generate", json={"description": DESCRIPTION, **body})
    assert response.status_code == 200, response.text
    return response.json()


def row_count(sessions: sessionmaker[Session]) -> int:
    with sessions() as session:
        return session.query(db.GenerationRow).count()


def test_generate_success(client: TestClient, fake_llm: FakeLLM) -> None:
    fake_llm.queue(VALID_PLAN)
    body = generate(client, controller_name="Skid01")
    assert body["status"] == "succeeded"
    assert [item["name"] for item in body["equipment"]] == ["P101", "LT101"]
    assert len(body["tags"]) == 3 + 5
    assert body["assumptions"] == ["Assumed one transfer pump"]
    assert body["unsupported"] == ["tank"]
    assert body["narrative"] == CANNED_NARRATIVE
    assert body["files"] == ["tags.csv", "docs.md", "io_list.csv", "Skid01.L5X"]
    assert fake_llm.plan_calls[0][0] == DESCRIPTION


def test_generate_default_controller_name(client: TestClient, fake_llm: FakeLLM) -> None:
    fake_llm.queue(VALID_PLAN)
    assert generate(client)["controller_name"] == "Controller1"


def test_generate_failure_returns_422_with_issues(
    client: TestClient, fake_llm: FakeLLM, sessions: sessionmaker[Session]
) -> None:
    fake_llm.queue(INVALID_PLAN, INVALID_PLAN, INVALID_PLAN)
    response = client.post("/generate", json={"description": DESCRIPTION})
    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "failed"
    assert any(issue["rule"] == "trailing_underscore" for issue in body["issues"])
    assert "tags" not in body and "narrative" not in body

    with sessions() as session:
        stored = db.get_generation(session, body["id"])
    assert (stored.status, stored.equipment, stored.tags, stored.narrative) == ("failed", [], [], None)
    assert stored.issues


def test_failed_generation_has_no_downloads(client: TestClient, fake_llm: FakeLLM) -> None:
    fake_llm.queue(LLMError("OpenAI request timed out"))
    body = client.post("/generate", json={"description": DESCRIPTION}).json()
    assert "Planner LLM call failed: OpenAI request timed out" in body["issues"][0]["message"]
    assert client.get(f"/generations/{body['id']}").json()["files"] == []
    assert client.get(f"/generations/{body['id']}/download/tags.csv").status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"description": ""},
        {"description": "   \n "},
        {"description": "x" * 2001},
        {},
        {"description": DESCRIPTION, "controller_name": "Skid 01"},
        {"description": DESCRIPTION, "controller_name": "1Skid"},
        {"description": DESCRIPTION, "controller_name": "Skid__01"},
        {"description": DESCRIPTION, "controller_name": "C" * 41},
        {"description": DESCRIPTION, "extra": "field"},
    ],
)
def test_generate_rejects_invalid_requests(
    client: TestClient, fake_llm: FakeLLM, sessions: sessionmaker[Session], body: dict
) -> None:
    assert client.post("/generate", json=body).status_code == 422
    assert fake_llm.plan_calls == []
    assert row_count(sessions) == 0


def test_description_at_limit_is_accepted(client: TestClient, fake_llm: FakeLLM) -> None:
    fake_llm.queue(VALID_PLAN)
    assert client.post("/generate", json={"description": "x" * 2000}).status_code == 200


def test_get_generation(client: TestClient, fake_llm: FakeLLM) -> None:
    fake_llm.queue(VALID_PLAN)
    created = generate(client)
    response = client.get(f"/generations/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_get_unknown_generation_is_404(client: TestClient) -> None:
    assert client.get("/generations/00000000-0000-4000-8000-000000000000").status_code == 404
    assert client.get("/generations/00000000-0000-4000-8000-000000000000/download/tags.csv").status_code == 404


def test_downloads_match_cli_writers(client: TestClient, fake_llm: FakeLLM) -> None:
    fake_llm.queue(VALID_PLAN)
    generation_id = generate(client, controller_name="Skid01")["id"]
    base = f"/generations/{generation_id}/download"

    tags_csv = client.get(f"{base}/tags.csv")
    assert tags_csv.status_code == 200
    assert tags_csv.headers["content-type"].startswith("text/csv")
    assert tags_csv.headers["content-disposition"] == 'attachment; filename="tags.csv"'
    assert tags_csv.text.splitlines()[1] == "P101_Run_Cmd,BOOL,Transfer pump run command,P101"

    docs = client.get(f"{base}/docs.md").text
    assert "## Control narrative" in docs and CANNED_NARRATIVE in docs

    assert client.get(f"{base}/io_list.csv").text.splitlines()[1] == "P101_Run_Cmd,DO,Transfer pump run command"

    l5x = client.get(f"{base}/Skid01.L5X")
    root = etree.fromstring(l5x.content)
    assert root.find("Controller").get("Name") == "Skid01"
    assert len(root.findall("Controller/Tags/Tag")) == 8


@pytest.mark.parametrize(
    "filename",
    [
        "secrets.txt",
        "Controller1.L5X",
        "TAGS.CSV",
        "..%2Ftags.csv",
        "..%2F..%2Fpyproject.toml",
        "%2E%2E%2F.env",
        "tags.csv%00",
    ],
)
def test_download_whitelist(client: TestClient, fake_llm: FakeLLM, filename: str) -> None:
    fake_llm.queue(VALID_PLAN)
    generation_id = generate(client, controller_name="Skid01")["id"]
    assert client.get(f"/generations/{generation_id}/download/{filename}").status_code == 404


def test_download_path_traversal_does_not_route(client: TestClient, fake_llm: FakeLLM) -> None:
    fake_llm.queue(VALID_PLAN)
    generation_id = generate(client)["id"]
    response = client.get(f"/generations/{generation_id}/download/../../../pyproject.toml")
    assert response.status_code == 404
    assert "logixconfig" not in response.text


def test_token_required_when_set(client: TestClient, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(api.TOKEN_ENV_VAR, "s3cret-token")
    fake_llm.queue(VALID_PLAN)
    body = {"description": DESCRIPTION}

    assert client.post("/generate", json=body).status_code == 401
    assert client.post("/generate", json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/generate", json=body, headers={"Authorization": "s3cret-token"}).status_code == 401
    assert fake_llm.plan_calls == []

    ok = client.post("/generate", json=body, headers={"Authorization": "Bearer s3cret-token"})
    assert ok.status_code == 200
    generation_id = ok.json()["id"]
    assert client.get(f"/generations/{generation_id}").status_code == 401
    assert client.get(f"/generations/{generation_id}/download/tags.csv").status_code == 401
    assert "s3cret-token" not in ok.text


def test_no_token_needed_when_unset(client: TestClient, fake_llm: FakeLLM) -> None:
    fake_llm.queue(VALID_PLAN)
    assert client.post("/generate", json={"description": DESCRIPTION}).status_code == 200


def test_missing_llm_config_is_503(sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    api.app.dependency_overrides[api.get_session] = override_session
    try:
        response = TestClient(api.app).post("/generate", json={"description": DESCRIPTION})
    finally:
        api.app.dependency_overrides.clear()
    assert response.status_code == 503
    assert "OPENAI_MODEL is not set" in response.json()["detail"]
    assert FAKE_KEY not in response.text


def test_no_openai_key_in_any_response(client: TestClient, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    fake_llm.queue(VALID_PLAN, INVALID_PLAN, INVALID_PLAN, INVALID_PLAN)
    ok = client.post("/generate", json={"description": DESCRIPTION})
    failed = client.post("/generate", json={"description": DESCRIPTION})
    generation_id = ok.json()["id"]
    responses = [
        ok,
        failed,
        client.post("/generate", json={"description": ""}),
        client.get(f"/generations/{generation_id}"),
        client.get("/generations/missing"),
        *(client.get(f"/generations/{generation_id}/download/{name}") for name in ok.json()["files"]),
    ]
    for response in responses:
        assert FAKE_KEY not in response.text
        assert FAKE_KEY not in str(response.headers)


def test_default_host_is_loopback() -> None:
    assert api.DEFAULT_HOST == "127.0.0.1"
