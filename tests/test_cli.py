import os
from pathlib import Path

import pytest
from lxml import etree

from conftest import CANNED_NARRATIVE, FakeLLM
from logixconfig import cli
from logixconfig.cli import main
from logixconfig.llm import LLMError
from logixconfig.models import Equipment, PlannerOutput

EXAMPLE_CSV = Path(__file__).parent.parent / "examples" / "equipment.csv"
OUTPUT_FILES = {"tags.csv", "docs.md", "io_list.csv", "Skid01.L5X"}


def run(*args: str) -> int:
    return main(["generate", *args])


def write_csv(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "equipment.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_generates_all_files(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run(str(EXAMPLE_CSV), "-o", str(out), "--controller-name", "Skid01") == 0
    assert {path.name for path in out.iterdir()} == OUTPUT_FILES


def test_l5x_contains_all_tags(tmp_path: Path) -> None:
    out = tmp_path / "out"
    run(str(EXAMPLE_CSV), "-o", str(out), "--controller-name", "Skid01")
    root = etree.parse(str(out / "Skid01.L5X")).getroot()
    assert len(root.findall("Controller/Tags/Tag")) == 30
    assert root.find("Controller").get("Name") == "Skid01"


def test_default_profile_is_v24(tmp_path: Path) -> None:
    out = tmp_path / "out"
    run(str(EXAMPLE_CSV), "-o", str(out), "--controller-name", "Skid01")
    root = etree.parse(str(out / "Skid01.L5X")).getroot()
    controller = root.find("Controller")
    assert root.get("SoftwareRevision") == "24.02"
    assert (controller.get("MajorRev"), controller.get("MinorRev")) == ("24", "11")


def test_revision_and_chassis_options(tmp_path: Path) -> None:
    out = tmp_path / "out"
    run(
        str(EXAMPLE_CSV), "-o", str(out), "--controller-name", "Skid01",
        "--major-rev", "33", "--minor-rev", "2", "--bus-size", "7",
    )
    root = etree.parse(str(out / "Skid01.L5X")).getroot()
    controller = root.find("Controller")
    assert root.get("SoftwareRevision") == "33.00"
    assert (controller.get("MajorRev"), controller.get("MinorRev")) == ("33", "2")
    assert controller.find("Modules/Module/Ports/Port/Bus").get("Size") == "7"


def test_mismatched_software_revision_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    code = run(str(EXAMPLE_CSV), "-o", str(out), "--controller-name", "Skid01", "--software-revision", "32.00")
    assert code == 1
    assert not out.exists()
    assert "does not match" in capsys.readouterr().err


def test_no_descriptions_option(tmp_path: Path) -> None:
    out = tmp_path / "out"
    run(str(EXAMPLE_CSV), "-o", str(out), "--controller-name", "Skid01", "--no-descriptions")
    root = etree.parse(str(out / "Skid01.L5X")).getroot()
    assert root.findall(".//Tag/Description") == []
    assert "run command" in (out / "tags.csv").read_text(encoding="utf-8")


def test_validation_errors_exit_1_and_write_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_path = write_csv(tmp_path, "name,type,description\nP101,pump,A\nP101,pump,B\n")
    out = tmp_path / "out"
    assert run(str(csv_path), "-o", str(out), "--controller-name", "Skid01") == 1
    assert not out.exists()
    stderr = capsys.readouterr().err
    assert "error: [duplicate]" in stderr
    assert "no files written" in stderr


def test_invalid_controller_name_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    assert run(str(EXAMPLE_CSV), "-o", str(out), "--controller-name", "Skid 01") == 1
    assert not out.exists()
    assert "Controller name 'Skid 01'" in capsys.readouterr().err


def test_bad_csv_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_path = write_csv(tmp_path, "name,type,description\nM101,mixer,Mixer\n")
    out = tmp_path / "out"
    assert run(str(csv_path), "-o", str(out), "--controller-name", "Skid01") == 1
    assert not out.exists()
    assert "unknown equipment type 'mixer'" in capsys.readouterr().err


def test_missing_csv_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    assert run(str(tmp_path / "nope.csv"), "-o", str(out), "--controller-name", "Skid01") == 1
    assert not out.exists()
    assert "error:" in capsys.readouterr().err


def test_success_message_goes_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(str(EXAMPLE_CSV), "-o", str(tmp_path / "out"), "--controller-name", "Skid01")
    captured = capsys.readouterr()
    assert "Wrote 30 tags for 8 equipment items" in captured.out
    assert captured.err == ""


DESCRIPTION = "Crude tank with a level transmitter and one transfer pump."
VALID_PLAN = PlannerOutput(
    equipment=[
        Equipment(name="P101", type="pump", description="Transfer pump"),
        Equipment(name="LT101", type="level_transmitter", description="Tank level"),
    ],
    assumptions=["Assumed one transfer pump"],
    unsupported=["electric heater"],
)
INVALID_PLAN = PlannerOutput(equipment=[Equipment(name="P101_", type="pump")])


def describe(*args: str) -> int:
    return main(["describe", DESCRIPTION, *args])


@pytest.fixture
def use_fake_llm(fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    monkeypatch.setattr(cli, "create_llm", lambda: fake_llm)
    return fake_llm


def test_describe_writes_all_files(tmp_path: Path, use_fake_llm: FakeLLM) -> None:
    use_fake_llm.queue(VALID_PLAN)
    out = tmp_path / "out"
    assert describe("-o", str(out), "--controller-name", "Skid01") == 0
    assert {path.name for path in out.iterdir()} == OUTPUT_FILES
    root = etree.parse(str(out / "Skid01.L5X")).getroot()
    assert len(root.findall("Controller/Tags/Tag")) == 3 + 5


def test_describe_adds_narrative_to_docs(tmp_path: Path, use_fake_llm: FakeLLM) -> None:
    use_fake_llm.queue(VALID_PLAN)
    out = tmp_path / "out"
    describe("-o", str(out), "--controller-name", "Skid01")
    docs = (out / "docs.md").read_text(encoding="utf-8")
    assert "## Control narrative" in docs
    assert docs.rstrip().endswith(CANNED_NARRATIVE)


def test_generate_docs_have_no_narrative_section(tmp_path: Path) -> None:
    out = tmp_path / "out"
    run(str(EXAMPLE_CSV), "-o", str(out), "--controller-name", "Skid01")
    assert "Control narrative" not in (out / "docs.md").read_text(encoding="utf-8")


def test_describe_prints_assumptions_and_unsupported(
    tmp_path: Path, use_fake_llm: FakeLLM, capsys: pytest.CaptureFixture[str]
) -> None:
    use_fake_llm.queue(VALID_PLAN)
    describe("-o", str(tmp_path / "out"), "--controller-name", "Skid01")
    stdout = capsys.readouterr().out
    assert "Assumptions:\n  - Assumed one transfer pump" in stdout
    assert "Unsupported (not generated):\n  - electric heater" in stdout


def test_describe_prints_none_when_lists_are_empty(
    tmp_path: Path, use_fake_llm: FakeLLM, capsys: pytest.CaptureFixture[str]
) -> None:
    use_fake_llm.queue(PlannerOutput(equipment=VALID_PLAN.equipment))
    describe("-o", str(tmp_path / "out"))
    assert "Assumptions:\n  - none" in capsys.readouterr().out


def test_describe_default_controller_name(tmp_path: Path, use_fake_llm: FakeLLM) -> None:
    use_fake_llm.queue(VALID_PLAN)
    out = tmp_path / "out"
    describe("-o", str(out))
    assert (out / "Controller1.L5X").exists()


def test_describe_failure_prints_issues_and_writes_nothing(
    tmp_path: Path, use_fake_llm: FakeLLM, capsys: pytest.CaptureFixture[str]
) -> None:
    use_fake_llm.queue(INVALID_PLAN, INVALID_PLAN, INVALID_PLAN)
    out = tmp_path / "out"
    assert describe("-o", str(out)) == 1
    assert not out.exists()
    stderr = capsys.readouterr().err
    assert "error: [trailing_underscore] Equipment ID 'P101_'" in stderr
    assert "no files written" in stderr
    assert len(use_fake_llm.plan_calls) == 3


def test_describe_llm_error_writes_nothing(
    tmp_path: Path, use_fake_llm: FakeLLM, capsys: pytest.CaptureFixture[str]
) -> None:
    use_fake_llm.queue(LLMError("OpenAI request timed out"))
    out = tmp_path / "out"
    assert describe("-o", str(out)) == 1
    assert not out.exists()
    assert "Planner LLM call failed: OpenAI request timed out" in capsys.readouterr().err


def test_describe_invalid_controller_name_skips_llm(
    tmp_path: Path, use_fake_llm: FakeLLM, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    assert describe("-o", str(out), "--controller-name", "Skid 01") == 1
    assert not out.exists()
    assert use_fake_llm.plan_calls == []
    assert "Controller name 'Skid 01'" in capsys.readouterr().err


def test_describe_missing_env_vars_is_a_clear_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    assert describe("-o", str(out)) == 1
    assert not out.exists()
    stderr = capsys.readouterr().err
    assert "OPENAI_MODEL is not set" in stderr
    assert "OPENAI_MODEL and OPENAI_API_KEY in your environment or .env" in stderr


def test_main_does_not_load_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".env").write_text("OPENAI_MODEL=from-dotenv\nOPENAI_API_KEY=sk-from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert describe("-o", str(tmp_path / "out")) == 1
    assert "OPENAI_MODEL is not set" in capsys.readouterr().err


def test_entry_loads_dotenv_without_overriding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("OPENAI_MODEL=from-dotenv\nOPENAI_API_KEY=sk-from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_MODEL", "from-shell")
    seen = {}

    def fake_main() -> int:
        seen["model"] = os.environ.get("OPENAI_MODEL")
        seen["key_loaded"] = os.environ.get("OPENAI_API_KEY") == "sk-from-dotenv"
        return 0

    monkeypatch.setattr(cli, "main", fake_main)
    with pytest.raises(SystemExit) as exit_info:
        cli.entry()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert exit_info.value.code == 0
    assert seen == {"model": "from-shell", "key_loaded": True}


def test_missing_required_option_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(str(EXAMPLE_CSV))
    assert exit_info.value.code == 2
