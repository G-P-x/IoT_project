import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from config.config import Config
from datetime import datetime, timezone

# payload format:
# {
#     "sensors": ["t1", "aq1", "s1"],  # optional, if not provided, assume all sensors for the parameter
#     "command": "cmd_01",
# }

TEMPERATURE = 1
SIESMIC_WAVES = 2
AIR_QUALITY = 3

logger = logging.getLogger(__name__)
cfg = Config()

FAILED_REQUEST_CODE = 404 # code error to use when the request fails and we don't have a response object to get the status code from. 
MALFORMED_DATA = 104

def send_alarm():
    pass

def _send_http_command(url, command, field_devices):
    """
    Send an HTTP POST to a single edge device.

    Args:
        device_url: Base URL of the gateways (e.g. "http://127.0.0.1:5000").
        command:    The command string (e.g. "cmd_01").
        field_devices:    list of device IDs to target, if empty, assume all.

    Returns:
        HTTP 200 with JSON body containing the result of the command execution, e.g.:
        {
            "time_stamp": "2024-06-01T12:00:00Z",
            "records": [
                {
                    "status": "OK",
                    "type": "sensor",
                    "id": "84F3EB12A0BC-t1",
                    "value": 24.8,
                    "message": "Temperature acquired",
                    "timestamp": "2026-02-16T15:40:12Z"
                },
                {
                    "status": "OK",
                    "type": "sensor",
                    "id": "84F3EB12A0BC-aq1",
                    "value": 10.2,
                    "timestamp": "2024-06-01T12:00:00Z",
                    "operator_id": None,
                    "command_id": None
                },
                {
                    "status": "ERROR",
                    "type": "sensor",
                    "id": "84F3EB12A0BC-x1",
                    "value": null,
                    "message": "Invalid sensor_id",
                    "timestamp": "2026-02-16T15:40:12Z"
                }
            ]
        }
        
    Returns:
        A dict with the following structure:
        {
            "status": "success" | "error",
            "code": HTTP status code (if success) or CUSTOM_ERROR_CODE (if error),
            "body": Response body (if success),
            "error": Error description (if error),
            "req_timestamp": Timestamp of the request
        }
    """
    # sending payload structure
    # {
    #  "command": "cmd_01",
    #  "sensors": ["t1", "aq1"],
    # } 
    payload = {"command": command, "sensors": field_devices}  # kept sensors as key for backwards compatibility, even if it's actually a list of field device IDs. 
    # The edge device will interpret the list of field device IDs as the target devices for the command. 
    # If the list is empty, it will apply the command to all sensors linked to the gateway.
    

    try:
        print(f"Sending command to {url} with payload: {payload}")
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        body = response.json()
        # logger.info("HTTP notify → %s  response: %s – %s", url, response.status_code, response.text)
        return {"status": "success", "code": response.status_code, "req_timestamp": datetime.now(timezone.utc).isoformat(), "body": body}
    except requests.RequestException as e:
        logger.error("HTTP notify → %s  failed: %s", url, e)
        return {"status": "error", "code": FAILED_REQUEST_CODE, "error": str(e), "req_timestamp": datetime.now(timezone.utc).isoformat()}


