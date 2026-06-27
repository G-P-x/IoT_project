# Data Flow: From `poll_gateways()` to Database Persistence

This document details the step-by-step journey of telemetry data, starting from the polling execution down to the MongoDB database where it is stored as Digital Replicas (DRs) and historical events.

## 1. Initiation: `poll_gateways()`
The process begins when `poll_gateways()` is triggered (either automatically via a scheduler or manually).
* **Action:** It fans out HTTP requests to the active edge gateways.
* **Output:** The gateways respond with their latest device records. These responses are aggregated into an `edge_results` dictionary, mapping each `gateway_id` to its respective `DeviceResult` (containing gateway status and a list of sensor/actuator records).

## 2. Validation & Ingestion: `ingest_edge_results()`
The `edge_results` payload is then handed off to the Data Ingestion Service, specifically the `ingest_edge_results()` function.
* **Validation:** Before processing, the shape of the data is strictly validated using Pydantic's `EdgeResults` model to ensure the payload conforms to the expected schema.

## 3. Gateway-Level Processing
The service iterates over each gateway present in the payload.
* **Gateway Failure:** If the gateway did not respond successfully (e.g., timeout, network error):
  1. A **history record** is created with status `"inactive"`.
  2. The service attempts to find the existing Gateway DR. If none exists, it creates an empty one.
  3. The Gateway DR is updated in the database with an `"inactive"` status and the latest timestamp.
  4. The process skips to the next gateway.
* **Gateway Success:** If the gateway responded successfully:
  1. An `"active"` **history record** is created for the gateway and saved via the Database Service.
  2. The service proceeds to extract individual device records (sensors and actuators).

## 4. Device-Level Processing (Sensors and Actuators)
For every successfully polled gateway, the service processes its child device records:

### Sensors
1. **History Tracking:** Generates a historical log entry (`_create_sensor_record`) containing the source, value, and status, saving it via `db_service.save_history_event()`.
2. **DR Resolution:** Calls `_find_dr()` to locate the existing Sensor Digital Replica.
3. **Auto-Creation:** If the sensor is reporting for the first time, `_create_sensor_dr_entry()` automatically creates a new DR, inferring the sensor type from the payload or its ID.
4. **State Update:** The Sensor DR is updated in the database (`db_service.update_dr()`) with the newly polled `"value"`, `"status"`, `"last_update"`, and any custom metrics (like `"threshold"`).

### Actuators
1. **History Tracking:** Generates a historical log entry (`_create_actuator_record`).
2. **State Update:** Finds the corresponding Actuator DR and updates its database record with the latest state, command, and timestamp.

## 5. Gateway DR Linking
Once all child devices are processed, the service updates the parent Gateway DR:
* It reads the Gateway DR's existing `data.sensors` and `data.actuators` lists.
* It appends any **newly discovered** sensors or actuators to these lists.
* It pushes this updated relationship model back to the database.

## 6. Digital Twin Orchestration
Finally, the physical infrastructure's virtual representation is synchronized:
* All updated Digital Replicas (the Gateway DR, Sensor DRs, and Actuator DRs) are bundled together.
* They are passed to `dt_factory.add_digital_replicas()`, which registers or refreshes them within the active Digital Twin instance, making the fresh data available to any connected analytics or prediction services.