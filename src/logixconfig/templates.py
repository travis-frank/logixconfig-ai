"""Deterministic tag templates: each equipment type always expands to the same tags."""

from typing import NamedTuple

from logixconfig.models import DataType, Equipment, EquipmentType, Tag


class TagTemplate(NamedTuple):
    suffix: str
    data_type: DataType
    description: str


_TRANSMITTER_TEMPLATES = (
    TagTemplate("PV", DataType.REAL, "process value"),
    TagTemplate("Hi_SP", DataType.REAL, "high alarm setpoint"),
    TagTemplate("Lo_SP", DataType.REAL, "low alarm setpoint"),
    TagTemplate("Hi_Alm", DataType.BOOL, "high alarm"),
    TagTemplate("Lo_Alm", DataType.BOOL, "low alarm"),
)

TEMPLATES: dict[EquipmentType, tuple[TagTemplate, ...]] = {
    EquipmentType.PUMP: (
        TagTemplate("Run_Cmd", DataType.BOOL, "run command"),
        TagTemplate("Run_Fb", DataType.BOOL, "run feedback"),
        TagTemplate("Fault", DataType.BOOL, "fault"),
    ),
    EquipmentType.VALVE: (
        TagTemplate("Open_Cmd", DataType.BOOL, "open command"),
        TagTemplate("Open_Fb", DataType.BOOL, "open feedback"),
        TagTemplate("Closed_Fb", DataType.BOOL, "closed feedback"),
    ),
    EquipmentType.LEVEL_TRANSMITTER: _TRANSMITTER_TEMPLATES,
    EquipmentType.PRESSURE_TRANSMITTER: _TRANSMITTER_TEMPLATES,
}


def tag_name(equipment_name: str, suffix: str) -> str:
    return f"{equipment_name}_{suffix}"


def tag_description(equipment: Equipment, template: TagTemplate) -> str:
    label = equipment.description.strip() or equipment.name
    return f"{label} {template.description}"


def tags_for(equipment: Equipment) -> list[Tag]:
    return [
        Tag(
            name=tag_name(equipment.name, template.suffix),
            data_type=template.data_type,
            description=tag_description(equipment, template),
            equipment=equipment.name,
        )
        for template in TEMPLATES[equipment.type]
    ]
