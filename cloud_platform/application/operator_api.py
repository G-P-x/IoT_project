from flask import Blueprint, current_app, jsonify, request
from flask import render_template
from cloud_platform.types.edge import EdgeResults, DeviceResult
from cloud_platform.application import client_http
from pydantic import BaseModel, ValidationError
from typing import Literal

## ThreadPoolExecutor for background ingestion tasks
from cloud_platform.types.queues import IngestionQueueItem, DispatchQueueItem, HistoryQueueItem
import queue

# ── Imports for Mock data for testing (delete in production) ──────────────────────────────────
from datetime import datetime, timedelta
import random
import logging

# This file defines the operator API routes and their handlers.
# An operator can use these routes to view telemetry data, health events, and send commands to the DT.
# 1. History of anomalies
# 2. History of telemetry data for a specific parameter
# 3. Send command to DT
# 4. View health events - sensor failures, connectivity issues, etc.
# 5. View current state of the DT (latest telemetry, health status, etc.)
# 6. View sensor status and diagnostics

logger = logging.getLogger(__name__)

# ────────────────── Command Dispatcher ──────────────────
class CommandDispatcher:
    """
    This class encapsulates the logic for sending commands to edge devices and processing their responses.
    It can be extended in the future to support different types of commands, more complex routing logic, etc.
    """
    def __init__(self):
        self.client = client_http
        self.commands_map = {
            "cmd_01": self._send_command_to_sensors,
            "cmd_02": self._send_command_to_actuators
        }

    def send_command(self, command: str, target: dict[str, list[str]]) -> dict:
        """
        Send the specified command to the target devices and return their responses.

            Args:

        - command: str 

            "cmd_01"

        - target: dict mapping gateway IDs to lists of sensor IDs.

            {
                "gateway_id (e.g. gw_01)": ["temp_01", "temp_02"],  
                "gw_02": ["aq_01", "aq_02"],
                "gw_03": ["s_01", "s_02"],
            }
            
            Returns: a dict mapping gateway IDs to their response


            {
                "gateway_01": {
                    "status": "success",
                    "code": 200,
                    "records": {
                        "temp_01": {"status": "OK", "value": 25.3, ...},
                        "temp_02": {"status": "ERROR", "message": "Sensor malfunction", ...},
                    }
                },
                ...
            }
        }
        """
        # Discriminate command type and call the appropriate handler
        f = self.commands_map.get(command)
        response = f(command, target) if f else None
        if isinstance(response, str):
            return {"status": "error", "message": response}
        assert isinstance(response, dict), "Expected response to be a dict"
        return response
    
    
    def _send_command_to_sensors(self, command: str, targets: dict[str, list[str]]) -> dict[str, DeviceResult] | str:
        """ 
        Input:
        - command: str 

            "cmd_01"

        - target: dict mapping gateway IDs to lists of sensor IDs.

            {
                "gateway_id (e.g. gw_01)": ["temp_01", "temp_02"],  
                "gw_02": ["aq_01", "aq_02"],
                "gw_03": ["s_01", "s_02"],
            }

        Output:
        - unknown now
        """
        record_type = 'sensor_reading_event'

        edge_results = self.client.send_command_to_sensors(
            command = command,
            target = targets,
        )
        try:
            EdgeResults(edge=edge_results) # validate the structure of the response using the EdgeResults pydantic model. If the structure is invalid, a ValidationError will be raised, which we catch and return as an error message.
            return edge_results
        except ValidationError as ve:
            print(f"Pydantic validation error: {ve}")
            return f"Pydantic validation error: {ve}"

        

    def _send_command_to_actuators(self, command: str, actuators: dict[str, list[str]]):
        """
        Similar to _send_command_to_sensors but for actuators. The structure of the input and output is the same, but the records will have different fields based on the type of actuator and the command sent.
        """
        pass

dispatcher = CommandDispatcher()
# ────────────────── Flask Routes ───────────────────────────────────────────
bp_operator = Blueprint("operator_api", __name__, url_prefix="/operator")

# ── Load Templates Roots ──────────────────────────────────────────

