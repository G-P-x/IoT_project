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
from cloud_platform.types.edge import ServiceResult
from cloud_platform.services.base import BaseService
from cloud_platform.services.base import BaseService
from cloud_platform.services.database_service import DatabaseService
from dataclasses import dataclass
    
    
    
logger = logging.getLogger(__name__)

UNIT_MAP_ANALYTICS = {
    "t1": "°C", 
    "t2": "°C",
    "t3": "°C",
    "aq1": "ppm", # for C02
    "aq2": "ppb", # for SO2
    "s1": "m/s^2",
}


@dataclass
class CustomError(Exception):
    message: str
    code: int | None = None

    def __str__(self):
        return f"{self.message} (code={self.code})" if self.code is not None else self.message
    
def check_data_input(data):
    '''
    Checks data is a dict and it contains the sensors list
    '''
    if not isinstance(data, dict):
        message = "data must be a dict"
        raise CustomError(message=message)

    sensors = data.get("sensors")
    if not isinstance(sensors, list):
        message = 'sensors field must be a list'
        raise CustomError(message=message)

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
    def _aggregate_sensors(sensor_records: List[Dict]) -> str:
        '''sensors records should receive an already sanitized list'''
        grouped: Dict[str, List[float]] = {}
        output_message = f""

        for sensor in sensor_records:
            device_type = sensor.get("device_type") or sensor.get("dr_type") or "unknown"
            value = _parse_sensor_value(sensor.get("current_value"))
            if value is None:
                continue
            grouped.setdefault(device_type, []).append(value)

        if not grouped:
            output_message += "No sensors with actual numeric values found."
            return output_message
        
        
        for device_type, values in grouped.items():
            try:
                temp_message = f"\n\t{device_type}\n"\
                    f"\t\tcount: {len(values)}\n"\
                    f"\t\tmean: {round(statistics.mean(values), 4)}\n"\
                    f"\t\tmin: {min(values)}\n"\
                    f"\t\tmax: {max(values)}\n"\
                    f"\t\tstddev: {round(statistics.stdev(values), 4) if len(values) > 1 else 0}\n\n"
                output_message += temp_message
            except (statistics.StatisticsError, ValueError) as exc:
                output_message += f"\n\t{device_type}\n"\
                    f"\t\tcount: {len(values)}\n"\
                    f"\t\terror: {str(exc)}"

        return output_message

    def __init__(self, config: dict = {}):
        '''
        Args:
            config : {
                    "device_type": str,
                },
            
        '''
        super().__init__(config)  
    

    def execute(self, data: Dict) -> ServiceResult:
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
        try:
            check_data_input(data)
            sensors = data.get("sensors")
            if self.config.get("device_type"):
                sensors = [sensor for sensor in sensors if sensor.get("device_type") == self.config["device_type"]]

            numeric_sensors = [sensor for sensor in sensors if _parse_sensor_value(sensor.get("current_value")) is not None]

            if not numeric_sensors:
                message = f"all sensor values are None"
                raise CustomError(message=message)
           
            message = self._aggregate_sensors(numeric_sensors)
            status = "service executed"
            
        
        except CustomError as e:
            status = "service executed"
        except Exception as e:
            status = "error executing the service"
            message = f"unexpected error as occurred:\n\t{e}"
        finally:
            output = ServiceResult(service= __class__.__name__, status=status, notify=["WEBHOOK_OPERATOR"], priority=self.priority, message=message )

        return output 
    
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

class AlertingService(BaseService):
    """
    Service for generating alerts based on measurements from Digital Replicas.

    This service could define thresholds for certain attributes and trigger alerts
    when those thresholds are exceeded.
    """
    def __init__(self, config: Dict = {}):
        super().__init__(config)
        self.inform = {
            1: ["WEBHOOK_ALERT", "ON_FIELD_ALARMS", "TELEGRAM"],
            2: ["WEBHOOK_ALERT"]
        }

    def execute(self, data: Dict) -> ServiceResult:
        '''
        Run alerting logic on measurements from the DT's Digital Replicas.
        
        Args:
            config:    Dict containing service configuration (stored in DT manifest).
                Optional — only consider DRs of this type (e.g. 'sensor').
                Optional — only consider measurements with this measure_type
            data: DT document.
        '''
        try:
            check_data_input(data)
            critical_count = 0
            temp = f""
            notify = None
            
            for dr in data.get("sensors"):
                single_dr_msg = f""
                
                try:
                    device_id = dr.get("device_id")
                    current_value = _parse_sensor_value(dr.get("current_value"))  # Extract numeric part
                    threshold = _parse_sensor_value(dr.get("threshold"))
                    alert_level = dr.get("alert_level", None)

                    if current_value is None or threshold is None or alert_level is None:
                        continue
                    
                    if alert_level == "critical":
                        critical_count += 1
                        self.priority = 1
                        unit : str = UNIT_MAP_ANALYTICS.get(dr.get("device_type"), "")
                        single_dr_msg += f"\tCRITICAL -- device ID: {device_id}"\
                            f"\t value: {current_value} {unit}"\
                            f"\t threshold: {threshold} {unit}\n"
  
                except AttributeError:
                    logger.warning("Skipping DR with missing device_id.")
                    continue
                except (ValueError, IndexError):
                    logger.warning("Skipping DR with invalid current_value or threshold format.")
                    continue
                finally:
                    temp += single_dr_msg

            notify = self.inform.get(self.priority)
            status = "service executed"
            message = f"\tcritical found: {critical_count}\n"
            message += temp
        except CustomError as e:
            status = "service executed"
            message = e.message
            notify = self.inform.get(self.priority)
        except Exception as e:
            status = "error executing the service"
            message = f"unexpected error as occurred {e}"
            notify = self.inform.get(self.priority)
        finally:
            output = ServiceResult(service= __class__.__name__, status=status, notify=notify, priority=self.priority,  message=message )

        return output
 
class DashboardVisualization(BaseService):
    '''
    This service read the database and update the operator dashboard continously with fresh DT reading
    '''
    def __init__(self, config: Dict = {}):
        super().__init__(config)
        self.priority = 2

    def execute(self, data) -> ServiceResult:
        try:
            check_data_input(data)
            status = "service executed"
            message = str(data)
        
        except CustomError as e:
            status = "service executed"
            message = e.message
        except Exception as e:
            status = "error executing the service"
            message = f"unexpected error as occurred {e}"
        finally:
            output = ServiceResult(service= __class__.__name__, status=status, notify=["WEBHOOK_OPERATOR"], priority=self.priority, message=message, )
            # output = {"service": __class__.__name__, "status": status, "message": message}

        return output

if __name__ == "__main__":
# test AggregationService
# run it 
#   C:...IoT_project> & c:....  IoT_project/.venv/Scripts/python.exe -m cloud_platform.services.analytics
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
                "current_value": "20 ppm",
                "threshold": "31.45 ppm",
                "alert_level": "normal",
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
                "current_value": "600 ppb",
                "threshold": "42.53 ppb",
                "alert_level": "critical",
                "device_type": "aq2"
            }
        ],
        "actuators": []
    }
    config ={}
    outputs = []
    # ags_1 = AggregationService(config=config)
    # output_1 = ags_1.execute(data)
    # outputs.append(output_1)

    ags_2 = AlertingService(config=config)
    output_2 = ags_2.execute(data)
    outputs.append(output_2)
    # for key, value in output_1.items():
    #     print(f"{key}: {value}")
    for output in outputs:
        print("\n\n")
        print(f"service: {output.service}")
        print(f"status: {output.status}")
        print(f"notify: {output.notify}")
        print(f"message: {output.message}")