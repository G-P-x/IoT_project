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
# used just to check the input
from cloud_platform.services.database_service import DatabaseService 
from cloud_platform.digital_twin.dt_factory import DTFactory

logger = logging.getLogger(__name__)

# Measurement units per sensor type
UNIT_MAP = {
    "t1": "°C", 
    "t2": "°C",
    "t3": "°C",
    "aq1": "ppm", # for C02
    "aq2": "ppb", # for SO2
    "s1": "m/s",
}

SENSOR_TYPE_MAP = {"sensor_t1": "temperature", 
                "sensor_aq1": "air_quality", 
                "sensor_t2": "temperature",
                "sensor_aq2": "air_quality"}


def _infer_sensor_type(physical_sensor_id: str) -> str:
    """
    Get the sensor type from the physical sensor ID.

    Examples:
        "sensor_t1"  → "temperature"
        "sensor_aq1" → "air_quality"
        "sensor_s1"  → "seismic_waves"

    Falls back to "temperature" if the sensor ID is not recognised.
    """
    return SENSOR_TYPE_MAP.get(physical_sensor_id, "temperature")

def _find_dr(db_service: DatabaseService, device_id: str) -> Optional[Dict]:
    """
    Look up the gateway DR by the physical device_id.

    Returns:
        The gateway DR document dict or None if not found.
    """
    # Try to find an existing gateway DR by device_id
    existing = db_service.query_drs("device", {"profile.device_id": device_id})
    if existing: # if the list is not empty, return the first match (there should ideally be only one)
        return existing[0]
    return None


def _link_sensor_to_gateway(db_service, gateway_id: str, sensor_dr_id: str) -> None:
    """
    Add a sensor DR _id to the gateway DR's data.sensors list (if not already present).
    """
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