@bp_operator.route("", methods=["GET"])
def home():
    return jsonify({"message": "Welcome to the Operator API. Use /operator/history/<parameter> to view telemetry history and /operator/commands/send to send commands to the DT."})

@bp_operator.route("/change_poll_interval", methods=["PUT"])
def commands():
    # Retrieve the JSON data from the request body
    data = request.get_json()
    try:
        new_interval = int(data.get("poll_interval"))
        logger.info(f"new poll interval arrived: {new_interval}")
        result = current_app.config["GATEWAY_POLLER"].update_interval(new_interval)
    except ValueError as e:
        logger.error(e)
        return jsonify({
            "status":"error",
            "message":"invalid"
        }), 400

    # Return a success response
    return jsonify({
        "status": "success",
        "message": result,
    }), 200


@bp_operator.route("/history", methods=["POST"])
def query_history():
    try:
        data:dict = request.get_json()
        q : queue.Queue = current_app.config.get("HISTORY_QUEUE")
        operator:str = data.get("operator_id")
        query:dict = data.get("query")
        logger.info(f"received queryin in Operator Route: {query}")
        q.put(HistoryQueueItem(stop_signal=False, operator_id=operator, query=query))
        logger.info(f"task in queue: {q}")
        return jsonify({
            "status":"on going",
            "message":"your request is being processed..."
        }), 200
    except KeyError as e:
        logger.error(e)
        return jsonify({
            "status":"error",
            "message":"malformed request"
        }), 400
    except Exception as e:
        logger.error(e)
        return jsonify({
            "status":"error",
            "message":"invalid"
        }), 400

@bp_operator.route("/history/<parameter>", methods=["GET"])
def get_history(parameter: str):
    """
    Accessed via GET request to /operator/history/temperature?twin_id=etna_01&limit=100
    The request is sent from the frontend through the javascript code in history.html,
    which extracts the parameter, twin_id, and limit from the user input and sends the 
    request to this endpoint. 
    The handler then retrieves the data from the DTService and returns it as JSON.
    """

    twin_id = request.args.get("twin_id") or current_app.config["DEFAULT_TWIN_ID"]
    sensor_id = request.args.get("sensor_id")          # optional sensor filter
    date_from = request.args.get("from")                # ISO datetime string
    date_to = request.args.get("to")                    # ISO datetime string
    # dt = current_app.extensions["dt_service"]
    # return jsonify(dt.get_history(twin_id, parameter, sensor_id=sensor_id, date_from=date_from, date_to=date_to))

    # ── Mock data for testing ──────────────────────────────────────────

    sensors_map = {
        "temperature":   ["temp_01", "temp_02"],
        "air_quality":   ["aq_01",   "aq_02"],
        "seismic_waves": ["s_01",    "s_02"],
    }
    units_map = {
        "temperature": "°C",
        "air_quality": "AQI",
        "seismic_waves": "mm/s",
    }
    sensors = [sensor_id] if sensor_id else sensors_map.get(parameter, ["sensor"])
    unit = units_map.get(parameter, "")

    # Parse date range
    dt_from = datetime.fromisoformat(date_from) if date_from else datetime.utcnow() - timedelta(days=7)
    dt_to = datetime.fromisoformat(date_to) if date_to else datetime.utcnow()
    total_seconds = (dt_to - dt_from).total_seconds()

    # ~24 samples per day, at least 2
    num_points = max(2, int((total_seconds / 86400) * 24))

    # Evenly spaced timestamps across the range
    step = total_seconds / (num_points - 1) if num_points > 1 else 0

    mock_data = [
        {
            "ts": (dt_from + timedelta(seconds=i * step)).isoformat(),
            "value": round(random.uniform(18.0, 35.0), 2),
            "unit": unit,
            "sensor_id": s,
        }
        for s in sensors
        for i in range(num_points)
    ]
    return jsonify(mock_data)