def send_command_to_sensors(command, target: dict):
    """
    Fan-out a command to multiple edge devices in parallel.

    Uses a ThreadPoolExecutor so that every device request runs concurrently.
    The calling Flask thread blocks until ALL workers finish, but other Flask
    request threads keep running normally.

    Args:
        command:    The command string (e.g. "cmd_01").
        target:    A dict mapping gateway IDs to their field devices.
        
    Returns:
        A dict mapping gateway_id → result dict, where each result contains:
            - "status":  "success" | "error"
            - "code":    HTTP status code (if success)
            - "body":    Response body (if success)
            - "error":   Error description (if error)
    """
    
    gateway_ids = list(target.keys()) if isinstance(target, dict) else list(cfg.EDGE_DEVICES.keys()) # get the list of gateway IDs from the target dict, or use all configured gateways if target is not a dict, basically sending the command to all devices..

    field_devices = list(target.values()) if isinstance(target, dict) else [[] for _ in gateway_ids] # get the list of field devices for each gateway from the target dict, or use empty lists if target is not a dict (which means all devices for each gateway)
    # if field_devices is empty for a gateway, the edge device will interpret that as "apply the command to all sensors linked to the gateway", so we can safely use empty lists for the case where target is not a dict (i.e. send to all devices).

    if gateway_ids is not None:
        urls = [f"{cfg.EDGE_DEVICES[gateway_id]}{cfg.COMMAND_ENDPOINT}" for gateway_id in gateway_ids] # gets the list of base URLs for the target gateways, or all configured gateways if target is not a dict.
    else:
        urls = [f"{cfg.EDGE_DEVICES[gateway_id]}{cfg.COMMAND_ENDPOINT}" for gateway_id in list(cfg.EDGE_DEVICES.values())] 

    print(f"send_command_to_sensors → Target gateways: {gateway_ids}")
    print(f"send_command_to_sensors → Target field devices: {field_devices}")
    print(f"send_command_to_sensors → Target URLs: {urls}")
    assert len(urls) > 0, "No devices to send command to."

    # If both gateway_ids and field_devices are provided, check that they have the same length. This is a sanity check to ensure that the input dict is well-formed (each gateway_id should correspond to one field device URL).
    assert len(urls) == len(field_devices) == len(gateway_ids), "Length of base_urls, field_devices and gateway_ids must match."

    results = {} # store results per gateway_id

    with ThreadPoolExecutor(max_workers=len(gateway_ids) or 1) as executor:
        # Submit one task per device
        future_to_device = {
            executor.submit(_send_http_command, urls[i], command, field_devices[i]): gateway_ids[i]
            for i in range(len(gateway_ids))
        }

        # Collect results as they complete
        for future in as_completed(future_to_device):
            gateway_id = future_to_device[future]
            try:
                response = future.result()
                results[gateway_id] = _normalize_result(response) # Normalize the result into a consistent format for data processing

            except Exception as e:
                logger.info(f"Error sending command to gateway {gateway_id}: {e}")
                #
                results[gateway_id] = _normalize_result({"status": "error", "code": FAILED_REQUEST_CODE, "error": str(e), "req_timestamp": datetime.now(timezone.utc).isoformat()})
                
    return results

def _normalize_result(result):
    '''
    Normalize the result from a gateway poll or command into a consistent format for data processing.

    Args:
    result: The raw result dict from _poll_gateway or _send_http_command, expected to have "status", "code", "req_timestamp", and "body" keys.
    
    Returns:
    A normalized dict with the following structure:
    {
        "gateway_info": {
            "status": "success" | "error",
            "code": HTTP status code (if success),
            "error": Error message (if error),
            "req_timestamp": Timestamp of the poll request
        },
        "records": {
            record_id: {
                "type": sensor/actuator,
                "status": OK/error,
                "severity": severity level (if error),
                "value": sensor value (if success),
                "message": message from the gateway,
                "timestamp": timestamp of the record at the sensor/actuator level
                "threshold": threshold value
            },
            ...
        }
    }
    '''
    if not isinstance(result, dict) or "status" not in result:
        raise ValueError("Invalid result format: expected a dict with a 'status' key")
    
    def _normalize_raw_records(body):
        if isinstance(body, list):
            records = []
            for json_item in body:  # Ensure each item is a dict
                json_item = dict(json_item)  # Convert to dict if it's not already
                rec = json_item.get("record", json_item)
                rec = dict(rec)  # Ensure rec is a dict
                records.append({
                    "id": rec.get("id"),
                    "type": rec.get("type"),
                    "status": rec.get("status"),
                    "severity": rec.get("severity"),
                    "value": rec.get("value"),
                    "message": rec.get("message"),
                    "timestamp": rec.get("timestamp"),
                    "threshold": rec.get("threshold"),
                })
            return records
        if isinstance(body, dict) and isinstance(body.get("body"), (list, dict)):
            return _normalize_raw_records(body.get("body"))

        if isinstance(body, dict) and isinstance(body.get("records"), list):
            records = []
            for rec in body.get("records", []):
                if not isinstance(rec, dict):
                    continue
                records.append({
                    "id": rec.get("id"),
                    "type": rec.get("type", "sensor"),
                    "status": rec.get("status"),
                    "severity": rec.get("severity"),
                    "value": rec.get("value"),
                    "message": rec.get("message"),
                    "timestamp": rec.get("timestamp"),
                    "threshold": rec.get("threshold"),
                })
            return records
        return []

    def _normalize_records(body):
        raw_records = _normalize_raw_records(body)
        records = {}
        for rec in raw_records:
            record_id = rec.get("id")
            if not record_id:
                continue
            records[record_id] = {
                "type": rec.get("type"),
                "status": rec.get("status"),
                "severity": rec.get("severity"),
                "value": rec.get("value"),
                "message": rec.get("message"),
                "timestamp": rec.get("timestamp"),
                "threshold": rec.get("threshold"),
            }
        return records
    
    raw_records = _normalize_raw_records(result.get("body")) if result.get("status") == "success" else []
    normalized = {
        "gateway_info": {
            "status": result.get("status"),
            "code": result.get("code"),
            "error": result.get("error") if result.get("status") == "error" else None, # This error is not received from the gateway, but generated by the client_http module when the request fails.
            "req_timestamp": result.get("req_timestamp"),
        },
        "raw_records": raw_records,
        "records": _normalize_records(result.get("body")) if result.get("status") == "success" else {},
    }
    
    # If not successful or unrecognized format, return as is
    return normalized

def _poll_gateway(url) -> dict:
    '''
    Poll a single gateway for new data.
    Returns:
        A List of json objects with the following structure:
        [
            {
                "time_stamp": "2026-05-05T14:30:00.000Z", # when the data was recorded at the gateway
                "record": {
                    "id": "mpu6050_01",
                    "type": "accelerometer",
                    "status": "ERROR",
                    "severity": "critical",
                    "value": null,
                    "message": "MPU-6050 connection lost",
                    "timestamp": "2026-02-16T15:40:12Z" # when the record was recorded at the sensor/actuator level
                }
            },
            ...
        ]
    '''
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        return {"status": "success", "code": resp.status_code, "req_timestamp": datetime.now(timezone.utc).isoformat(), "body": body}
    
    except requests.RequestException as e:
        logger.error("HTTP poll → %s failed: %s", url, e)
        return {"status": "error", "code": FAILED_REQUEST_CODE, "error": str(e), "req_timestamp": datetime.now(timezone.utc).isoformat()}

# Called in the app.py. This function will be used to automatically poll gateways at regular intervals (e.g. every minute) to check for new data or alerts.
def poll_gateways():
    '''
    Poll all gateways for new data.
    '''
    results = {}
    # print(f"Polling gateways: {list(cfg.EDGE_DEVICES.keys())}")
    # print(f"Polling URLs: {[url for url in cfg.EDGE_DEVICES.values()]}")

    with ThreadPoolExecutor(max_workers=len(cfg.EDGE_DEVICES) or 1) as executor:
        # Submit one polling task per  gateway
        future_to_gateway = {
            executor.submit(_poll_gateway, f"{url}{cfg.POLL_ENDPOINT}"): gateway_id
            for gateway_id, url in cfg.EDGE_DEVICES.items()
        }
        # creates a dict mapping Future (an object created by executor.submit) → gateway_id, so we can identify which gateway corresponds 
        # to each completed Future later on. The keys of future_to_gateway are Future objects representing the asynchronous execution 
        # of _poll_gateway for each gateway, and the values are the corresponding gateway IDs.
        # This allows us to track which Future corresponds to which gateway when we collect results

    # Collect results as they complete
    for future in as_completed(future_to_gateway):
        gateway_id = future_to_gateway[future]
        try:
            result = future.result() # Waits for the asynchronous task to complete (_poll_gateway) and retrieves its result. 
            results[gateway_id] = _normalize_result(result) # Store the result in the results dict, keyed by gateway_id. 
            #  Each result is a dict with "status", "code", "body" (if success) or "error" (if error).
        except Exception as e:
            # print(f"Error polling gateway {gateway_id}: {e}")
            logger.error("Polling gateway '%s' failed: %s", gateway_id, str(e))
            results[gateway_id] = _normalize_result({"status": "error", "code": FAILED_REQUEST_CODE, "error": str(e), "req_timestamp": datetime.now(timezone.utc).isoformat()})

    return results


