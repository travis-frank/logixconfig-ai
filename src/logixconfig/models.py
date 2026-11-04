"""Core data models: equipment from the process, and the Logix tags generated for it."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DataType(str, Enum):
    BOOL = "BOOL"
    SINT = "SINT"
    INT = "INT"
    DINT = "DINT"
    REAL = "REAL"


class EquipmentType(str, Enum):
    PUMP = "pump"
    VALVE = "valve"
    LEVEL_TRANSMITTER = "level_transmitter"
    PRESSURE_TRANSMITTER = "pressure_transmitter"


class Equipment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1)
    type: EquipmentType
    description: str = ""


class PlannerOutput(BaseModel):
    equipment: list[Equipment]
    assumptions: list[str] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)


class Tag(BaseModel):
    name: str
    data_type: DataType
    description: str = ""
    equipment: str
