"""Classify tags as physical I/O or internal values and write an I/O list."""

import csv
from enum import Enum
from pathlib import Path
from typing import NamedTuple

from logixconfig.models import Tag


class SignalType(str, Enum):
    DIGITAL_OUTPUT = "DO"
    DIGITAL_INPUT = "DI"
    ANALOG_INPUT = "AI"
    INTERNAL_SETPOINT = "Internal setpoint"
    INTERNAL_ALARM = "Internal alarm"


class IoRow(NamedTuple):
    tag: str
    signal_type: SignalType
    description: str


SUFFIX_SIGNAL_TYPES: tuple[tuple[str, SignalType], ...] = (
    ("_Cmd", SignalType.DIGITAL_OUTPUT),
    ("_Fb", SignalType.DIGITAL_INPUT),
    ("_Fault", SignalType.DIGITAL_INPUT),
    ("_PV", SignalType.ANALOG_INPUT),
    ("_SP", SignalType.INTERNAL_SETPOINT),
    ("_Alm", SignalType.INTERNAL_ALARM),
)

IO_LIST_COLUMNS = ("tag", "signal_type", "description")


def signal_type_for(tag: Tag) -> SignalType:
    for suffix, signal_type in SUFFIX_SIGNAL_TYPES:
        if tag.name.endswith(suffix):
            return signal_type
    raise ValueError(f"Tag '{tag.name}' has no known I/O suffix")


def io_rows(tags: list[Tag]) -> list[IoRow]:
    return [IoRow(tag.name, signal_type_for(tag), tag.description) for tag in tags]


def write_io_list(rows: list[IoRow], path: str | Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(IO_LIST_COLUMNS)
        for row in rows:
            writer.writerow([row.tag, row.signal_type.value, row.description])
