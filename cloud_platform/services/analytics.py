"""
Analytics Service Module
=========================
Provides an AggregationService that computes basic statistics (mean, min, max,
standard deviation) across measurements stored in Digital Replicas.

Architecture reasoning (from the lecture):
- The AggregationService is a concrete implementation of BaseService.
- It operates on the 'digital_replicas' list provided by the DT core and can
  optionally filter by DR type and measurement attribute.
- This keeps the service decoupled from any specific domain — it works on any
  DR whose 'data.measurements' follows the standard measurement dict format:
    { "measure_type": str, "value": numeric, "timestamp": str|datetime }
- In our IoT monitoring domain the measure_type values include 'temperature',
  'air_quality', 'seismic_waves', etc.
"""
import logging
from typing import Dict, List, Optional
import statistics
from cloud_platform.services.base import BaseService
from cloud_platform.services.database_service import DatabaseService
    
logger = logging.getLogger(__name__)


class AggregationService(BaseService):
    """
    Service for aggregating measurements across Digital Replicas.

    Given the DT data this service:
        1. Filters sensors by device_type (optional).
        2. Collects all sensors with an actual numeric value.
        3. Groups numeric values by device_type.
        4. Computes count, mean, min, max, and stddev for each group.
    """

    @staticmethod
    def _parse_sensor_value(raw_value: Optional[str]) -> Optional[float]:
        if raw_value is None:
            return None

        if isinstance(raw_value, (int, float)):
            return float(raw_value)

        if not isinstance(raw_value, str):
            return None

        normalized = raw_value.strip()
        if not normalized or normalized.lower() in {"none", "nan", "null"}:
            return None

        numeric_part = normalized.split()[0]
        try:
            return float(numeric_part)
        except ValueError:
            return None

    @staticmethod
    def _aggregate_sensors(sensor_records: List[Dict]) -> Dict:
        grouped: Dict[str, List[float]] = {}

        for sensor in sensor_records:
            device_type = sensor.get("device_type") or sensor.get("dr_type") or "unknown"
            value = AggregationService._parse_sensor_value(sensor.get("current_value"))
            if value is None:
                continue
            grouped.setdefault(device_type, []).append(value)

        if not grouped:
            return {"error": "No sensors with actual numeric values found."}

        stats: Dict[str, Dict[str, float]] = {}
        for device_type, values in grouped.items():
            try:
                stats[device_type] = {
                    "count": len(values),
                    "mean": round(statistics.mean(values), 4),
                    "min": min(values),
                    "max": max(values),
                    "stddev": round(statistics.stdev(values), 4) if len(values) > 1 else 0,
                }
            except (statistics.StatisticsError, ValueError) as exc:
                stats[device_type] = {"error": str(exc), "count": len(values)}

        return stats

    def __init__(self, config: dict = {}):
        '''
        Args:
            config : {
                    "device_type": str,
                },
            
        '''
        super().__init__(config)  
    

    def execute(self, data: Dict) -> Dict:
        """
        Run aggregation on measurements from the DT's Digital Replicas.

        Args:
            data:      Dict containing DT data.

        Returns:
            A dict mapping each measure_type to its computed statistics, e.g.:
            {
                "temperature": {"count": 10, "mean": 23.5, "min": 18.0, ...},
                ...
            }
        """
        if not data or not isinstance(data, dict):
            raise ValueError("Invalid data: missing DT")

        sensors = data.get("sensors")
        if sensors is None:
            return {"error": "Invalid sensor collection None in input data."}

        if not isinstance(sensors, list):
            return {"error": "Invalid sensor collection in input data. It is not a list."}

        if self.config.get("device_type"):
            sensors = [sensor for sensor in sensors if sensor.get("device_type") == self.config["device_type"]]

        numeric_sensors = [sensor for sensor in sensors if self._parse_sensor_value(sensor.get("current_value")) is not None]

        if not numeric_sensors:
            return {"error": "No sensors with actual numeric values found."}

        return {"service": __class__.__name__, "status": self._aggregate_sensors(numeric_sensors), "messages":"complete"}
    