def test():
    import json as json_module
    from unittest.mock import patch, MagicMock

    # ── 1. Mock Configuration ───────────────────────────────────────────
    # Temporarily override cfg variables for predictable testing
    cfg.EDGE_DEVICES = {
        "gateway_01": "http://192.168.1.10:5000",
        "gateway_02": "http://192.168.1.11:5000",
        "gateway_03": "http://192.168.1.99:5000", # We will simulate an unreachable device here
    }
    cfg.COMMAND_ENDPOINT = "/command"
    cfg.POLL_ENDPOINT = "/poll"

    # ── 2. Mock Data & Functions ────────────────────────────────────────
    # Responses for the POST command
    mock_post_responses = {
        "gateway_01": {
            "time_stamp": "2026-05-22T12:00:00Z",
            "records": [
                {
                    "id": "t1",
                    "type": "sensor",
                    "status": "OK",
                    "severity": "info",
                    "value": 24.8,
                    "message": "Temperature acquired",
                    "timestamp": "2026-05-22T12:00:00Z",
                }
            ]
        },
        "gateway_02": {
            "time_stamp": "2026-05-22T12:00:00Z",
            "records": [
                {
                    "id": "aq1",
                    "type": "sensor",
                    "status": "OK",
                    "severity": "info",
                    "value": 10.2,
                    "message": "Air quality acquired",
                    "timestamp": "2026-05-22T12:00:00Z",
                }
            ]
        }
    }

    # Responses for the GET poll
    mock_get_responses = {
        "gateway_01": [
            {
                "time_stamp": "2026-05-22T12:01:00Z",
                "record": {
                    "id": "t1",
                    "type": "sensor",
                    "status": "OK",
                    "severity": "info",
                    "value": 24.8,
                    "message": "read successful",
                    "timestamp": "2026-05-22T12:01:00Z",
                }
            }
        ],
        "gateway_02": [
            {
                "time_stamp": "2026-05-22T12:01:00Z",
                "record": {
                    "id": "aq1",
                    "type": "sensor",
                    "status": "OK",
                    "severity": "info",
                    "value": 10.2,
                    "message": "read successful",
                    "timestamp": "2026-05-22T12:01:00Z",
                }
            }
        ]
    }

    def _get_gateway_id_from_url(url):
        for gid, base_url in cfg.EDGE_DEVICES.items():
            if url.startswith(base_url):
                return gid
        return None

    def mock_requests_post(url, json=None, timeout=None):
        gateway_id = _get_gateway_id_from_url(url)
        if gateway_id == "gateway_03" or not gateway_id:
            raise requests.ConnectionError(f"Mock: Gateway {gateway_id} unreachable")

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = mock_post_responses.get(gateway_id, {})
        resp.text = json_module.dumps(resp.json.return_value)
        return resp

    def mock_requests_get(url, timeout=None):
        gateway_id = _get_gateway_id_from_url(url)
        if gateway_id == "gateway_03" or not gateway_id:
            raise requests.ConnectionError(f"Mock: Gateway {gateway_id} unreachable")

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = mock_get_responses.get(gateway_id, [])
        resp.text = json_module.dumps(resp.json.return_value)
        return resp

    def _assert_normalized_structure(label, results):
        assert isinstance(results, dict), f"{label}: expected dict results"
        for gateway_id, gateway_result in results.items():
            assert isinstance(gateway_result, dict), f"{label}: {gateway_id} result is not dict"
            assert "gateway_info" in gateway_result, f"{label}: {gateway_id} missing gateway_info"
            assert "records" in gateway_result, f"{label}: {gateway_id} missing records"

            info = gateway_result.get("gateway_info", {})
            assert isinstance(info, dict), f"{label}: {gateway_id} gateway_info is not dict"
            for key in ("status", "code", "error", "req_timestamp"):
                assert key in info, f"{label}: {gateway_id} gateway_info missing {key}"

            records = gateway_result.get("records", {})
            assert isinstance(records, dict), f"{label}: {gateway_id} records is not dict"
            if info.get("status") == "success":
                assert records, f"{label}: {gateway_id} expected non-empty records for success"
            for record_id, record in records.items():
                assert isinstance(record, dict), f"{label}: {gateway_id}:{record_id} record is not dict"
                for key in ("type", "status", "severity", "value", "message", "timestamp"):
                    assert key in record, f"{label}: {gateway_id}:{record_id} missing {key}"
        print(f"{label}: normalized structure OK")

    # Change this path if your module hierarchy differs
    MODULE_PATH = "cloud_platform.application.client_http"


    # ── TEST 1: send_command_to_sensors ─────────────────────────────────
    print("\n" + "=" * 60)
    print("TEST 1: send_command_to_sensors")
    print("Targeting: gateway_01 (success), gateway_03 (failure)")
    print("=" * 60)
    
    # We pass a dict mapping gateways to their targeted field devices
    target_devices = {
        "gateway_01": ["t1", "aq1"],
        "gateway_03": ["s1"] 
    }

    # Patching requests.post using the module path where it's imported
    with patch(f"{MODULE_PATH}.requests.post", side_effect=mock_requests_post):
        command_results = send_command_to_sensors("cmd_01", target_devices)
        
        for gw_id, res in command_results.items():
            print(f"\n  [{gw_id}]")
            info = res.get("gateway_info", {})
            print(f"    Status: {info.get('status')}")
            print(f"    Code:   {info.get('code')}")
            print(f"    Req TS: {info.get('req_timestamp')}")
            if info.get("status") == "success":
                print(f"    Records: {json_module.dumps(res.get('records'), indent=4)}")
            else:
                print(f"    Error:   {info.get('error')}")
        _assert_normalized_structure("TEST 1", command_results)


    # ── TEST 2: poll_gateways ───────────────────────────────────────────
    print("\n" + "=" * 60)
    print("TEST 2: poll_gateways")
    print("Targeting: All configured EDGE_DEVICES")
    print("=" * 60)

    # Patching requests.get using the module path where it's imported
    with patch(f"{MODULE_PATH}.requests.get", side_effect=mock_requests_get):
        poll_results = poll_gateways()
        
        for gw_id, res in poll_results.items():
            print(f"\n  [{gw_id}]")
            info = res.get("gateway_info", {})
            print(f"    Status: {info.get('status')}")
            print(f"    Code:   {info.get('code')}")
            print(f"    Req TS: {info.get('req_timestamp')}")
            if info.get("status") == "success":
                print(f"    Records: {json_module.dumps(res.get('records'), indent=4)}")
            else:
                print(f"    Error:   {info.get('error')}")
        _assert_normalized_structure("TEST 2", poll_results)

    print("\n" + "=" * 60)
    print("All tests completed.")
    print("=" * 60)

