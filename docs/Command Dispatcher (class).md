``` python
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
        The target is a dict mapping gateway IDs to lists of sensor IDs. For example:
            {
                "gateway_01": ["temp_01", "temp_02"],
                "gateway_02": ["aq_01", "aq_02"],
                "gateway_03": ["s_01", "s_02"],
            }

            The output is a dict mapping gateway IDs to their response, which includes the connection status and the status of each sensor. For example:

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
        
        f = self.commands_map.get(command)
        response = f(command, target) if f else None
        if response is None:
            # Handle unknown command case, e.g. log an error, return a specific response, etc.
            return {"error": "something went wrong, unknown command or no handler implemented"}
        # For this mock implementation, we just call the client_http function that simulates sending the command and getting responses.
        return self.client.send_command_to_sensors(command, target)
        
    def _send_command_to_sensors(self, command: str, targets: dict[str, list[str]]) -> dict[str, DeviceResult]:

        """
        Input:
            JSON body with fields:
            {
                - target: {
                    "gateway_id (e.g. gw_01)": ["temp_01", "temp_02"],  
                    "gw_02": ["aq_01", "aq_02"],
                    "gw_03": ["s_01", "s_02"],
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

        command_id = str(data.get("command_id")).lower()
        operator_id = str(data.get("issued_by")).lower()

        edge_results = self.client.send_command_to_sensors(
            command = command_id,
            target = targets,
        )

        # Validate response structure with Pydantic

        try:

            EdgeResults(edge=edge_results)

        except ValidationError as ve:

            return jsonify({"status": "error", "message": "Invalid response structure from devices", "details": ve.errors()}), 502

        # data is valid at this point, we can safely access edge_results[gateway_id]["status"], etc.

  

        # ── Analyze results for connectivity and sensor status ──────────────

        # ── Persist results into collection ──────────────

  

        # Now I have to persist the results into the database.

        # I have two collections:

        # 1. history_collection: one document per event, with fields like:

        # 2. devices_collection: one document per device, with current state and metadata

  

        ingestion_summary = {}

        db_service = current_app.config.get("DB_SERVICE")

        if db_service and db_service.is_connected():

            ingestion_summary = ingest_edge_results(db_service, edge_results)

        else:

            ingestion_summary = {"warning": "DB_SERVICE not available — data not persisted"}

  

        # Determine overall status

        any_success = any(r["status"] == "success" for r in edge_results.values())

        overall_status = "success" if any_success else "error"

        http_code = 200 if any_success else 502

        return jsonify({

            "status": overall_status,

            "connection_status": {gw: r["status"] for gw, r in edge_results.items()},

            "sensor_status": {f"{gw}:{dev}": d["status"] for gw, r in edge_results.items() for dev, d in r["records"].items()},

            "devices": edge_results,

            "ingestion_summary": ingestion_summary,

        }), http_code

  

    def _send_command_to_actuators(self, command: str, actuators: dict[str, list[str]]):

        """

        Similar to _send_command_to_sensors but for actuators. The structure of the input and output is the same, but the records will have different fields based on the type of actuator and the command sent.

        """

        pass
```