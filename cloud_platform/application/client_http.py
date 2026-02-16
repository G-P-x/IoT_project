import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from config.config import Config

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


def _build_url(base_url):
    """Build the notify endpoint URL for a given device base URL."""
    return base_url.rstrip("/") + "/notify"


def send_http_command(device_url, command, sensors=None):
    """
    Send an HTTP POST to a single edge device.

    Args:
        device_url: Base URL of the edge device (e.g. "http://192.168.1.10:5000").
        command:    The command string (e.g. "cmd_01").
        sensors:    Optional list of sensor ids.
    
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
        A requests.Response on success, or None on failure.
    """
    url = _build_url(device_url)
    # sending payload structure
    # {
    #  "command": "cmd_01",
    #  "sensors": ["t1", "aq1"]
    # } 
    payload = {"command": command, "sensors": sensors} if sensors is not None else {"command": command, "sensors": []}
    # if sensors is [], the device interprets it as "apply to all sensors linked to the gateway"
    try:
        response = requests.post(url, json=payload, timeout=10)
        logger.info("HTTP notify → %s  response: %s – %s", url, response.status_code, response.text)
        return response
    except requests.RequestException as e:
        logger.error("HTTP notify → %s  failed: %s", url, e)
        return None


def send_command_to_all_devices(command, sensors=None, device_ids=None, twin_id=None):
    """
    Fan-out a command to multiple edge devices in parallel.

    Uses a ThreadPoolExecutor so that every device request runs concurrently.
    The calling Flask thread blocks until ALL workers finish, but other Flask
    request threads keep running normally.

    Args:
        command:    The command string (e.g. "cmd_01").
        sensors:    Optional list of sensor ids.
        device_ids: Optional list of device IDs to target.
                    If None, the command is sent to ALL configured devices.
    Returns:
        A dict mapping device_id → result dict, where each result contains:
            - "status":  "success" | "error"
            - "code":    HTTP status code (if success)
            - "body":    Response body (if success)
            - "error":   Error description (if error)
    """
    devices = cfg.EDGE_DEVICES  # {device_id: base_url, …}

    # Filter to specific devices if requested
    if device_ids is not None:
        devices = {did: url for did, url in devices.items() if did in device_ids}

    results = {} # store results per device_id (per gateway)

    with ThreadPoolExecutor(max_workers=len(devices) or 1) as executor:
        # Submit one task per device
        future_to_device = {
            executor.submit(send_http_command, url, command, sensors): device_id
            for device_id, url in devices.items()
        }

        # Collect results as they complete
        for future in as_completed(future_to_device):
            device_id = future_to_device[future]
            try:
                response = future.result()
                # Expected response format:
                # {
                #     "time_stamp": "2024-06-01T12:00:00Z",
                #     "records": [
                #         {
                #             "status": "OK",
                #             "type": "sensor",
                #             "id": "84F3EB12A0BC-t1",
                #             "value": 24.8,
                #             "message": "Temperature acquired",
                #             "timestamp": "2026-02-16T15:40:12Z"
                #         },
                #         {
                #             "status": "OK",
                #             "type": "sensor",
                #             "id": "84F3EB12A0BC-aq1",
                #             "value": 10.2,
                #             "timestamp": "2024-06-01T12:00:00Z",
                #             "operator_id": None,
                #             "command_id": None
                #         },
                #         {
                #             "status": "ERROR",
                #             "type": "sensor",
                #             "id": "84F3EB12A0BC-x1",
                #             "value": null,
                #             "message": "Invalid sensor_id",
                #             "timestamp": "2026-02-16T15:40:12Z"
                #         }
                #     ]
                # }
                if response is not None:
                    content_type = response.headers.get("content-type", "")
                    results[device_id] = {
                        "status": "success",
                        "code": response.status_code,
                        "body": response.json() if "application/json" in content_type else response.text,
                    }
                else:
                    results[device_id] = {
                        "status": "error",
                        "error": "No response from device.",
                    }
            except Exception as e:
                results[device_id] = {
                    "status": "error",
                    "error": str(e),
                }
    return results

