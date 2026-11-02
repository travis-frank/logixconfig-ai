import pytest
from pydantic import ValidationError

from logixconfig.models import DataType, Equipment, EquipmentType
from logixconfig.templates import TEMPLATES, tags_for


def names(equipment: Equipment) -> list[str]:
    return [tag.name for tag in tags_for(equipment)]


def test_pump_tags() -> None:
    pump = Equipment(name="P101", type="pump", description="Feed pump")
    assert names(pump) == ["P101_Run_Cmd", "P101_Run_Fb", "P101_Fault"]
    assert all(tag.data_type is DataType.BOOL for tag in tags_for(pump))


def test_valve_tags() -> None:
    valve = Equipment(name="XV101", type="valve")
    assert names(valve) == ["XV101_Open_Cmd", "XV101_Open_Fb", "XV101_Closed_Fb"]


@pytest.mark.parametrize("kind", ["level_transmitter", "pressure_transmitter"])
def test_transmitter_tags(kind: str) -> None:
    tags = tags_for(Equipment(name="LT101", type=kind))
    types = {tag.name: tag.data_type for tag in tags}
    assert types == {
        "LT101_PV": DataType.REAL,
        "LT101_Hi_SP": DataType.REAL,
        "LT101_Lo_SP": DataType.REAL,
        "LT101_Hi_Alm": DataType.BOOL,
        "LT101_Lo_Alm": DataType.BOOL,
    }


def test_tags_link_back_to_equipment() -> None:
    tags = tags_for(Equipment(name="P101", type="pump"))
    assert {tag.equipment for tag in tags} == {"P101"}


def test_description_uses_equipment_description() -> None:
    tag = tags_for(Equipment(name="P101", type="pump", description="Feed pump"))[0]
    assert tag.description == "Feed pump run command"


def test_description_falls_back_to_name() -> None:
    tag = tags_for(Equipment(name="P101", type="pump"))[0]
    assert tag.description == "P101 run command"


def test_same_input_gives_same_output() -> None:
    pump = Equipment(name="P101", type="pump", description="Feed pump")
    assert tags_for(pump) == tags_for(pump)


def test_empty_equipment_name_cannot_produce_underscore_tags() -> None:
    with pytest.raises(ValidationError):
        tags_for(Equipment(name="", type="pump"))


def test_every_equipment_type_has_a_template() -> None:
    assert set(TEMPLATES) == set(EquipmentType)
