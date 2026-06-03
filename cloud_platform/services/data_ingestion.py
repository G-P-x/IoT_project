"""
Data Ingestion Service
=======================
Processes gateway responses and persists sensor readings as Digital Replica
measurements in MongoDB.

This is the "missing bridge" between the HTTP client (which pulls data from
edge gateways) and the DT persistence layer (DatabaseService + DRs).

Flow:
    1. operator_api.send_command() fans out HTTP requests to gateways.
    2. Each gateway responds with a list of sensor records.
    3. This service takes those gateway responses, and for each OK record:
        a. Looks up the sensor DR by its physical sensor_id (profile.sensor_id).
        b. If no sensor DR exists yet, auto-creates one and links it to the
           gateway DR.
        c. Appends the measurement to the sensor DR's data.measurements list
           and updates data.current_value.
        d. Also appends the measurement to the gateway DR's data.measurements
           for aggregated access.
    4. Returns a summary of what was ingested.

Design decisions:
    - Auto-creation of sensor DRs removes the need for manual pre-registration.
      The first time a gateway reports a sensor, the DR is born automatically.
    - Sensor type is inferred from the physical sensor_id suffix convention:
        t  → temperature
        aq → air_quality
        s  → seismic_waves
      This can be extended via the SENSOR_TYPE_MAP dict.
    - The service is stateless — it uses the DB_SERVICE and SCHEMA_REGISTRY
      passed to it, making it testable in isolation.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic_core import ValidationError
from cloud_platform.types.edge import DeviceResult, EdgeResults
from cloud_platform.virtualization.digital_replica.dr_factory import DRFactory
from cloud_platform.virtualization.digital_replica.history_factory import HistoryFactory
from cloud_platform.services.database_service import DatabaseService # used just to check the input

logger = logging.getLogger(__name__)

# ── Sensor-type inference from physical ID suffix ─────────────────────
# Gateway sensor IDs follow the pattern "<MAC>-<suffix>" where the suffix
# hints at the sensor kind.  This map is the single place to extend when
# new sensor types are added to the edge firmware.
SENSOR_TYPE_MAP = {
    "t":  "temperature",
    "aq": "air_quality",
    "s":  "seismic_waves",
    "h":  "humidity",
    "g":  "gas",
}

# Measurement units per sensor type
UNIT_MAP = {
    "temperature":   "°C",
    "air_quality":   "AQI",
    "seismic_waves": "mm/s",
    "humidity":      "%",
    "gas":           "ppm",
}


def _infer_sensor_type(physical_sensor_id: str) -> str:
    """
    Derive the sensor type from the physical sensor ID suffix.

    Examples:
        "84F3EB12A0BC-t1"  → "temperature"
        "84F3EB12A0BC-aq1" → "air_quality"
        "FFEEDDCCBBAA-s1"  → "seismic_waves"

    Falls back to "unknown" if the suffix is not recognised.
    """
    # Split on '-' and take the last segment, then strip trailing digits
    parts = physical_sensor_id.rsplit("-", 1)
    if len(parts) < 2:
        return "unknown"
    suffix = parts[1].rstrip("0123456789")  # "t1" → "t", "aq1" → "aq"
    return SENSOR_TYPE_MAP.get(suffix, "unknown")

def _find_gateway_dr(db_service: DatabaseService, device_id: str) -> Optional[Dict]:
    """
    Look up the gateway DR by the physical device_id.

    Returns:
        The gateway DR document dict or None if not found.
    """
    # Try to find an existing gateway DR by device_id
    existing = db_service.query_drs("device", {"profile.device_id": device_id})
    if existing:
        return existing[0]

    # ── Auto-create ──────────────────────────────────────────────────
    initial_data = {
        "profile": {
            "name": f"Gateway {device_id}",
            "device_id": device_id,
            "description": f"Auto-created for device '{device_id}'",
        },
        "data": {
            "sensors": [],  # will be populated as sensors are linked
        },
    }

    dr_factory = DRFactory("cloud_platform/virtualization/templates/gateway.yaml")
    gateway_dr = dr_factory.create_dr("gateway", initial_data)
    db_service.save_dr("gateway", gateway_dr)

    logger.info("Auto-created gateway DR '%s' for device '%s'", gateway_dr["_id"], device_id)
    return gateway_dr

def _find_or_create_sensor_dr(
    db_service,
    physical_sensor_id: str,
    gateway_device_id: str,
    gateway_dr_id: Optional[str] = None,
) -> Dict:
    """
    Look up a sensor DR by its physical sensor_id.  If it doesn't exist,
    auto-create one and link it to the gateway.

    Args:
        db_service:          The DatabaseService instance.
        physical_sensor_id:  e.g. "84F3EB12A0BC-t1".
        gateway_device_id:   The gateway's device_id (e.g. "device_01").
        gateway_dr_id:       The gateway DR's _id (if known) to set on the sensor profile.

    Returns:
        The sensor DR document dict (existing or newly created).
    """
    # Try to find an existing sensor DR by physical ID
    existing = db_service.query_drs("sensor", {"profile.sensor_id": physical_sensor_id})
    if existing:
        return existing[0]

    # ── Auto-create ──────────────────────────────────────────────────
    sensor_type = _infer_sensor_type(physical_sensor_id)
    unit = UNIT_MAP.get(sensor_type, "")

    initial_data = {
        "profile": {
            "name": f"Sensor {physical_sensor_id}",
            "sensor_id": physical_sensor_id,
            "sensor_type": sensor_type,
            "unit": unit,
            "description": f"Auto-created from gateway '{gateway_device_id}' response",
            "gateway_id": gateway_dr_id or "",
        },
    }

    dr_factory = DRFactory("cloud_platform/virtualization/templates/sensor.yaml")
    sensor_dr = dr_factory.create_dr("sensor", initial_data)
    db_service.save_dr("sensor", sensor_dr)

    # If we know the gateway DR, add this sensor to its sensors list
    if gateway_dr_id:
        _link_sensor_to_gateway(db_service, gateway_dr_id, sensor_dr["_id"])

    logger.info(
        "Auto-created sensor DR '%s' (type=%s) for gateway '%s'",
        sensor_dr["_id"], sensor_type, gateway_device_id,
    )
    return sensor_dr


def _link_sensor_to_gateway(db_service, gateway_dr_id: str, sensor_dr_id: str) -> None:
    """
    Add a sensor DR _id to the gateway DR's data.sensors list (if not already present).
    """
    try:
        gw = db_service.get_dr("gateway", gateway_dr_id)
        if not gw:
            return
        sensors_list = gw.get("data", {}).get("sensors", [])
        if sensor_dr_id not in sensors_list:
            sensors_list.append(sensor_dr_id)
            db_service.update_dr("gateway", gateway_dr_id, {
                "data": {"sensors": sensors_list},
                "metadata": {"updated_at": datetime.utcnow()},
            })
    except Exception as e:
        logger.warning("Failed to link sensor %s to gateway %s: %s", sensor_dr_id, gateway_dr_id, e)


def _resolve_gateway_dr_id(db_service, device_id: str) -> Optional[str]:
    """
    Look up the gateway DR _id from the physical device_id.

    Returns None if no gateway DR is registered for this device.
    """
    results = db_service.query_drs("gateway", {"profile.device_id": device_id})
    if results:
        return results[0]["_id"]
    return None

def _create_gateway_record(gateway_id: str, gateway_info: Dict, sub: str | None) -> dict:
    history_factory = HistoryFactory("cloud_platform/virtualization/templates/gateway_history.yaml")

    history_entry = history_factory.create_record({
        "device_id": gateway_id,
        "timestamp": gateway_info.get("req_timestamp", datetime.now(timezone.utc).isoformat()),
        "data": {"status": "active" if gateway_info.get("status") == "success" else "inactive",
                 "source": "operator" if sub else "telemetry",
                 "operator_id": sub if sub else None},
    })
    return history_entry

def _create_sensor_record(gateway_id: str, sensor_id: str, record: Dict, sub: str | None) -> dict: 
    history_factory = HistoryFactory("cloud_platform/virtualization/templates/sensor_history.yaml")
    history_entry = history_factory.create_record({
        "device_id": sensor_id,
        "gateway_id": gateway_id,
        "timestamp": record.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "data": {
            "value": record.get("value"),
            "status": "active" if record.get("status") == "OK" else "inactive",            
            "source": "operator" if sub else "telemetry",
            "operator_id": sub if sub else None,
        },
    })
    return history_entry

def _create_actuator_record(gateway_id, actuator_id: str, record: Dict, sub: str | None, command: str | None) -> None:
    # to be completed, I have to wait to understan what kind of actuator is going to be used.
    history_factory = HistoryFactory("cloud_platform/virtualization/templates/actuator_history.yaml")
    history_entry = history_factory.create_record({
        "device_id": actuator_id,
        "gateway_id": gateway_id,
        "timestamp": record.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "data": {
            "command": command,
            "status": "active" if record.get("status") == "OK" else "inactive",            
            "source": "operator" if sub else "telemetry",
            "operator_id": sub if sub else None,
        },

    })
    pass

def _create_gateway_dr_entry(gateway_id: str, gateway_info: Dict, sensors : List[str] = [], actuators: List[str] = []) -> dict:
    dr_factory = DRFactory("cloud_platform/virtualization/templates/gateway.yaml")
    initial_data = {
        "profile": {
            "device_id": gateway_id,
        },
        "data": {
            "sensors": sensors,  # will be populated as sensors are linked
        },
        "metadata": {
            "last_update": gateway_info.get("req_timestamp", datetime.now(timezone.utc).isoformat()),
            "status": "active" if gateway_info.get("status") == "success" else "inactive",
        },
    }
    gateway_dr = dr_factory.create_dr("gateway", initial_data)
    return gateway_dr

def  _parse_record_timestamp(value: str | None) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not value or not isinstance(value, str):
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None

def _collect_latest_sensor_readings(records: Dict[str, Dict]) -> tuple[list[str], Dict[str, Dict]]:
    """
    Extract unique sensor IDs and their most recent readings.

    Returns:
        sensors: list of unique sensor IDs (first-seen order)
        latest: mapping of sensor ID -> latest record by timestamp
    """
    sensors: list[str] = []
    seen: set[str] = set()
    latest: Dict[str, Dict] = {}
    latest_ts: Dict[str, Optional[datetime]] = {}

    for device_id, record in (records or {}).items():
        if not isinstance(record, dict):
            continue
        if record.get("type") != "sensor":
            continue

        if device_id not in seen:
            seen.add(device_id)
            sensors.append(device_id)

        # Keep the record with the most recent timestamp; prefer any parseable timestamp.
        current_ts = _parse_record_timestamp(record.get("timestamp"))
        prev_ts = latest_ts.get(device_id)

        if device_id not in latest:
            latest[device_id] = record
            latest_ts[device_id] = current_ts
            continue

        if prev_ts is None:
            if current_ts is not None:
                latest[device_id] = record
                latest_ts[device_id] = current_ts
            continue

        if current_ts is not None and current_ts > prev_ts:
            latest[device_id] = record
            latest_ts[device_id] = current_ts

    return sensors, latest

def ingest_edge_results(db_service: DatabaseService, edge_results: Dict[str, DeviceResult], submitter: str | None) -> Dict:
    """
    Process the full edge_results dict returned by send_command_to_all_devices()
    and persist every successful sensor reading into the corresponding DRs.

    Args:
        db_service:   The DatabaseService instance (from current_app.config["DB_SERVICE"]).
        edge_results: Dict mapping device_id → result dict, as returned by
                      client_http.send_command_to_all_devices().
                      Expected record format per device:
                      {
                          "status": "success",
                          "body": {
                              "time_stamp": "...",
                              "records": [
                                  { "status": "OK", "type": "sensor",
                                    "id": "...", "value": ..., "timestamp": "..." },
                                  ...
                              ]
                          } 
                      }

    Returns:
        A summary dict:
        {
            "ingested": <int>,      # number of measurements stored
            "skipped":  <int>,      # records skipped (ERROR status, null value, etc.)
            "errors":   [<str>],    # any processing errors
            "details":  [ ... ],    # per-record detail
        }
    """

    try:
        # validate edge_results structure with Pydantic, technically it is already validated in the client_http before returning the response.
        EdgeResults(edge=edge_results)

    except ValidationError as ve:
        print("Validation error in edge_results:", ve)
        return {}

    for gateway_id, gtw_data in edge_results.items(): # gateway_id, data: DeviceResult
        # Skip devices that failed to respond
        assert isinstance(gtw_data, dict), f"Expected dict for device result, got {type(gtw_data)}"

        # ----- First case: gateway-level failure (e.g. no response) -----
        if gtw_data.get("gateway_info", {}).get("status") != "success":
            history_entry = _create_gateway_record(gateway_id, gtw_data.get("gateway_info", {}), sub = submitter)
            db_service.save_history_event(history_entry)
            dr_entry = _create_gateway_dr_entry(gateway_id, gtw_data.get("gateway_info", {}))
            if dr_entry:
                db_service.update_dr("gateway", dr_entry["_id"], {
                    "data": {"status": "inactive"},
                    "metadata": {"updated_at": datetime.now(timezone.utc).isoformat()},
                })
            continue
        
        # ----- Second case: gateway-level success -----
        history_entry = _create_gateway_record(gateway_id, gtw_data.get("gateway_info", {}), sub = submitter)
        db_service.save_history_event(history_entry)
        sensors = []
        actuators = []
        
        
        for device_id, device_data in gtw_data.get("records", {}).items():

            # create a history entry and DR entry for the sensor record
            if device_data.get("type") == "sensor":
                history_entry = _create_sensor_record(gateway_id, device_id, device_data, sub = submitter)
                db_service.save_history_event(history_entry)
                sensors.append(device_id)
                # also create/update the sensor DR and link it to the gateway DR
                
            elif device_data.get("type") == "actuator":
                # to be completed when I will have more details about the actuators
                actuators.append(device_id)

        dr_entry = _create_gateway_dr_entry(gateway_id, gtw_data.get("gateway_info", {}), sensors = sensors, actuators = actuators)
        # update the gateway DR with the new sensors/actuators and status

## ARRIVATO QUI IL GIORNO 25-05