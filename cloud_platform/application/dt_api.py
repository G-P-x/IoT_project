"""
Digital Twin API Module
========================
Flask Blueprint that exposes REST endpoints for managing Digital Twins,
Digital Replicas, and Services.

Architecture reasoning (from the lecture):
- The lecture separates generic DT/DR management APIs (api.py) from domain-specific
  APIs (winery_apis.py). We follow the same pattern: this file contains the
  generic CRUD and management routes, while the operator_api.py in the existing
  project handles domain-specific operator actions.

Blueprints defined here:
    dt_api             — /api/dt            — Create / list / get Digital Twins
    dr_api             — /api/dr            — Generic DR CRUD (gateway, sensor)
    dt_management_api  — /api/dt-management — Assign DRs to DTs, run services

All routes use `current_app.config` to access the shared DT_FACTORY, DB_SERVICE,
and SCHEMA_REGISTRY instances — this follows Flask's recommended pattern for
dependency injection without global imports.
"""

from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from cloud_platform.virtualization.digital_replica.dr_factory import DRFactory

# ── Blueprint definitions ─────────────────────────────────────────────
# Three separate blueprints keep the URL namespace clean and make it easy
# to enable/disable groups of endpoints independently.

dt_api = Blueprint("dt_api", __name__, url_prefix="/api/dt")
dr_api = Blueprint("dr_api", __name__, url_prefix="/api/dr")
dt_management_api = Blueprint("dt_management_api", __name__, url_prefix="/api/dt-management")


# ==========================================================================
# Digital Twin endpoints  (/api/dt)
# ==========================================================================