class MonitorService(BaseService):
    """
    Service for monitoring measurements across Digital Replicas.

    This service receives the DR data and decides, based on the thresholds defined for each device_type, whether to trigger alerts or not.
    """
    @staticmethod
    def _is_monotonic_increasing(values: List[float]) -> bool:
        return len(values) >= 2 and all(current > previous for previous, current in zip(values, values[1:]))

    @staticmethod
    def _extract_history_values(history_records: List[Dict]) -> List[float]:
        values: List[float] = []
        for record in reversed(history_records):
            value = record.get("data", {}).get("value")
            if value is None:
                continue
            values.append(float(value))
        return values

    def execute(
        self,
        data: Dict,
        dr_type: str = 'sensor',
        device_type: str | None = None,
        db_service: Optional[DatabaseService] = None,
        history_limit: int = 20,
    ) -> Dict:
        if dr_type == "actuator" or dr_type == "gateway":
            return {"error": "Monitoring is applicable only to sensor-type Digital Replicas."}

        if not data or "digital_replicas" not in data:
            raise ValueError("Invalid data: missing 'digital_replicas' key")

        drs = [
            dr for dr in data["digital_replicas"]
            if dr_type is None or dr.get("dr_type") == dr_type or dr.get("type") == dr_type
        ]

        for dr in drs:
            data_fields = dr.get("data", {})
            value = data_fields.get("current_value")
            sensor_id = dr.get("profile", {}).get("device_id", dr.get("_id", "unknown"))

            if value is None:
                print(f"DR {sensor_id} has no 'current_value' in data, skipping.")
                continue

            min_threshold = data_fields.get("alert_threshold_min")
            if min_threshold is None:
                print(f"DR {sensor_id} has no 'alert_threshold_min' in data, skipping.")
                continue

            max_threshold = data_fields.get("alert_threshold_max")
            if max_threshold is None:
                print(f"DR {sensor_id} has no 'alert_threshold_max' in data, skipping.")
                continue

            if value > max_threshold:
                return {"alert": f"Value {value} exceeds max threshold {max_threshold} in DR {sensor_id}"}

            if value < min_threshold:
                continue

            if db_service is None:
                logger.debug(
                    "Skipping history analysis for DR %s because no db_service was provided.",
                    sensor_id,
                )
                continue

            history_records = db_service.query_history_records(sensor_id, limit=history_limit)
            if len(history_records) < 5:
                logger.debug(
                    "Skipping monotonic check for %s because only %d history records were found.",
                    sensor_id,
                    len(history_records),
                )
                continue

            values = self._extract_history_values(history_records)
            if len(values) < 5:
                logger.debug(
                    "Skipping monotonic check for %s because only %d numeric values were found.",
                    sensor_id,
                    len(values),
                )
                continue

            if self._is_monotonic_increasing(values):
                message = (
                    f"ALERT: Sensor {sensor_id} shows a monotonic increasing pattern "
                    f"in the last {len(values)} history records: {values}"
                )
                print(message)
                logger.warning(message)
                return {"alert": message, "sensor_id": sensor_id, "history_count": len(values)}

        return {}

class PredictionService(BaseService):
    """
    Service for making predictions based on measurements from Digital Replicas.

    This service could implement machine learning models or simple heuristics
    to forecast future values or detect anomalies.
    """
    def execute(self, data: Dict, dr_type: str = None, attribute: str = None) -> Dict:
        pass

class AlertingService(BaseService):
    """
    Service for generating alerts based on measurements from Digital Replicas.

    This service could define thresholds for certain attributes and trigger alerts
    when those thresholds are exceeded.
    """
    def execute(self, data: Dict, config: Dict = {}) -> Dict:
        '''
        Run alerting logic on measurements from the DT's Digital Replicas.
        
        Args:
            config:    Dict containing service configuration (stored in DT manifest).
                Optional — only consider DRs of this type (e.g. 'sensor').
                Optional — only consider measurements with this measure_type
            data:      List containing 'digital_replicas' (list of DR dicts).
                [
                    {
                        '_id_document': 'e0a244f2-8316-4cf5-ba41-e632e1ff8a53', 
                        'dr_type': 'sensor', 
                        'device_id': 'CCDDEEFF-t2', 
                        'device_type': 't2', 
                        'current_value': '56.44 °C', 
                        'threshold': '27.53 °C', 
                        'alert_level': 'critical'
                    }
                ]
        '''
        for dr in data:
            try:
                device_id = dr.get("device_id")
                dr_type = dr.get("dr_type")
                device_type = dr.get("device_type")
                current_value = float(dr.get("current_value").split(" ")[0])  # Extract numeric part
                threshold = float(dr.get("threshold").split(" ")[0])  # Extract numeric part
                alert_level = dr.get("alert_level")
            except AttributeError:
                logger.warning("Skipping DR with missing device_id.")
                continue
            except (ValueError, IndexError):
                logger.warning("Skipping DR with invalid current_value or threshold format.")
                continue

            if alert_level == "critical":
                message = (
                    f"ALERT: DR {device_id} (type: {dr_type}, device_type: {device_type}) "
                    f"has critical alert level.\nCurrent value: {current_value},\n"
                    f"Threshold: {threshold}"
                )
                logger.warning(message)
                return {"service": "alerting", "status": "alert", "message": message}

        return {"service": self.__name__, "status": "ok", "message": "No critical alerts found."}
 
