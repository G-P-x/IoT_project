from flask import Blueprint, cli, current_app, jsonify, request
from flask import render_template
from cloud_platform.application import client_http

# This file defines the operator API routes and their handlers.
# An operator can use these routes to view telemetry data, health events, and send commands to the DT.
# 1. History of anomalies
# 2. History of telemetry data for a specific parameter
# 3. Send command to DT
# 4. View health events - sensor failures, connectivity issues, etc.
# 5. View current state of the DT (latest telemetry, health status, etc.)
# 6. View sensor status and diagnostics

bp_operator = Blueprint("operator_api", __name__, url_prefix="/operator")

@bp_operator.route("/home", methods=["GET"])
def home():
    return render_template("home.html")

# Look up telemetry history for a specific parameter, with optional twin_id and limit parameters
@bp_operator.route("/history", methods=["GET"])
def history():
    """
    Accessed via GET request to /operator/history?parameter=temperature&twin_id=etna_01&limit=100
    """
    return render_template("history.html")



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
    from datetime import datetime, timedelta
    import random

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

@bp_operator.route("/commands", methods=["GET"])
def commands():
    return render_template("commands.html")

@bp_operator.route("/commands/send", methods=["POST"])
def send_command():
    """
    Expects JSON body with fields:
    {
        target: {
             "twin_id": "etna_01",
             "sensor_id": "temp_01"   # optional, if command is for a specific sensor
        },
        command_id: "cmd_01",
        issued_by: "operator_01"   
    }
    """
    data = request.get_json()
    target = data.get("target", {})
    twin_id = target.get("twin_id") or current_app.config["DEFAULT_TWIN_ID"]
    sensor_id = target.get("sensor_id")          # optional sensor filter
    command_id = data.get("command_id")
    operator_id = data.get("issued_by")

    # Fan out the command to all (or selected) edge devices in parallel.
    # Blocks only THIS request thread; other Flask threads keep serving normally.
    edge_results = client_http.send_command_to_all_devices(
        command_id,
        sensors=[sensor_id] if sensor_id else None,
    )

    # dt = current_app.extensions["dt_service"]
    # dt.send_command(twin_id, command_id, sensor_id=sensor_id)

    # Check if any device responded successfully
    any_success = any(r["status"] == "success" for r in edge_results.values())
    overall_status = "success" if any_success else "error"
    http_code = 200 if any_success else 502

    print(f"Received command: {command_id} for twin: {twin_id}, sensor: {sensor_id}. from operator: {operator_id}")
    return jsonify({
        "status": overall_status,
        "message": f"Command '{command_id}' sent to twin '{twin_id}', sensor '{sensor_id}', by operator '{operator_id}'.",
        "devices": edge_results,
    }), http_code

        


@bp_operator.route("/health", methods=["GET"])
def health():
    return render_template("health.html")
@bp_operator.route("/anomalies", methods=["GET"])
def anomalies():
    return render_template("anomalies.html")
def register_operator_routes(app):
    app.register_blueprint(bp_operator)