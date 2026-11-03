import csv
from pathlib import Path

from logixconfig.io import render_docs, suggested_alarm_rows, write_docs, write_tags_csv
from logixconfig.models import Equipment
from logixconfig.templates import tags_for

PUMP = Equipment(name="P101", type="pump", description="Crude transfer pump A")
LEVEL = Equipment(name="LT101", type="level_transmitter", description="Tank TK-100 level")


def all_tags(equipment: list[Equipment]) -> list:
    return [tag for item in equipment for tag in tags_for(item)]


def test_write_tags_csv(tmp_path: Path) -> None:
    path = tmp_path / "tags.csv"
    write_tags_csv(tags_for(PUMP), path)
    with open(path, newline="", encoding="utf-8") as file:
        rows = list(csv.reader(file))
    assert rows[0] == ["name", "data_type", "description", "equipment"]
    assert rows[1] == ["P101_Run_Cmd", "BOOL", "Crude transfer pump A run command", "P101"]
    assert len(rows) == 4


def test_write_tags_csv_quotes_commas(tmp_path: Path) -> None:
    pump = Equipment(name="P101", type="pump", description="Pump A, north")
    path = tmp_path / "tags.csv"
    write_tags_csv(tags_for(pump), path)
    with open(path, newline="", encoding="utf-8") as file:
        rows = list(csv.reader(file))
    assert rows[1][2] == "Pump A, north run command"


def test_docs_have_all_sections_in_order() -> None:
    docs = render_docs([PUMP, LEVEL], all_tags([PUMP, LEVEL]))
    positions = [docs.index(heading) for heading in ("## Equipment", "## Tags", "## Suggested Alarms")]
    assert positions == sorted(positions)


def test_docs_list_every_equipment_item_and_tag() -> None:
    equipment = [PUMP, LEVEL]
    tags = all_tags(equipment)
    docs = render_docs(equipment, tags)
    assert "| P101 | pump | Crude transfer pump A |" in docs
    assert "| LT101 | level_transmitter | Tank TK-100 level |" in docs
    for tag in tags:
        assert f"| {tag.name} | {tag.data_type.value} |" in docs


def test_docs_escape_pipes_in_descriptions() -> None:
    pump = Equipment(name="P101", type="pump", description="Pump A | B")
    docs = render_docs([pump], tags_for(pump))
    assert "Pump A \\| B" in docs


def test_suggested_alarms_reference_real_tag_names() -> None:
    rows = suggested_alarm_rows([PUMP, LEVEL])
    assert ("P101", "Fault", "P101_Fault is on") in rows
    assert ("LT101", "High level", "LT101_PV is above LT101_Hi_SP (sets LT101_Hi_Alm)") in rows


def test_every_equipment_type_has_suggested_alarms() -> None:
    for kind in ("pump", "valve", "level_transmitter", "pressure_transmitter"):
        assert suggested_alarm_rows([Equipment(name="EQ1", type=kind)])


def test_docs_with_no_equipment() -> None:
    docs = render_docs([], [])
    assert "## Equipment" in docs
    assert docs.endswith("\n")


def test_write_docs(tmp_path: Path) -> None:
    path = tmp_path / "docs.md"
    write_docs([PUMP], tags_for(PUMP), path)
    assert path.read_text(encoding="utf-8") == render_docs([PUMP], tags_for(PUMP))
