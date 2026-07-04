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

    Given the DT data (list of DRs), this service:
        1. Filters DRs by type (optional).
        2. Collects all measurements, optionally filtering by attribute.
        3. Groups values by measure_type.
        4. Computes count, mean, min, max, and stddev for each group.
    """

    def execute(self, data: Dict, dr_type: str = None, attribute: str = None) -> Dict:
        """
        Run aggregation on measurements from the DT's Digital Replicas.

        Args:
            data:      Dict containing 'digital_replicas' (list of DR dicts).
            dr_type:   Optional — only aggregate DRs of this type (e.g. 'sensor').
            attribute: Optional — only aggregate measurements with this measure_type
                       (e.g. 'temperature').

        Returns:
            A dict mapping each measure_type to its computed statistics, e.g.:
            {
                "temperature": {"count": 10, "mean": 23.5, "min": 18.0, ...},
                ...
            }
        """
        if not data or "digital_replicas" not in data:
            raise ValueError("Invalid data: missing 'digital_replicas' key")

        # Step 1 — Filter DRs by type if specified
        drs = [
            dr for dr in data["digital_replicas"]
            if dr_type is None or dr.get("type") == dr_type
        ]

        if not drs:
            return {"error": f"No digital replicas found of type '{dr_type}'"}

        # Step 2 — Collect measurements, optionally filtering by attribute
        all_measurements = []
        for dr in drs:
            measurements = dr.get("data", {}).get("measurements", [])
            if attribute:
                measurements = [m for m in measurements if m.get("measure_type") == attribute]
            all_measurements.extend(measurements)

        if not all_measurements:
            return {"error": f"No measurements found for attribute '{attribute}'"}

        # Step 3 — Group numeric values by measure_type
        grouped: Dict[str, list] = {}
        for m in all_measurements:
            mtype = m.get("measure_type", "unknown")
            grouped.setdefault(mtype, []).append(float(m["value"]))

        # Step 4 — Compute statistics per group
        stats = {}
        for mtype, values in grouped.items():
            try:
                stats[mtype] = {
                    "count": len(values),
                    "mean": round(statistics.mean(values), 4),
                    "min": min(values),
                    "max": max(values),
                    "stddev": round(statistics.stdev(values), 4) if len(values) > 1 else 0,
                }
            except (statistics.StatisticsError, ValueError) as e:
                stats[mtype] = {"error": str(e), "count": len(values)}

        return stats
    
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

        return {"service": "alerting", "status": "ok", "message": "No critical alerts found."}