class DashboardVisualization(BaseService):
    '''
    This service read the database and update the operator dashboard continously
    '''
    def execute(self, dr_data, config = {}):
        pass

if __name__ == "__main__":
# test AggregationService
    data = {
        "_id": "c5500d1e-c911-4e90-8dd4-250d04e9fd05",
        "digital_replicas": [],
        "services": [
            {
                "name": "AlertingService",
                "config": {},
                "status": "active",
                "added_at": "2026-07-05T11:11:07.175667"
            }
        ],
        "metadata": {
            "created_at": {
                "$date": "2026-07-02T10:15:21.111Z"
            },
            "updated_at": "2026-07-05T09:31:25.399636+00:00",
            "status": "OK"
        },
        "name": "etna",
        "description": "default",
        "sensors": [
            {
                "_id_document": "f04b8c23-608f-457d-9c05-664b41faf40e",
                "dr_type": "sensor",
                "device_id": "AABBCCDD-t1",
                "current_value": "25 °C",
                "threshold": "85.71 °C",
                "alert_level": "normal",
                "device_type": "t1"
            },
            {
                "_id_document": "8c3d3106-4d33-47d1-8122-47192a2eb5e2",
                "dr_type": "sensor",
                "device_id": "BBCCDDEE-t1",
                "current_value": "28 °C",
                "threshold": "74.39 °C",
                "alert_level": "normal",
                "device_type": "t1"
            },
            {
                "_id_document": "13660a38-080b-41d2-9f20-2531c6b56e62",
                "dr_type": "sensor",
                "device_id": "DDEEFF00-aq1",
                "current_value": "None ppm",
                "threshold": "31.45 ppm",
                "alert_level": None,
                "device_type": "aq1"
            },
            {
                "_id_document": "71bace25-daf3-48f5-8cc9-c83edcc294e8",
                "dr_type": "sensor",
                "device_id": "FF001122-s1",
                "current_value": "26.39 m/s",
                "threshold": "66.71 m/s",
                "alert_level": "normal",
                "device_type": "s1"
            },
            {
                "_id_document": "e0a244f2-8316-4cf5-ba41-e632e1ff8a53",
                "dr_type": "sensor",
                "device_id": "CCDDEEFF-t2",
                "current_value": "None °C",
                "threshold": "22.31 °C",
                "alert_level": None,
                "device_type": "t2"
            },
            {
                "_id_document": "6bb1753b-c407-44c4-a743-cb1a838eb7b7",
                "dr_type": "sensor",
                "device_id": "EEFF0011-t3",
                "current_value": "56.45 °C",
                "threshold": "83.81 °C",
                "alert_level": "normal",
                "device_type": "t3"
            },
            {
                "_id_document": "c0b19bea-dccf-4f0c-82cc-badefb957a35",
                "dr_type": "sensor",
                "device_id": "00112233-t2",
                "current_value": "None °C",
                "threshold": "50.68 °C",
                "alert_level": None,
                "device_type": "t2"
            },
            {
                "_id_document": "9e0650fc-9e75-4016-9d99-7d7c9cf37dc7",
                "dr_type": "sensor",
                "device_id": "22334455-aq2",
                "current_value": "None ppb",
                "threshold": "42.53 ppb",
                "alert_level": None,
                "device_type": "aq2"
            }
        ],
        "actuators": []
    }
    config ={}
    ags = AggregationService(config=config)
    stats = ags.execute(data)
    for key, value in stats.items():
        print(f"{key}: {value}")