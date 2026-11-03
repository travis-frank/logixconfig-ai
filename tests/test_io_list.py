import csv
from pathlib import Path

import pytest

from logixconfig.io_list import SignalType, io_rows, signal_type_for, write_io_list
from logixconfig.models import Equipment, Tag
from logixconfig.templates import tags_for


def make_tag(name: str) -> Tag:
    return Tag(name=name, data_type="BOOL", description="d", equipment="EQ")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("P101_Run_Cmd", SignalType.DIGITAL_OUTPUT),
        ("XV101_Open_Cmd", SignalType.DIGITAL_OUTPUT),
        ("P101_Run_Fb", SignalType.DIGITAL_INPUT),
        ("XV101_Closed_Fb", SignalType.DIGITAL_INPUT),
        ("P101_Fault", SignalType.DIGITAL_INPUT),
        ("LT101_PV", SignalType.ANALOG_INPUT),
        ("LT101_Hi_SP", SignalType.INTERNAL_SETPOINT),
        ("LT101_Lo_SP", SignalType.INTERNAL_SETPOINT),
        ("LT101_Hi_Alm", SignalType.INTERNAL_ALARM),
        ("LT101_Lo_Alm", SignalType.INTERNAL_ALARM),
    ],
)
def test_signal_type_mapping(name: str, expected: SignalType) -> None:
    assert signal_type_for(make_tag(name)) is expected


def test_unknown_suffix_raises() -> None:
    with pytest.raises(ValueError, match="P101_Speed"):
        signal_type_for(make_tag("P101_Speed"))


def test_suffix_must_be_at_end_of_name() -> None:
    with pytest.raises(ValueError):
        signal_type_for(make_tag("P101_Cmd_Extra"))


def test_every_template_tag_has_a_signal_type() -> None:
    for kind in ("pump", "valve", "level_transmitter", "pressure_transmitter"):
        io_rows(tags_for(Equipment(name="EQ1", type=kind)))


def test_pump_io_rows() -> None:
    rows = io_rows(tags_for(Equipment(name="P101", type="pump", description="Feed pump")))
    assert [(row.tag, row.signal_type) for row in rows] == [
        ("P101_Run_Cmd", SignalType.DIGITAL_OUTPUT),
        ("P101_Run_Fb", SignalType.DIGITAL_INPUT),
        ("P101_Fault", SignalType.DIGITAL_INPUT),
    ]
    assert rows[0].description == "Feed pump run command"


def test_write_io_list_csv(tmp_path: Path) -> None:
    path = tmp_path / "io_list.csv"
    write_io_list(io_rows([make_tag("P101_Run_Cmd"), make_tag("LT101_Hi_SP")]), path)
    with open(path, newline="", encoding="utf-8") as file:
        rows = list(csv.reader(file))
    assert rows == [
        ["tag", "signal_type", "description"],
        ["P101_Run_Cmd", "DO", "d"],
        ["LT101_Hi_SP", "Internal setpoint", "d"],
    ]
