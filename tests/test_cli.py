from pathlib import Path

import pytest
from lxml import etree

from logixconfig.cli import main

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


def test_missing_required_option_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(str(EXAMPLE_CSV))
    assert exit_info.value.code == 2