@dt_api.route("/", methods=["POST"])
def create_digital_twin():
    """
    Create a new Digital Twin.

    Expected JSON body:
        { "name": "Etna Monitoring Station Alpha", "description": "..." }

    The DT starts with no DRs and no services — they are added via the
    management endpoints below.
    """
    try:
        data = request.get_json()
        required_fields = ["name", "description"]
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Missing required fields: name, description"}), 400

        dt_id = current_app.config["DT_FACTORY"].create_dt(
            name=data["name"],
            description=data["description"],
        )
        return jsonify({"dt_id": dt_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dt_api.route("/<dt_id>", methods=["GET"])
def get_digital_twin(dt_id):
    """Retrieve a single DT manifest by _id."""
    try:
        dt = current_app.config["DT_FACTORY"].get_dt(dt_id)
        if not dt:
            return jsonify({"error": "Digital Twin not found"}), 404
        return jsonify(dt), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dt_api.route("/", methods=["GET"])
def list_digital_twins():
    """List all Digital Twins."""
    try:
        dts = current_app.config["DT_FACTORY"].list_dts()
        return jsonify(dts), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dt_api.route("/<dt_id>/services", methods=["POST"])
def add_service_to_dt(dt_id):
    """
    Attach a service to a Digital Twin.

    Expected JSON body:
        { "name": "AggregationService", "config": {} }

    The service class is resolved dynamically via the DT Factory's module mapping.
    """
    try:
        data = request.get_json()
        if not data or "name" not in data:
            return jsonify({"error": "Missing service name"}), 400

        current_app.config["DT_FACTORY"].add_service(
            dt_id=dt_id,
            service_name=data["name"],
            service_config=data.get("config", {}),
        )
        return jsonify({"status": "success", "message": f"Service '{data['name']}' added"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@dt_api.route("/<dt_id>/services/<service_name>", methods=["DELETE"])
def remove_service_from_dt(dt_id, service_name):
    """
    Detach a service from a Digital Twin.

    This endpoint allows the removal of a service from the DT's manifest.
    """
    try:
        current_app.config["DT_FACTORY"].remove_service(dt_id, service_name)
        return jsonify({"status": "success", "message": f"Service '{service_name}' removed"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==========================================================================
# Digital Replica endpoints  (/api/dr)
# ==========================================================================

@dr_api.route("/<dr_type>", methods=["POST"])
def create_digital_replica(dr_type):
    """
    Create a new Digital Replica of a given type (gateway or sensor).

    The route dynamically resolves the correct YAML template based on dr_type.

    Expected JSON body: the initial profile/data/metadata for the DR (see the
    corresponding YAML template for the expected structure).
    """
    try:
        data = request.get_json()
        # Resolve the YAML template path for this DR type
        template_path = f"cloud_platform/virtualization/templates/{dr_type}.yaml"
        dr_factory = DRFactory(template_path)
        dr = dr_factory.create_dr(dr_type, data)
        dr_id = current_app.config["DB_SERVICE"].save_dr(dr_type, dr)
        return jsonify({
            "status": "success",
            "message": f"{dr_type.capitalize()} DR created successfully",
            f"{dr_type}_id": dr_id,
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dr_api.route("/<dr_type>/<dr_id>", methods=["GET"])
def get_digital_replica(dr_type, dr_id):
    """Retrieve a single DR by type and _id."""
    try:
        dr = current_app.config["DB_SERVICE"].get_dr(dr_type, dr_id)
        if not dr:
            return jsonify({"error": "Digital Replica not found"}), 404
        return jsonify(dr), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dr_api.route("/<dr_type>", methods=["GET"])
def list_digital_replicas(dr_type):
    """List all DRs of a given type, with optional query-string filters."""
    try:
        filters = {}
        # Support common filters via query string
        if request.args.get("status"):
            filters["metadata.status"] = request.args.get("status")
        drs = current_app.config["DB_SERVICE"].query_drs(dr_type, filters)
        return jsonify({f"{dr_type}s": drs}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dr_api.route("/<dr_type>/<dr_id>", methods=["PUT"])
def update_digital_replica(dr_type, dr_id):
    """
    Partially update a DR document.

    Expected JSON body: a dict with optional 'profile', 'data', 'metadata' keys.
    """
    try:
        data = request.get_json()
        update_data = {}
        if "profile" in data:
            update_data["profile"] = data["profile"]
        if "data" in data:
            update_data["data"] = data["data"]
        update_data["metadata"] = {"updated_at": datetime.utcnow()}

        current_app.config["DB_SERVICE"].update_dr(dr_type, dr_id, update_data)
        return jsonify({"status": "success", "message": f"{dr_type.capitalize()} updated"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dr_api.route("/<dr_type>/<dr_id>", methods=["DELETE"])
def delete_digital_replica(dr_type, dr_id):
    """Delete a DR by type and _id."""
    try:
        dr = current_app.config["DB_SERVICE"].get_dr(dr_type, dr_id)
        if not dr:
            return jsonify({"error": "Digital Replica not found"}), 404
        current_app.config["DB_SERVICE"].delete_dr(dr_type, dr_id)
        return jsonify({"status": "success", "message": f"{dr_type.capitalize()} deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dr_api.route("/<dr_type>/<dr_id>/measurements", methods=["POST"])
def add_measurement(dr_type, dr_id):
    """
    Append a new measurement to a DR's measurement list.

    Expected JSON body:
        { "measure_type": "temperature", "value": 24.8 }

    A timestamp is automatically added. This endpoint mirrors the lecture's
    add_room_measurements pattern — it reads the current measurement list,
    appends the new reading, and writes the whole list back.
    """
    try:
        data = request.get_json()
        if not data.get("measure_type") or "value" not in data:
            return jsonify({"error": "Missing required fields: measure_type, value"}), 400

        # Fetch current DR to read existing measurements
        dr = current_app.config["DB_SERVICE"].get_dr(dr_type, dr_id)
        if not dr:
            return jsonify({"error": "Digital Replica not found"}), 404

        # Build the measurement record
        measurement = {
            "measure_type": data["measure_type"],
            "value": data["value"],
            "timestamp": datetime.utcnow(),
        }

        # Ensure data.measurements exists
        existing_measurements = dr.get("data", {}).get("measurements", [])

        update_data = {
            "data": {
                "measurements": existing_measurements + [measurement],
            },
            "metadata": {
                "updated_at": datetime.utcnow(),
            },
        }

        current_app.config["DB_SERVICE"].update_dr(dr_type, dr_id, update_data)
        return jsonify({"status": "success", "message": "Measurement added"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==========================================================================
# DT Management endpoints  (/api/dt-management)
# ==========================================================================

@dt_management_api.route("/assign/<dt_id>", methods=["POST"])
def assign_dr_to_dt(dt_id):
    """
    Assign a Digital Replica to an existing Digital Twin.

    Expected JSON body:
        { "dr_type": "sensor", "dr_id": "abc-123-..." }
    """
    try:
        data = request.get_json()
        required_fields = ["dr_type", "dr_id"]
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Missing required fields: dr_type, dr_id"}), 400

        current_app.config["DT_FACTORY"].add_digital_replica(
            dt_id, data["dr_type"], data["dr_id"]
        )
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dt_management_api.route("/stats/<dt_id>", methods=["GET"])
def get_dt_stats(dt_id):
    """
    Execute the AggregationService on a Digital Twin and return statistics.

    Optional query parameters:
        - dr_type:      Filter DRs by type (e.g. 'sensor').
        - measure_type: Filter measurements by type (e.g. 'temperature').

    This endpoint mirrors the lecture's /api/dt-management/stats/<dt_id> route.
    """
    try:
        dt = current_app.config["DT_FACTORY"].get_dt(dt_id)
        if not dt:
            return jsonify({"error": "Digital Twin not found"}), 404

        params = request.args.to_dict()
        dr_type = params.get("dr_type")
        measure_type = params.get("measure_type")

        # Reconstitute a live DT instance and execute the aggregation service
        stats = current_app.config["DT_FACTORY"].get_dt_instance(dt_id).execute_service(
            "AggregationService",
            dr_type=dr_type,
            attribute=measure_type,
        )
        return jsonify(stats), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==========================================================================
# Blueprint registration helper
# ==========================================================================

def register_dt_api_blueprints(app):
    """
    Register all DT-related API blueprints with the Flask app.

    Called once at startup from the FlaskServer class.
    """
    app.register_blueprint(dt_api)
    app.register_blueprint(dr_api)
    app.register_blueprint(dt_management_api)
