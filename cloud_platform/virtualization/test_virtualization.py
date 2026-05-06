"""
Quick test module for the virtualization layer.
Run with: python -m cloud_platform.virtualization.test_virtualization
"""

from datetime import datetime, timezone
import os

from cloud_platform.virtualization.digital_replica.dr_factory import DRFactory
from cloud_platform.virtualization.digital_replica.history_factory import HistoryFactory
from cloud_platform.virtualization.digital_replica.dr_schema_registry import DRSchemaRegistry
from cloud_platform.virtualization.digital_replica.history_schema_registry import HistorySchemaRegistry


def _templates_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "templates")


def _template_path(name: str) -> str:
    return os.path.join(_templates_dir(), name)


def test_dr_factory():
    gateway_factory = DRFactory(_template_path("gateway.yaml"))
    gateway = gateway_factory.create_dr(
        "gateway",
        {
            "profile": {
                "name": "Gateway A",
                "description": "Main gateway",
                "device_id": "device_01",
                "location": "Field",
            },
            "data": {
                "sensors": [],
                "actuators": [],
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            },
            "metadata": {"status": "active"},
        },
    )
    assert gateway["dr_type"] == "gateway"
    assert "last_update" in gateway["metadata"]

    sensor_factory = DRFactory(_template_path("sensor.yaml"))
    sensor = sensor_factory.create_dr(
        "sensor",
        {
            "profile": {
                "name": "Sensor A",
                "sensor_id": "S-01",
                "sensor_type": "temperature",
                "unit": "C",
                "description": "Temp sensor",
                "gateway_id": gateway["_id"],
                "location": "Field",
            },
            "data": {
                "current_value": 22.5,
                "alert_threshold_min": 0.0,
                "alert_threshold_max": 100.0,
            },
            "metadata": {"status": "active"},
        },
    )
    assert sensor["dr_type"] == "sensor"

    actuator_factory = DRFactory(_template_path("actuator.yaml"))
    actuator = actuator_factory.create_dr(
        "actuator",
        {
            "profile": {
                "name": "Actuator A",
                "actuator_id": "A-01",
                "actuator_type": "siren",
                "description": "Alarm",
                "gateway_id": gateway["_id"],
                "location": "Field",
            },
            "data": {"current_command": "standby"},
            "metadata": {"status": "active"},
        },
    )
    assert actuator["dr_type"] == "actuator"


def test_history_factory():
    gateway_history_factory = HistoryFactory(_template_path("gateway_history.yaml"))
    gateway_event = gateway_history_factory.create_record(
        {
            "gateway_id": "gw-01",
            "data": {
                "status": "inactive",
                "timestamp": datetime.now(timezone.utc),
                "source": "monitor",
            },
        }
    )
    assert gateway_event["record_type"] == "gateway_status_event"

    sensor_history_factory = HistoryFactory(_template_path("sensor_history.yaml"))
    sensor_event = sensor_history_factory.create_record(
        {
            "sensor_id": "s-01",
            "gateway_id": "gw-01",
            "data": {
                "value": 24.1,
                "timestamp": datetime.now(timezone.utc),
                "source": "telemetry",
            },
        }
    )
    assert sensor_event["record_type"] == "sensor_reading_event"

    actuator_history_factory = HistoryFactory(_template_path("attuator_history.yaml"))
    actuator_event = actuator_history_factory.create_record(
        {
            "actuator_id": "a-01",
            "gateway_id": "gw-01",
            "data": {
                "command": "activate",
                "timestamp": datetime.now(timezone.utc),
                "result": "success",
                "source": "operator",
            },
        }
    )
    assert actuator_event["record_type"] == "actuator_command_event"


def test_schema_registries():
    dr_registry = DRSchemaRegistry()
    dr_registry.load_schema("gateway", _template_path("gateway.yaml"))
    dr_registry.load_schema("sensor", _template_path("sensor.yaml"))
    dr_registry.load_schema("actuator", _template_path("actuator.yaml"))
    assert dr_registry.get_validation_schema("gateway")

    history_registry = HistorySchemaRegistry()
    history_registry.load_schema("gateway_history", _template_path("gateway_history.yaml"))
    history_registry.load_schema("sensor_history", _template_path("sensor_history.yaml"))
    history_registry.load_schema("actuator_history", _template_path("attuator_history.yaml"))
    assert history_registry.get_validation_schema("gateway_history")


def main() -> None:
    test_dr_factory()
    test_history_factory()
    test_schema_registries()
    print("Virtualization layer tests: OK")


if __name__ == "__main__":
    main()
