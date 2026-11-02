from collections import Counter
from pathlib import Path

import pytest

from logixconfig.io import read_equipment
from logixconfig.models import EquipmentType
from logixconfig.templates import tags_for
from logixconfig.validator import validate

EXAMPLE_CSV = Path(__file__).parent.parent / "examples" / "equipment.csv"


def write_csv(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "equipment.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_reads_rows(tmp_path: Path) -> None:
    path = write_csv(tmp_path, "name,type,description\nP101,pump,Feed pump\nXV101,valve,Inlet\n")
    equipment = read_equipment(path)
    assert [(e.name, e.type, e.description) for e in equipment] == [
        ("P101", EquipmentType.PUMP, "Feed pump"),
        ("XV101", EquipmentType.VALVE, "Inlet"),
    ]


def test_empty_file_returns_empty_list(tmp_path: Path) -> None:
    assert read_equipment(write_csv(tmp_path, "")) == []


def test_header_only_returns_empty_list(tmp_path: Path) -> None:
    assert read_equipment(write_csv(tmp_path, "name,type,description\n")) == []


def test_unknown_type_raises_with_line_number(tmp_path: Path) -> None:
    path = write_csv(tmp_path, "name,type,description\nP101,pump,Feed\nM101,mixer,Mixer\n")
    with pytest.raises(ValueError, match=r"Line 3: unknown equipment type 'mixer'"):
        read_equipment(path)


def test_empty_name_raises_with_line_number(tmp_path: Path) -> None:
    path = write_csv(tmp_path, "name,type,description\nP101,pump,Feed\n,valve,Unnamed valve\n")
    with pytest.raises(ValueError, match=r"Line 3: invalid equipment \(name: "):
        read_equipment(path)


def test_missing_column_raises(tmp_path: Path) -> None:
    path = write_csv(tmp_path, "name,type\nP101,pump\n")
    with pytest.raises(ValueError, match="missing required columns: description"):
        read_equipment(path)


def test_trims_whitespace_and_normalizes_type_case(tmp_path: Path) -> None:
    path = write_csv(tmp_path, " Name , TYPE ,description\n  P101 , Pump ,  Feed pump  \n")
    [pump] = read_equipment(path)
    assert (pump.name, pump.type, pump.description) == ("P101", EquipmentType.PUMP, "Feed pump")


def test_skips_blank_rows(tmp_path: Path) -> None:
    path = write_csv(tmp_path, "name,type,description\nP101,pump,Feed\n,,\n\nP102,pump,Transfer\n")
    assert [e.name for e in read_equipment(path)] == ["P101", "P102"]


def test_handles_excel_byte_order_mark(tmp_path: Path) -> None:
    path = tmp_path / "equipment.csv"
    path.write_text("name,type,description\nP101,pump,Feed\n", encoding="utf-8-sig")
    assert [e.name for e in read_equipment(path)] == ["P101"]


def test_description_containing_comma(tmp_path: Path) -> None:
    path = write_csv(tmp_path, 'name,type,description\nP101,pump,"Feed pump, north side"\n')
    assert read_equipment(path)[0].description == "Feed pump, north side"


def test_example_file_has_expected_equipment() -> None:
    counts = Counter(e.type for e in read_equipment(EXAMPLE_CSV))
    assert counts == {
        EquipmentType.PUMP: 2,
        EquipmentType.VALVE: 3,
        EquipmentType.LEVEL_TRANSMITTER: 1,
        EquipmentType.PRESSURE_TRANSMITTER: 2,
    }


def test_example_file_produces_valid_tags() -> None:
    tags = [tag for equipment in read_equipment(EXAMPLE_CSV) for tag in tags_for(equipment)]
    assert len(tags) == 2 * 3 + 3 * 3 + 3 * 5
    assert validate(tags) == []