if __name__ == "__main__":
    ## IMPORTANT: this test code is meant to be run as a standalone script to test the client_http module in isolation.
    # Since it doesn't know about the project root, you should run it as a module from the project root like this:
    # -> on the terminal run ->    python -m cloud_platform.application.client_http

    import json
    import os
    from unittest.mock import patch, MagicMock

    # ── Load mock data ────────────────────────────────────────────────
    mock_file = os.path.join(os.path.dirname(__file__), "mock_edge_responses.json")
    with open(mock_file, "r") as f:
        mock_data = json.load(f)    # {device_id: response_body | null, …}

    def mock_post(url, json=None, timeout=None):
        """
        Replace requests.post: look up the device from the URL and return
        the corresponding mock response, or simulate a connection failure
        if the mock value is null.
        """
        # Map URL back to device_id using configured devices
        device_id = None
        for did, base_url in cfg.EDGE_DEVICES.items():
            if url.startswith(base_url):
                device_id = did
                break

        body = mock_data.get(device_id) if device_id else None

        if body is None:
            # Simulate unreachable device
            raise requests.ConnectionError(f"Mock: device {device_id or url} unreachable")

        # Build a fake Response object
        resp = MagicMock()
        resp.status_code = 200
        resp.text = json_module.dumps(body)
        resp.json.return_value = body
        resp.headers = {"content-type": "application/json"}
        return resp

    # Need json module under a different name to avoid shadowing the parameter
    import json as json_module

    # ── Test 1: send_http_command to a single device ──────────────────
    print("=" * 60)
    print("TEST 1: send_http_command (single device)")
    print("=" * 60)
    with patch("cloud_platform.application.client_http.requests.post", side_effect=mock_post):
        device_url = cfg.EDGE_DEVICES["device_01"]
        result = send_http_command(device_url, "cmd_01", sensors=["t1", "aq1"])
        print(f"  Status code: {result.status_code}")
        print(f"  Body: {json_module.dumps(result.json(), indent=4)}")

    # ── Test 2: send_http_command to an unreachable device ────────────
    print("\n" + "=" * 60)
    print("TEST 2: send_http_command (unreachable device – device_04)")
    print("=" * 60)
    with patch("cloud_platform.application.client_http.requests.post", side_effect=mock_post):
        device_url = cfg.EDGE_DEVICES["device_04"]
        result = send_http_command(device_url, "cmd_01")
        print(f"  Result: {result}")  # Should be None

    # ── Test 3: send_command_to_all_devices (all devices) ─────────────
    print("\n" + "=" * 60)
    print("TEST 3: send_command_to_all_devices (all devices)")
    print("=" * 60)
    with patch("cloud_platform.application.client_http.requests.post", side_effect=mock_post):
        results = send_command_to_all_devices("cmd_01", sensors=["t1"])
        for device_id, res in results.items():
            print(f"\n  [{device_id}]")
            print(f"    status: {res['status']}")
            if res["status"] == "success":
                print(f"    code:   {res['code']}")
                print(f"    body:   {json_module.dumps(res['body'], indent=6)}")
            else:
                print(f"    error:  {res['error']}")

    # ── Test 4: send_command_to_all_devices (subset of devices) ───────
    print("\n" + "=" * 60)
    print("TEST 4: send_command_to_all_devices (only device_01, device_03)")
    print("=" * 60)
    with patch("cloud_platform.application.client_http.requests.post", side_effect=mock_post):
        results = send_command_to_all_devices("cmd_01", device_ids=["device_01", "device_03"])
        for device_id, res in results.items():
            print(f"\n  [{device_id}]")
            print(f"    status: {res['status']}")
            if res["status"] == "success":
                print(f"    code:   {res['code']}")
                print(f"    body:   {json_module.dumps(res['body'], indent=6)}")
            else:
                print(f"    error:  {res['error']}")

    # ── Test 5: Pydantic validation of results ────────────────────────
    print("\n" + "=" * 60)
    print("TEST 5: Pydantic validation (EdgeResults)")
    print("=" * 60)
    from cloud_platform.application.operator_api import EdgeResults
    from pydantic import ValidationError

    with patch("cloud_platform.application.client_http.requests.post", side_effect=mock_post):
        results = send_command_to_all_devices("cmd_01")
        try:
            validated = EdgeResults(edge=results)
            print("  ✓ Validation passed")
            for did, dr in validated.edge.items():
                print(f"    {did}: status={dr.status}, code={dr.code}, error={dr.error}")
        except ValidationError as ve:
            print(f"  ✗ Validation failed: {ve}")

    print("\n" + "=" * 60)
    print("All tests completed.")
    print("=" * 60)