@bp_operator.route("/commands/send", methods=["POST"])
def send():
    '''
    Expected JSON body: 
        {"command_id": "string", 
        "issued_by": "string", 
        "target": 
        {"gateway_id": ["sensor_id", ...], ...}}
    '''
    data = request.get_json() # get the JSON body of the request
    if not data:
        return jsonify({"status": "error", "message": "Missing JSON body"}), 400
    command_id = str(data.get("command_id")).lower()
    operator_id = str(data.get("issued_by")).lower()
    target = dict(data.get("target"))

    # Dispatch the command to the appropriate edge devices
    edge_results = dispatcher.send_command(command=command_id, target=target)

    if edge_results:
        ingestion_queue = current_app.config.get("INGESTION_QUEUE")
        ingestion_queue.put(IngestionQueueItem(priority=1, item={"edge_results": edge_results, "command_id": command_id, "operator_id": operator_id, "target": target}))
        return jsonify(edge_results), 200
    else:
        return jsonify({"status": "error", "message": "Failed to send command to edge devices"}), 502        
    

def register_operator_routes(app):
    app.register_blueprint(bp_operator)

if __name__ == "__main__":
    ## IMPORTANT: run from project root as:  python -m cloud_platform.application.operator_api
    import json
    import os
    from flask import Flask
    from unittest.mock import patch, MagicMock

    # ── Helper: build mock edge_results from the JSON file ────────────
    mock_file = os.path.join(os.path.dirname(__file__), "mock_edge_responses.json")
    with open(mock_file, "r") as f:
        mock_raw = json.load(f)

    def build_mock_edge_results(device_filter=None):
        """
        Convert the raw mock JSON into the dict format that
        send_command_to_all_devices() would return.
        """
        results = {}
        for did, body in mock_raw.items():
            if device_filter and did not in device_filter:
                continue
            if body is None:
                results[did] = {"status": "error", "error": "No response from device."}
            else:
                results[did] = {"status": "success", "code": 200, "body": body}
        return results

    # ── Create a minimal Flask test app ───────────────────────────────
    app = Flask(__name__)
    app.config["DEFAULT_TWIN_ID"] = "etna_01"
    register_operator_routes(app)
    client = app.test_client()

    # ── TEST 1: Missing JSON body → 400 ──────────────────────────────
    print("=" * 60)
    print("TEST 1: POST /commands/send with no JSON body → 400")
    print("=" * 60)
    resp = client.post("/operator/commands/send", content_type="application/json", data="")
    print(f"  Status: {resp.status_code}")
    print(f"  Body:   {resp.get_json()}")
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    print("  PASSED")

    # ── TEST 2: Missing required fields → 400 ────────────────────────
    print("\n" + "=" * 60)
    print("TEST 2: POST /commands/send missing command_id → 400")
    print("=" * 60)
    resp = client.post("/operator/commands/send", json={"target": {"twin_id": "etna_01"}, "issued_by": "op_01"})
    print(f"  Status: {resp.status_code}")
    print(f"  Body:   {resp.get_json()}")
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    print("  PASSED")

    # ── TEST 3: Valid command to all devices (mix of success/error) ───
    print("\n" + "=" * 60)
    print("TEST 3: Valid command → all devices (3 success, 1 error)")
    print("=" * 60)
    mock_results = build_mock_edge_results()
    with patch("cloud_platform.application.client_http.send_command_to_all_devices", return_value=mock_results):
        resp = client.post("/operator/commands/send", json={
            "target": {"twin_id": "etna_01"},
            "command_id": "cmd_01",
            "issued_by": "operator_01"
        })
    data = resp.get_json()
    print(f"  Status: {resp.status_code}")
    print(f"  Overall status: {data['status']}")
    print(f"  Connection status: {json.dumps(data['connection_status'], indent=4)}")
    print(f"  Sensor status: {json.dumps(data['sensor_status'], indent=4)}")
    print(f"  Devices responded: {list(data['devices'].keys())}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert data["status"] == "success"
    assert data["connection_status"]["device_04"] == "error"
    print("  PASSED")

    # ── TEST 4: Valid command to subset of devices ────────────────────
    print("\n" + "=" * 60)
    print("TEST 4: Valid command → only device_01, device_03")
    print("=" * 60)
    mock_results = build_mock_edge_results(device_filter=["device_01", "device_03"])
    with patch("cloud_platform.application.client_http.send_command_to_all_devices", return_value=mock_results):
        resp = client.post("/operator/commands/send", json={
            "target": {"twin_id": "etna_01", "gateway_id": ["device_01", "device_03"]},
            "command_id": "cmd_01",
            "issued_by": "operator_01"
        })
    data = resp.get_json()
    print(f"  Status: {resp.status_code}")
    print(f"  Devices: {list(data['devices'].keys())}")
    assert resp.status_code == 200
    assert set(data["devices"].keys()) == {"device_01", "device_03"}
    print("  PASSED")

    # ── TEST 5: All devices fail → 502 ───────────────────────────────
    print("\n" + "=" * 60)
    print("TEST 5: All devices unreachable → 502")
    print("=" * 60)
    all_error = {
        "device_01": {"status": "error", "error": "Connection refused"},
        "device_02": {"status": "error", "error": "Timeout"},
    }
    with patch("cloud_platform.application.client_http.send_command_to_all_devices", return_value=all_error):
        resp = client.post("/operator/commands/send", json={
            "target": {"twin_id": "etna_01"},
            "command_id": "cmd_01",
            "issued_by": "operator_01"
        })
    data = resp.get_json()
    print(f"  Status: {resp.status_code}")
    print(f"  Overall status: {data['status']}")
    assert resp.status_code == 502
    assert data["status"] == "error"
    print("  PASSED")

    # ── TEST 6: Pydantic validation catches bad structure → 502 ──────
    print("\n" + "=" * 60)
    print("TEST 6: Invalid device response structure → Pydantic 502")
    print("=" * 60)
    bad_results = {
        "device_01": {"wrong_field": "oops"}  # missing "status"
    }
    with patch("cloud_platform.application.client_http.send_command_to_all_devices", return_value=bad_results):
        resp = client.post("/operator/commands/send", json={
            "target": {"twin_id": "etna_01"},
            "command_id": "cmd_01",
            "issued_by": "operator_01"
        })
    data = resp.get_json()
    print(f"  Status: {resp.status_code}")
    print(f"  Message: {data['message']}")
    assert resp.status_code == 502
    assert "Invalid response structure" in data["message"]
    print("  PASSED")

    # ── TEST 7: Sensor-level error detection ─────────────────────────
    print("\n" + "=" * 60)
    print("TEST 7: Sensor-level errors detected in response")
    print("=" * 60)
    mock_results = build_mock_edge_results(device_filter=["device_02"])
    with patch("cloud_platform.application.client_http.send_command_to_all_devices", return_value=mock_results):
        resp = client.post("/operator/commands/send", json={
            "target": {"twin_id": "etna_01", "gateway_id": ["device_02"]},
            "command_id": "cmd_01",
            "issued_by": "operator_01"
        })
    data = resp.get_json()
    print(f"  Status: {resp.status_code}")
    print(f"  Sensor status: {json.dumps(data['sensor_status'], indent=4)}")
    # device_02 has one OK sensor and one ERROR sensor
    assert data["sensor_status"]["device_02:A1B2C3D4E5F6-t1"] == "OK"
    assert data["sensor_status"]["device_02:A1B2C3D4E5F6-x1"] == "ERROR"
    print("  PASSED")

    # ── TEST 8: GET /history/<parameter> returns mock data ───────────
    print("\n" + "=" * 60)
    print("TEST 8: GET /history/temperature returns mock telemetry")
    print("=" * 60)
    resp = client.get("/operator/history/temperature?from=2026-02-10T00:00:00&to=2026-02-16T00:00:00")
    data = resp.get_json()
    print(f"  Status: {resp.status_code}")
    print(f"  Points returned: {len(data)}")
    print(f"  First point: {data[0]}")
    assert resp.status_code == 200
    assert len(data) > 0
    assert "value" in data[0] and "sensor_id" in data[0]
    print("  PASSED")

    print("\n" + "=" * 60)
    print("All tests completed successfully.")
    print("=" * 60)