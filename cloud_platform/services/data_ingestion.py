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
from datetime import datetime
from typing import Dict, List, Optional
from cloud_platform.virtualization.digital_replica.dr_factory import DRFactory

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

def ingest_telemetry_data(db_service, telemetry_data: List[Dict]) -> None:
    """
    Process telemetry data from a gateway and persist it as measurements in the corresponding sensor DRs.

    Args:
        db_service:     The DatabaseService instance.
        telemetry_data: List of dicts containing the gateway's telemetry data, expected format:
                    [
                        {
                            "time_stamp": "2026-05-05T14:30:00.000Z",
                            "record": {
                            "id": "mpu6050_01",
                            "type": "accelerometer",
                            "status": "ERROR",
                            "severity": "critical",
                            "value": null,
                            "message": "MPU-6050 connection lost",
                            "timestamp": "2026-05-05T14:29:58Z"
                            }
                        }
                    ]

    """
    # Implementation for ingesting telemetry data
    # 1. Validate the telemetry data format.
    assert isinstance(telemetry_data, list), "Telemetry data must be a list of records"
    for data in telemetry_data:
        assert isinstance(data, dict), "Each telemetry record must be a dict"
        assert "time_stamp" in data, "Each telemetry record must have a 'time_stamp' field"
        assert "record" in data, "Each telemetry record must have a 'record' field"
        assert "id" in data['record'], "Each telemetry record must have an 'id' field"
        assert "type" in data['record'], "Each telemetry record must have a 'type' field"
        assert "status" in data['record'], "Each telemetry record must have a 'status' field"
        assert "severity" in data['record'], "Each telemetry record must have a 'severity' field"
        assert "value" in data['record'], "Each telemetry record must have a 'value' field"
        assert "timestamp" in data['record'], "Each telemetry record must have a 'timestamp' field"

    assert all(isinstance(record, dict) and "id" in record for record in telemetry_data), "Each telemetry record must be a dict with an 'id' field"
    # 2. Aggregate the data by id.
    # 3. For each unique id, find the latest record and persist it as a measurement in the corresponding sensor DR.
    # 4. Persist all the records related to the same id in the history collection of the sensor DR, ensuring uniqueness based on the timestamp. 
    pass

def ingest_edge_results(db_service, edge_results: Dict) -> Dict:
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
    ingested = 0
    skipped = 0
    errors: List[str] = []
    details: List[Dict] = []

    for device_id, res in edge_results.items():
        # Skip devices that failed to respond
        if res.get("status") != "success":
            skipped += 1
            continue

        body = res.get("body")
        if not isinstance(body, dict) or "records" not in body:
            skipped += 1
            continue

        # Resolve the gateway DR _id once per device
        gateway_dr_id = _resolve_gateway_dr_id(db_service, device_id)

        for record in body["records"]:
            # Only process successful sensor readings
            if record.get("status") != "OK":
                skipped += 1
                details.append({
                    "device": device_id,
                    "sensor": record.get("id"),
                    "action": "skipped",
                    "reason": record.get("message", "non-OK status"),
                })
                continue

            physical_sensor_id = record.get("id")
            value = record.get("value")
            timestamp = record.get("timestamp", datetime.utcnow().isoformat())

            if physical_sensor_id is None or value is None:
                skipped += 1
                continue

            try:
                # ── Find or auto-create the sensor DR ──
                sensor_dr = _find_or_create_sensor_dr(
                    db_service, physical_sensor_id, device_id, gateway_dr_id
                )

                # ── Build the measurement record ──
                sensor_type = _infer_sensor_type(physical_sensor_id)
                measurement = {
                    "measure_type": sensor_type,
                    "value": value,
                    "timestamp": timestamp,
                }

                # ── Append to sensor DR ──
                existing_measurements = sensor_dr.get("data", {}).get("measurements", [])
                db_service.update_dr("sensor", sensor_dr["_id"], {
                    "data": {
                        "measurements": existing_measurements + [measurement],
                        "current_value": value,
                    },
                    "metadata": {"updated_at": datetime.utcnow()},
                })

                # ── Also append to gateway DR (aggregated view) ──
                if gateway_dr_id:
                    gw = db_service.get_dr("gateway", gateway_dr_id)
                    if gw:
                        gw_measurements = gw.get("data", {}).get("measurements", [])
                        db_service.update_dr("gateway", gateway_dr_id, {
                            "data": {
                                "measurements": gw_measurements + [measurement],
                                "last_heartbeat": timestamp,
                            },
                            "metadata": {"updated_at": datetime.utcnow()},
                        })

                ingested += 1
                details.append({
                    "device": device_id,
                    "sensor": physical_sensor_id,
                    "sensor_dr_id": sensor_dr["_id"],
                    "action": "ingested",
                    "value": value,
                })

            except Exception as e:
                errors.append(f"{device_id}/{physical_sensor_id}: {str(e)}")
                logger.error("Ingestion error for %s/%s: %s", device_id, physical_sensor_id, e)

    logger.info("Ingestion complete: %d ingested, %d skipped, %d errors", ingested, skipped, len(errors))

    return {
        "ingested": ingested,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }
