import logging
from unittest.mock import MagicMock
from cloud_platform.services.database_service import DatabaseService
from cloud_platform.virtualization.digital_replica.schema_registry import SchemaRegistry
from cloud_platform.services.data_ingestion import ingest_edge_results
import json

# Setup basic logging to see what data_ingestion logs
logging.basicConfig(level=logging.INFO)

def run_test():
    # 1. Initialize the SchemaRegistry and load the YAML templates
    schema_registry = SchemaRegistry()
    schema_registry.load_schema("gateway", "cloud_platform/virtualization/templates/gateway.yaml")
    schema_registry.load_schema("sensor", "cloud_platform/virtualization/templates/sensor.yaml")
    schema_registry.load_schema("actuator", "cloud_platform/virtualization/templates/actuator.yaml")
    # For history, the data_ingestion uses sensor_history, actuator_history, gateway_history
    schema_registry.load_schema("history", "cloud_platform/virtualization/templates/sensor_history.yaml") 

    # 2. We mock the DatabaseService to capture what it does without needing a real MongoDB
    db_service = DatabaseService("mongodb://fake", "fake_db", schema_registry)
    db_service.is_connected = MagicMock(return_value=True) # bypass connection check

    # Custom mock for save_history_event to capture the history record
    def mock_save_history_event(history_event):
        print("\n" + "="*80)
        print("[HISTORY COLLECTION] Saving Event:")
        # The structure is defined by the history templates
        print(json.dumps(history_event, indent=4, default=str))
        print("="*80)

    db_service.save_history_event = mock_save_history_event

    # Custom mock for add_dr to capture new Digital Replicas
    def mock_add_dr(dr_entry):
        print("\n" + "="*80)
        col_name = schema_registry.get_collection_name(dr_entry.get("dr_type", "device"))
        print(f"[DIGITAL REPLICA] Adding new DR to '{col_name}':")
        # Simulate PyMongo adding an _id so the script doesn't fail later
        dr_entry["_id"] = dr_entry["profile"].get("device_id") or dr_entry["profile"].get("sensor_id") or "mock_id_123"
        print(json.dumps(dr_entry, indent=4, default=str))
        print("="*80)
        return dr_entry

    db_service.add_dr = mock_add_dr

    # Custom mock for update_dr to capture updates to existing Digital Replicas
    def mock_update_dr(dr_type, dr_id, update_data):
        print("\n" + "="*80)
        col_name = schema_registry.get_collection_name(dr_type)
        print(f"[DIGITAL REPLICA] Updating DR '{dr_id}' in '{col_name}':")
        # The update_data contains the modified fields using MongoDB $set syntax
        print(json.dumps(update_data, indent=4, default=str))
        print("="*80)

    db_service.update_dr = mock_update_dr

    # We simulate _find_dr by returning an empty list, which implies the DRs don't exist yet.
    # This forces data_ingestion to create them, which gives us a complete view of the payload.
    db_service.query_drs = MagicMock(return_value=[])

    # 3. Prepare the simulated Edge Results data structure
    # This simulates the normalized output of poll_gateways()
    edge_results = {
        "gateway_alpha": {
            "gateway_info": {
                "status": "success",
                "code": 200,
                "error": None,
                "req_timestamp": "2026-06-04T10:00:00Z"
            },
            "records": {
                "84F3EB12A0BC-t1": {
                    "type": "sensor",
                    "status": "OK",
                    "severity": "info",
                    "value": 24.8,
                    "message": "Temperature acquired",
                    "timestamp": "2026-06-04T09:59:58Z"
                }
            }
        }
    }

    print("\n" + "="*80)
    print("Starting ingest_edge_results test...")
    # 4. Call the function
    ingest_edge_results(db_service, edge_results, submitter="operator_01", command="cmd_01")
    print("\nTest completed.")

if __name__ == "__main__":
    run_test()
