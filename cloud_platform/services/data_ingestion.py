"""
Data Ingestion Service
=======================
Processa le risposte dei gateway e persiste le letture dei sensori come
record Digital Replica in MongoDB.

Modifiche rispetto alla versione precedente:
    - _infer_sensor_type: riconosce i MAC-based ID (es. A4CF12F5A331-t1)
    - update_dr sensore: salva value, threshold, severity, message
    - _create_sensor_record: salva threshold, severity, message nella history
    - ingest_edge_results: chiama NotificationService su severity=critical
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic_core import ValidationError

from cloud_platform.types.edge import DeviceResult, EdgeResults
from cloud_platform.virtualization.digital_replica.dr_factory import DRFactory
from cloud_platform.virtualization.digital_replica.history_factory import HistoryFactory
from cloud_platform.services.database_service import DatabaseService

logger = logging.getLogger(__name__)

# Unità di misura per tipo sensore
UNIT_MAP = {
    "temperature":   "°C",
    "air_quality":   "ppm",
    "seismic_waves": "m/s2",
    "humidity":      "%",
    "gas":           "ppm",
}


def _infer_sensor_type(physical_sensor_id: str) -> str:
    """
    Inferisce il tipo di sensore dal suffisso del physical_sensor_id.

    Supporta il formato MAC-based del firmware (es. "A4CF12F5A331-t1"):
        *-t1, *-t2       → temperature
        *-aq1, *-aq2     → air_quality
        *-s1             → seismic_waves

    Fallback → "unknown"
    """
    parts = physical_sensor_id.rsplit("-", 1)
    if len(parts) == 2:
        suffix = parts[1].lower()
        if suffix.startswith("t"):
            return "temperature"
        if suffix.startswith("aq"):
            return "air_quality"
        if suffix.startswith("s"):
            return "seismic_waves"
    return "unknown"


def _find_dr(db_service: DatabaseService, device_id: str) -> Optional[Dict]:
    """
    Cerca un DR per device_id nella device_collection.
    Tutti i DR (gateway, sensor, actuator) condividono la stessa collection
    per come è configurato DRSchemaRegistry.
    """
    existing = db_service.query_drs("device", {"profile.device_id": device_id})
    if existing:
        return existing[0]
    return None


def _link_sensor_to_gateway(db_service, gateway_id: str, sensor_dr_id: str) -> None:
    try:
        gw = db_service.get_dr("gateway", gateway_id)
        if not gw:
            return
        sensors_list = gw.get("data", {}).get("sensors", [])
        if sensor_dr_id not in sensors_list:
            sensors_list.append(sensor_dr_id)
            db_service.update_dr("gateway", gateway_id, {
                "data": {"sensors": sensors_list},
            })
    except Exception as e:
        logger.warning("Failed to link sensor %s to gateway %s: %s", sensor_dr_id, gateway_id, e)


def _resolve_gateway_dr_id(db_service, device_id: str) -> Optional[str]:
    results = db_service.query_drs("gateway", {"profile.device_id": device_id})
    if results:
        return results[0]["_id"]
    return None


def _create_gateway_record(gateway_id: str, gateway_info: Dict, sub: str | None) -> dict:
    history_factory = HistoryFactory("cloud_platform/virtualization/templates/gateway_history.yaml")
    history_entry = history_factory.create_record({
        "device_id":  gateway_id,
        "timestamp":  gateway_info.get("req_timestamp", datetime.now(timezone.utc).isoformat()),
        "data": {
            "status":      "active" if gateway_info.get("status") == "success" else "inactive",
            "source":      "operator" if sub else "telemetry",
            "operator_id": sub if sub else None,
        },
    })
    return history_entry


def _create_sensor_record(
    gateway_id: str,
    sensor_id:  str,
    record:     Dict,
    sub:        str | None,
) -> dict:
    """
    Crea un record storico per la lettura di un sensore.
    Ora include threshold, severity e message.
    """
    history_factory = HistoryFactory("cloud_platform/virtualization/templates/sensor_history.yaml")
    history_entry = history_factory.create_record({
        "device_id":  sensor_id,
        "gateway_id": gateway_id,
        "timestamp":  record.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "data": {
            "value":       record.get("value"),
            "threshold":   record.get("threshold"),   # soglia critica embedded dal gateway
            "severity":    record.get("severity"),    # none / critical / error
            "message":     record.get("message", ""),
            "status":      "active" if record.get("status") == "OK" else "inactive",
            "source":      "operator" if sub else "telemetry",
            "operator_id": sub if sub else None,
        },
    })
    return history_entry


def _create_actuator_record(
    gateway_id:  str,
    actuator_id: str,
    record:      Dict,
    sub:         str | None,
    command:     str | None,
) -> None:
    history_factory = HistoryFactory("cloud_platform/virtualization/templates/actuator_history.yaml")
    history_factory.create_record({
        "device_id":  actuator_id,
        "gateway_id": gateway_id,
        "timestamp":  record.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "data": {
            "command":     command,
            "status":      "active" if record.get("status") == "OK" else "inactive",
            "source":      "operator" if sub else "telemetry",
            "operator_id": sub if sub else None,
        },
    })


def _create_gateway_dr_entry(
    gateway_id:   str,
    gateway_info: Dict,
    sensors:      List[str] = [],
    actuators:    List[str] = [],
) -> dict:
    dr_factory = DRFactory("cloud_platform/virtualization/templates/gateway.yaml")
    initial_data = {
        "profile": {
            "name":      f"Gateway {gateway_id}",
            "device_id": gateway_id,
        },
        "data": {
            "sensors":   sensors,
            "actuators": actuators,
        },
        "metadata": {
            "last_update": gateway_info.get("req_timestamp", datetime.now(timezone.utc).isoformat()),
            "status":      "active" if gateway_info.get("status") == "success" else "inactive",
        },
    }
    return dr_factory.create_dr("gateway", initial_data)


def _create_sensor_dr_entry(gateway_id: str, sensor_id: str, record: Dict) -> dict:
    sensor_type = _infer_sensor_type(sensor_id)
    unit        = UNIT_MAP.get(sensor_type, "")

    initial_data = {
        "profile": {
            "device_id":   sensor_id,
            "device_type": sensor_type,
            "unit":        unit,
            "description": f"Auto-created from gateway '{gateway_id}' response",
            "gateway_id":  gateway_id or "",
        },
    }

    dr_factory = DRFactory("cloud_platform/virtualization/templates/sensor.yaml")
    sensor_dr  = dr_factory.create_dr("sensor", initial_data)
    logger.info("Auto-created sensor DR (type=%s) for gateway '%s'", sensor_type, gateway_id)
    return sensor_dr


def _parse_record_timestamp(value: str | None) -> Optional[datetime]:
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


def ingest_edge_results(
    db_service:           DatabaseService,
    edge_results:         Dict[str, DeviceResult],
    submitter:            str | None,
    command:              str | None,
    notification_service=None,
) -> Dict:
    """
    Processa edge_results e persiste ogni lettura nei DR MongoDB.
    Se severity="critical" e notification_service è fornito, invia gli allarmi.

    Args:
        db_service:            DatabaseService connesso.
        edge_results:          Dict gateway_id → DeviceResult.
        submitter:             ID operatore (None se telemetria automatica).
        command:               Comando inviato (None se telemetria automatica).
        notification_service:  NotificationService (opzionale).
    """
    try:
        EdgeResults(edge=edge_results)
    except ValidationError as ve:
        print("Validation error in edge_results:", ve)
        return {}

    for gateway_id, gtw_data in edge_results.items():
        assert isinstance(gtw_data, dict), f"Expected dict, got {type(gtw_data)}"

        # ── Gateway-level failure ────────────────────────────────────
        if gtw_data.get("gateway_info", {}).get("status") != "success":
            history_entry = _create_gateway_record(gateway_id, gtw_data.get("gateway_info", {}), sub=submitter)
            db_service.save_history_event(history_entry)

            dr_entry = _find_dr(db_service, gateway_id)
            if not dr_entry:
                dr_entry = _create_gateway_dr_entry(gateway_id, gtw_data.get("gateway_info", {}))
                dr_entry = db_service.add_dr(dr_entry)
                if not dr_entry:
                    logger.error("Failed to save new gateway DR for device '%s'", gateway_id)
                    continue

            db_service.update_dr("device", dr_entry["_id"], {
                "metadata": {
                    "last_update": gtw_data.get("gateway_info", {}).get("req_timestamp", datetime.now(timezone.utc).isoformat()),
                    "status":      "inactive",
                },
            })
            continue

        # ── Gateway-level success ────────────────────────────────────
        history_entry = _create_gateway_record(gateway_id, gtw_data.get("gateway_info", {}), sub=submitter)
        db_service.save_history_event(history_entry)

        sensors   = []
        actuators = []

        for device_id, device_data in gtw_data.get("records", {}).items():

            if device_data.get("type") == "sensor":
                # Storico
                history_entry = _create_sensor_record(gateway_id, device_id, device_data, sub=submitter)
                db_service.save_history_event(history_entry)
                sensors.append(device_id)

                # DR
                dr_entry = _find_dr(db_service, device_id)
                if not dr_entry:
                    dr_entry = _create_sensor_dr_entry(gateway_id, device_id, device_data)
                    dr_entry = db_service.add_dr(dr_entry)

                # Aggiorna il DR con tutti i campi del record corrente
                db_service.update_dr("sensor", dr_entry["_id"], {
                    "data": {
                        "value":     device_data.get("value"),
                        "threshold": device_data.get("threshold"),
                        "severity":  device_data.get("severity"),
                        "message":   device_data.get("message", ""),
                    },
                    "metadata": {
                        "last_update": device_data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                        "status":      "active" if device_data.get("status") == "OK" else "inactive",
                    },
                })

                # Notifica allarme se severity critica
                if device_data.get("severity") == "critical" and notification_service:
                    notification_service.send_alarm(
                        sensor_id=device_id,
                        gateway_id=gateway_id,
                        value=device_data.get("value"),
                        threshold=device_data.get("threshold"),
                        message=device_data.get("message", ""),
                    )

            elif device_data.get("type") == "actuator":
                _create_actuator_record(gateway_id, device_id, device_data, sub=submitter, command=command)
                actuators.append(device_id)

                dr_entry = _find_dr(db_service, device_id)
                if dr_entry:
                    db_service.update_dr("actuator", dr_entry["_id"], {
                        "data": {
                            "status":    device_data.get("status"),
                            "command":   command,
                            "timestamp": device_data.get("timestamp"),
                        },
                        "metadata": {
                            "last_update": device_data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                        },
                    })

        # Aggiorna il gateway DR
        gateway_dr = _find_dr(db_service, gateway_id)
        if gateway_dr:
            existing_sensors   = gateway_dr.get("data", {}).get("sensors",   [])
            existing_actuators = gateway_dr.get("data", {}).get("actuators", [])

            for s in sensors:
                if s not in existing_sensors:
                    existing_sensors.append(s)
            for a in actuators:
                if a not in existing_actuators:
                    existing_actuators.append(a)

            db_service.update_dr("device", gateway_dr["_id"], {
                "data": {
                    "sensors":   existing_sensors,
                    "actuators": existing_actuators,
                },
                "metadata": {
                    "last_update": gtw_data.get("gateway_info", {}).get("req_timestamp", datetime.now(timezone.utc).isoformat()),
                    "status":      "active",
                },
            })
        else:
            dr_entry = _create_gateway_dr_entry(
                gateway_id, gtw_data.get("gateway_info", {}),
                sensors=sensors, actuators=actuators,
            )
            db_service.add_dr(dr_entry)