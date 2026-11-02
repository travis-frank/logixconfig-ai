"""Core data models: equipment from the process, and the Logix tags generated for it."""

from enum import Enum

from pydantic import BaseModel


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
    name: str
    type: EquipmentType
    description: str = ""


class Tag(BaseModel):
    name: str
    data_type: DataType
    description: str = ""
    equipment: str