def _create_gateway_record(gateway_id: str, gateway_info: Dict, sub: str | None) -> dict:
    ''' 
    
    Create a history record for the gateway status update. 

        Args:
            - gateway_id: the physical device_id of the gateway
            - gateway_info: the gateway_info dict from the DeviceResult, containing status, code, error, req_timestamp
            - sub: the operator user ID if this ingestion is triggered by an operator command, else None if triggered by telemetry

        Returns:    
            - A dict representing the history record to be saved, following the gateway_history.yaml template.

    '''
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
    temp = sensor_id.split("-")[1]  # e.g., "t1" or "aq1" from "sensor_t1"
    history_entry = history_factory.create_record({
        "record_type": temp,  # e.g., "t1" or "aq1" from "sensor_t1"
        "device_id": sensor_id,
        "unit": UNIT_MAP.get(temp),  # e.g., "°C" for "t1"
        "gateway_id": gateway_id,
        "timestamp": record.get("timestamp", datetime.now(timezone.utc).isoformat()),
        
        "data": {
            "value": record.get("value"),
            "threshold": record.get("threshold"),
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
    '''
    Create a gateway DR entry dict with the given info. The factory assigns _id.

    Args:
        - gateway_id: the physical device_id of the gateway
        - gateway_info: the gateway_info dict from the DeviceResult, containing status, code, error, req_timestamp
        - sensors: list of sensor IDs to link to this gateway DR
        - actuators: list of actuator IDs to link to this gateway DR

    Returns:
        -  A dict representing the gateway DR to be saved, following the gateway.yaml template.


    '''
    dr_factory = DRFactory("cloud_platform/virtualization/templates/gateway.yaml")
    initial_data = {
        "profile": {
            "name": f"Gateway {gateway_id}",
            "device_id": gateway_id,
        },
        "data": {
            "sensors": sensors,  # will be populated as sensors are linked
            "actuators": actuators,  # will be populated as actuators are linked
        },
        "metadata": {
            "last_update": gateway_info.get("req_timestamp", datetime.now(timezone.utc).isoformat()),
            "status": "active" if gateway_info.get("status") == "success" else "inactive",
        },
    }
    gateway_dr = dr_factory.create_dr("gateway", initial_data)
    return gateway_dr

def _create_sensor_dr_entry(gateway_id: str, sensor_id: str, record: Dict) -> dict:
    # ── Auto-create ──────────────────────────────────────────────────
    # Prefer explicit type from the incoming record when available, map it
    # to the canonical device_type values expected by the sensor schema.
    DEFAULT_DESCRIPTION = {
        "t1": "ground temperature sensor",
        "t2": "fumarole temperature sensor",
        "t3": "magmatic chamber temperature sensor",
        "aq1": "CO2 concentration sensor",
        "aq2": "SO2 concentration sensor",
        "s1": "seismic waves sensor",
    }
    
    temp = sensor_id.split("-")[1] if "-" in sensor_id else "NOT_SPECIFIED"  # e.g., "t1" or "aq1" from "sensor_t1"
    initial_data = {
        "profile": {
            "device_id": sensor_id,
            "device_type": temp,
            "unit": UNIT_MAP.get(temp, "NOT_SPECIFIED"),
            "description": DEFAULT_DESCRIPTION.get(temp, "NOT_SPECIFIED"),
            "gateway_id": gateway_id or "",
        },
    }

    dr_factory = DRFactory("cloud_platform/virtualization/templates/sensor.yaml")
    sensor_dr = dr_factory.create_dr("sensor", initial_data)
    return sensor_dr

def ingest_edge_results(db_service: DatabaseService, edge_results: Dict[str, DeviceResult], dt_factory: DTFactory, submitter: str | None, command: str | None) -> Dict:
    """
    Process the full edge_results dict returned by send_command_to_all_devices() and poll_gateways()
    and persist every successful sensor reading into the corresponding DRs.

    Args:
        db_service:   The DatabaseService instance (from current_app.config["DB_SERVICE"]).
        edge_results: Dict of gateway_id → DeviceResult as returned by the HTTP client after polling the gateways.
        dt_factory:   The DTFactory instance (from current_app.config["DT_FACTORY"]). Used for the CRUD operations on the DTs.
        submitter:    The operator user ID if this ingestion is triggered by an operator command, else None if triggered by telemetry.
        command:        The command string if this ingestion is triggered by an operator command, else None.

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
        logger.error("Validation error in edge_results: %s", ve)
        return {}

    for gateway_id, gtw_data in edge_results.items(): # gateway_id, data: DeviceResult
        assert isinstance(gtw_data, dict), f"Expected dict for device result, got {type(gtw_data)}"
        logger.info("Ingesting edge results from submitter '%s' with command '%s'", submitter, command)
        # phase 1: create a history record for the gateway with status "inactive" and source "operator" or "telemetry" based on the submitter
        history_entry = _create_gateway_record(gateway_id, gtw_data.get("gateway_info", {}), sub = submitter) # create a history record for the gateway, both in case of success and failure
        db_service.save_history_event(history_entry)

        # ----- First case: gateway-level failure (e.g. no response) -----
        if gtw_data.get("gateway_info", {}).get("status") != "success":
            logger.info("Processing gateway-level failure for device '%s'", gateway_id)
            # phase 2: find or create the gateway DR and set its status to "inactive" (if it already exists, just update the status and last_update timestamp, if it doesn't exist, create it with the status "inactive" and no sensors/actuators)
            dr_entry = _find_dr(db_service, gateway_id) # find an existing gateway DR by device_id (by default it searches in the "device" collection)

            if not dr_entry: # if no gateway DR exists, create one with status "inactive" and no sensors/actuators
                dr_entry = _create_gateway_dr_entry(gateway_id, gtw_data.get("gateway_info", {})) # create the gateway DR dictionary using gateway.yaml template
                dr_entry = db_service.add_dr(dr_entry)
                if not dr_entry:
                    logger.error("Failed to save new gateway DR for device '%s'", gateway_id)
                    continue

            db_service.update_dr("device", dr_entry["_id"], {
                                "metadata": {"last_update": gtw_data.get("gateway_info", {}).get("req_timestamp", datetime.now(timezone.utc).isoformat()),
                                            "status": "inactive"},
                            })
            
            # phase 3: update digital twin: add digital replica (gateway) in the DT 
            dt_factory.add_digital_replicas(dt_factory.dt_id, [{"type": "gateway", "id": dr_entry["_id"]}])
            continue
        
        # ----- Second case: gateway-level success -----
        logger.info("Processing gateway-level success for device '%s'", gateway_id)
        logger.info("Edge results: %s", gtw_data)
        sensors = []
        actuators = []
        digital_replicas = []
        
        for device_id, device_data in gtw_data.get("records", {}).items():
            try:
                logger.info("Processing device '%s' in gateway '%s'", device_id, gateway_id)
                device_data = dict(device_data)  # Ensure device_data is a dict
                # create a history entry and DR entry for the sensor record
                if device_data.get("type") == "sensor":

                    # Phase 1: create a history record for the sensor with status "active" or "inactive" based on the record status and source "operator" or "telemetry" based on the submitter
                    history_entry = _create_sensor_record(gateway_id, device_id, device_data, sub = submitter)
                    db_service.save_history_event(history_entry)
                    sensors.append(device_id)

                    # Phase 2: find or create the sensor DR and link it to the gateway DR (if not already linked)
                    dr_entry = _find_dr(db_service, device_id) # find an existing sensor DR by physical sensor_id
                    if not dr_entry: # if no sensor DR exists, create one
                        dr_entry = _create_sensor_dr_entry(gateway_id, device_id, device_data) # create the sensor DR dictionary using sensor.yaml template
                        dr_entry = db_service.add_dr(dr_entry) # and insert in the collection
                    
                    db_service.update_dr("sensor", dr_entry["_id"], {
                        "data": {
                            "value": device_data.get("value"),
                            "threshold": device_data.get("threshold"),
                        },
                        "metadata": {
                            "last_update": device_data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                            "status": "active" if device_data.get("status") == "OK" else "inactive",
                        },
                    })
                    
                elif device_data.get("type") == "actuator":
                    # Phase 1: create a history record for the actuator with status "active" or "inactive" based on the record status and source "operator" or "telemetry" based on the submitter
                    history_entry = _create_actuator_record(gateway_id, device_id, device_data, sub=submitter, command=command)
                    db_service.save_history_event(history_entry)
                    actuators.append(device_id)

                    # Phase 2: find or create the actuator DR and link it to the gateway DR (if not already linked)
                    dr_entry = _find_dr(db_service, device_id)
                    if dr_entry:
                        db_service.update_dr("actuator", dr_entry["_id"], {
                            "data": {
                                "status": device_data.get("status"),
                                "command": command,
                                "timestamp": device_data.get("timestamp"),
                            },
                            "metadata": {
                                "last_update": device_data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                            },
                        })
                else:
                    logger.warning("Unknown device type '%s' for device '%s' in gateway '%s'", device_data.get("type"), device_id, gateway_id)
                    continue

            except Exception as e:
                logger.error("Error processing device '%s' in gateway '%s': %s", device_id, gateway_id, e)
                continue
            
            digital_replicas.append({"type": dr_entry.get("profile", {}).get("device_type"), "id": dr_entry["_id"]}) # collect all digital replicas (sensors and actuators) to be added to the DT at the end of the loop

        # Update the gateway DR with the new sensors/actuators and status, keeping existing ones
        gateway_dr = _find_dr(db_service, gateway_id)
        if gateway_dr:
            existing_sensors = gateway_dr.get("data", {}).get("sensors", []) # get the existing sensors list from the gateway DR
            existing_actuators = gateway_dr.get("data", {}).get("actuators", []) # get the existing actuators list from the gateway DR
            
            for s in sensors:
                if s not in existing_sensors:
                    existing_sensors.append(s)
            
            for a in actuators:
                if a not in existing_actuators:
                    existing_actuators.append(a)
                    
            db_service.update_dr("device", gateway_dr["_id"], {
                "data": {
                    "sensors": existing_sensors,
                    "actuators": existing_actuators,
                },
                "metadata": {
                    "last_update": gtw_data.get("gateway_info", {}).get("req_timestamp", datetime.now(timezone.utc).isoformat()),
                    "status": "active" if gtw_data.get("gateway_info", {}).get("status") == "success" else "inactive",
                }
            })
        else:
            gateway_dr = _create_gateway_dr_entry(gateway_id, gtw_data.get("gateway_info", {}), sensors=sensors, actuators=actuators)
            db_service.add_dr(gateway_dr)
        digital_replicas.append({"type": gateway_dr.get("dr_type"), "id": gateway_dr["_id"]})
        
        # Finally, update the digital twin with the gateway DR reference
        dt_factory.add_digital_replicas(dt_factory.dt_id, digital_replicas)