if __name__ == "__main__":
    # a way to use this module to poll gateways and ingest data into the cloud platform, simulating the cloud platform's client_http.py
    import os
    import time as time_module
    from cloud_platform.services.database_service import DatabaseService
    from cloud_platform.digital_twin.dt_factory import DTFactory
    from cloud_platform.virtualization.digital_replica.schema_registry import SchemaRegistry
    from config.config_loader import ConfigLoader
    from cloud_platform.services.data_ingestion import ingest_edge_results

    schema_registry = SchemaRegistry()
    schema_registry.load_schema("gateway", "cloud_platform/virtualization/templates/gateway.yaml")
    schema_registry.load_schema("sensor", "cloud_platform/virtualization/templates/sensor.yaml")
    schema_registry.load_schema("actuator", "cloud_platform/virtualization/templates/actuator.yaml")
    schema_registry.load_schema("digital_twin", "cloud_platform/virtualization/templates/digital_twin.yaml")

    db_config = ConfigLoader.load_database_config()
    connection_string = ConfigLoader.build_connection_string(db_config)

    db_service = DatabaseService(
        connection_string=connection_string,
        db_name=db_config["settings"]["name"],
        schema_registry=schema_registry,
    )
    db_service.connect()

    dt_factory = DTFactory(
        name="etna",
        db_service=db_service,
        schema_registry=schema_registry,
        dt_schema_path=os.path.join(
            os.getcwd(),
            "cloud_platform",
            "virtualization",
            "templates",
            "digital_twin.yaml",
        ),
    )

    poll_interval_s = getattr(cfg, "POLLING_INTERVAL_MS", 5000) / 1000.0

    print(f"Starting polling loop. Interval: {poll_interval_s}s")
    # Run it as a module from the project root: python -m cloud_platform.application.client_http
    while True:
        results = poll_gateways()
        ingest_edge_results(db_service, results, dt_factory, submitter=None, command=None)
        time_module.sleep(poll_interval_s)
