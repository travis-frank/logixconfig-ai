import pytest
from pydantic import ValidationError

from logixconfig.models import DataType, Equipment, EquipmentType, Tag


def test_equipment_accepts_type_as_string() -> None:
    pump = Equipment(name="P101", type="pump", description="Feed pump")
    assert pump.type is EquipmentType.PUMP


def test_equipment_description_defaults_to_empty() -> None:
    assert Equipment(name="P101", type="pump").description == ""


def test_equipment_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        Equipment(name="M101", type="mixer")


@pytest.mark.parametrize("name", ["", " ", "   "])
def test_equipment_rejects_empty_name(name: str) -> None:
    with pytest.raises(ValidationError):
        Equipment(name=name, type="pump")


def test_equipment_strips_whitespace() -> None:
    pump = Equipment(name=" P101 ", type="pump", description="  Feed pump  ")
    assert (pump.name, pump.description) == ("P101", "Feed pump")


def test_tag_accepts_data_type_as_string() -> None:
    tag = Tag(name="P101_Run_Cmd", data_type="BOOL", equipment="P101")
    assert tag.data_type is DataType.BOOL


def test_tag_rejects_unknown_data_type() -> None:
    with pytest.raises(ValidationError):
        Tag(name="P101_Run_Cmd", data_type="STRING", equipment="P101")


def test_all_mvp_data_types_exist() -> None:
    assert {t.value for t in DataType} == {"BOOL", "SINT", "INT", "DINT", "REAL"}
