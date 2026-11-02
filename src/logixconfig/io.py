"""Read equipment lists from CSV files."""

import csv
from pathlib import Path

from logixconfig.models import Equipment, EquipmentType

REQUIRED_COLUMNS = ("name", "type", "description")


def read_equipment(csv_path: str | Path) -> list[Equipment]:
    with open(csv_path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            return []
        _check_columns(reader.fieldnames)
        return [
            _row_to_equipment(row, line_number=reader.line_num)
            for row in reader
            if not _is_blank(row)
        ]


def _check_columns(fieldnames: list[str]) -> None:
    present = {name.strip().lower() for name in fieldnames}
    missing = [column for column in REQUIRED_COLUMNS if column not in present]
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")


def _row_to_equipment(row: dict[str, str], line_number: int) -> Equipment:
    values = {key.strip().lower(): (value or "").strip() for key, value in row.items() if key}
    return Equipment(
        name=values["name"],
        type=_parse_type(values["type"], line_number),
        description=values["description"],
    )


def _parse_type(raw: str, line_number: int) -> EquipmentType:
    try:
        return EquipmentType(raw.lower())
    except ValueError:
        valid = ", ".join(t.value for t in EquipmentType)
        raise ValueError(f"Line {line_number}: unknown equipment type '{raw}' (expected one of: {valid})") from None


def _is_blank(row: dict[str, str]) -> bool:
    return all(not (value or "").strip() for key, value in row.items() if key)
