from multiprocessing import connection
from flask import Blueprint, current_app, jsonify, request
from flask import render_template
from cloud_platform.application import client_http
from pydantic import BaseModel, ValidationError

# ── Imports for Mock data for testing (delete in production) ──────────────────────────────────
from datetime import datetime, timedelta
import random

# This file defines the operator API routes and their handlers.
# An operator can use these routes to view telemetry data, health events, and send commands to the DT.
# 1. History of anomalies
# 2. History of telemetry data for a specific parameter
# 3. Send command to DT
# 4. View health events - sensor failures, connectivity issues, etc.
# 5. View current state of the DT (latest telemetry, health status, etc.)
# 6. View sensor status and diagnostics

# ── pydantic for enhanced data validation ──────────────────────────────────────────
class DeviceResult(BaseModel):
    # edge_results_structure = {
    #     device_id: {
    #         "status": "success" or "error",
    #         "code": 200 or error_code,     # present on success
    #         "body": { ... } or "text",      # present on success
    #         "error": "error message"         # present on error
    #     }
    # }
    status: str                    # "success" or "error"
    code: int | None = None        # HTTP status code (only on success)
    body: dict | str | None = None # Response body (only on success)
    error: str | None = None       # Error description (only on error)
    # The body should be this format:
    # {
    #     "time_stamp": "2024-06-01T12:00:00Z",
    #     "records": [
    #         {
    #             "status": "OK",
    #             "type": "sensor",
    #             "id": "84F3EB12A0BC-t1",
    #             "value": 24.8,
    #             "message": "Temperature acquired",
    #             "timestamp": "2026-02-16T15:40:12
    #         },
    #         {
    #             "status": "OK",
    #             "type": "sensor",
    #             "id": "84F3EB12A0BC-aq1",
    #             "value": 10.2,
    #             "timestamp": "2024-06-01T12:00:00
    #         },
    #         {
    #             "status": "ERROR",
    #             "type": "sensor",
    #             "id": "84F3EB12A0BC-x1",
    #             "value": null,
    #             "message": "Invalid sensor_id",
    #             "timestamp": "2026-02-16T15:40:12"
    #         }
    #     ]

# Pydantic v2 RootModel replaces v1's __root__
class EdgeResults(BaseModel):
    edge : dict[str, DeviceResult]  # device_id -> DeviceResult


bp_operator = Blueprint("operator_api", __name__, url_prefix="/operator")

# ── Load Templates Roots ──────────────────────────────────────────
@bp_operator.route("/home", methods=["GET"])
def home():
    return render_template("home.html")

@bp_operator.route("/history", methods=["GET"])
def history():
    return render_template("history.html")

@bp_operator.route("/commands", methods=["GET"])
def commands():
    return render_template("commands.html")

@bp_operator.route("/health", methods=["GET"])
def health():
    return render_template("health.html")

@bp_operator.route("/anomalies", methods=["GET"])
def anomalies():
    return render_template("anomalies.html")





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
def send_command():
    """
    Input:
        JSON body with fields:
        {
            - target: {
                "twin_id": "etna_01",
                "gateway_id": ["gw_01", "gw_02" ],  # optional, if not provided, assume all gateways for the twin
                "sensor_id": ["temp_01", "temp_02"]  # optional, if not provided, assume all sensors for the parameter
            },
            - command_id: "cmd_01",
            - issued_by: "operator_01",  
        }
    """
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "Invalid JSON in request body"}), 400

    target = data.get("target", {})
    if not target or "command_id" not in data or "issued_by" not in data:
        return jsonify({"status": "error", "message": "Missing required fields: target, command_id, issued_by"}), 400

    twin_id = target.get("twin_id") or current_app.config["DEFAULT_TWIN_ID"]
    command_id = data.get("command_id")
    gateway_ids = target.get("gateway_id")  # optional list of gateway IDs to target, if not provided, assume all gateways for the twin
    sensor_ids = target.get("sensor_id")    # optional list of sensor IDs to target, if not provided, assume all sensors for the parameter
    operator_id = data.get("issued_by")

    # Fan out the command to all (or selected) edge devices in parallel.
    # Blocks only THIS request thread; other Flask threads keep serving normally.
    edge_results = client_http.send_command_to_all_devices(
        command_id,
        sensors=sensor_ids,
        device_ids=gateway_ids,
        twin_id=twin_id,
    )

    # Validate response structure with Pydantic
    try:
        EdgeResults(edge=edge_results)
    except ValidationError as ve:
        return jsonify({"status": "error", "message": "Invalid response structure from devices", "details": ve.errors()}), 502
    # dt = current_app.extensions["dt_service"]
    # dt.send_command(twin_id, command_id, sensor_id=sensor_id)

    # Check for connection errors with the gateways (network issues, device offline, etc.)
    connection_status = {device_id: res["status"] for device_id, res in edge_results.items()} 
    if any(status == "error" for status in connection_status.values()):
        print(f"Connection errors with devices: {connection_status}")
        # Depending on requirements, you might want to return an error response here instead of proceeding.

    # Check sensor-level errors in the device responses (e.g. invalid sensor_id, command processing error, etc.)
    sensors_status = {}
    for device_id, res in edge_results.items():
        if res["status"] == "success" and isinstance(res["body"], dict) and "records" in res["body"]:
            for record in res["body"]["records"]:
                sensor_id = record.get("id", "unknown_sensor")
                sensors_status[f"{device_id}:{sensor_id}"] = record.get("status", "unknown_status")

    print(f"Received command: {command_id} for twin: {twin_id}, gateways: {gateway_ids}, sensors: {sensor_ids}. from operator: {operator_id}")
    
    # return jsonify({
    #     "status": overall_status,
    #     "message": f"Command '{command_id}' sent to twin '{twin_id}', gateways '{gateway_ids}', sensors '{sensor_ids}', by operator '{operator_id}'.",
    #     "devices": edge_results,
    #     "sensor_status": sensors_status,

        



def register_operator_routes(app):
    app.register_blueprint(bp_operator)

if __name__ == "__main__":
    # runs test for this module
    print("Testing operator_api module...")