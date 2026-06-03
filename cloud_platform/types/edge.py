# cloud_platform/types/edge.py
from typing import TypedDict, Dict
from typing import Literal
from pydantic.v1 import BaseModel

# ── pydantic for enhanced data validation ──────────────────────────────────────────
class GatewayInfo(BaseModel):
    status: Literal["success", "error"]
    code: int
    error: str | None = None
    req_timestamp: str

class FieldDeviceResult(BaseModel):
    type: str                    # "temperature sensor" or "air quality sensor", etc.
    status: str                    # "ERROR" or "OK"
    severity: str                  # "critical", "warning", "info"
    value: float | None          # present if status is OK
    message: str                # "reading acquired" or "invalid sensor_id", etc.
    timestamp: str              # ISO datetime string of when the reading was taken

class DeviceResult(BaseModel):
    gateway_info: GatewayInfo
    records: dict[str, FieldDeviceResult]

class EdgeResults(BaseModel):
    edge: dict[str, DeviceResult]  # gateway_id → DeviceResult