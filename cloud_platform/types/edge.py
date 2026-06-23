# cloud_platform/types/edge.py
from typing import Dict
from typing import Literal
from pydantic.v1 import BaseModel


class GatewayInfo(BaseModel):
    status: Literal["success", "error"]
    code: int
    error: str | None = None
    req_timestamp: str


class FieldDeviceResult(BaseModel):
    type: str                    # "sensor" / "actuator"
    status: str                  # "OK" / "ERROR"
    severity: str                # "none" / "critical" / "error"
    value: float | None          # Valore letto (null se il sensore non risponde)
    message: str                 # Messaggio descrittivo dal gateway
    timestamp: str               # ISO datetime della lettura
    threshold: float | None = None  # Soglia critica configurata sull'ESP (null se sensore non risponde)


class DeviceResult(BaseModel):
    gateway_info: GatewayInfo
    records: dict[str, FieldDeviceResult]


class EdgeResults(BaseModel):
    edge: dict[str, DeviceResult]  # gateway_id → DeviceResult