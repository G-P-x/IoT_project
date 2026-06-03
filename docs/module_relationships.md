# <mark style='background-color:lightgreen'>APPLICATION LAYER</mark>
# ==application.operator_api==
## Input (UI)
- JSON payload specifying the command, issuer, and target gateways/devices

## Input (application.client_http)
- Normalized execution result dictionary from command execution

## Output (application.client_http)
- Dispatched targets including base URLs, command identifiers, and affected field sensors/actuators

## Output (services.data_ingestion)
- Normalized execution results (`edge_results`) dispatched asynchronously
- Submitter information

---

# ==application.client_http==
## Input (application.operator_api)
- Dispatched targets (base URLs, command identifiers, field sensors/actuators)

## Input (Gateways)
- Raw HTTP response bodies containing timestamps and field device reading arrays or objects

## Output (application.operator_api)
- Normalized result dictionary associating each `gateway_id` to its connection status and individual sensor details

## Output (Gateways)
- Command execution payloads targeting specific sensors and actuators

## Output (services.data_ingestion)
- Normalized result dictionary generated during automated polling queries

--- 
# ==application.dt_api==
## Input (services.data_ingestion)
- Digital Twin property updates based on latest telemetry and command output
- Gateway DR state configurations

---

# <mark style='background-color: lightgreen'>SERVICE LAYER</mark>
# ==services.data_ingestion==
## Input (application.operator_api)
- Normalized execution results (`edge_results`)
- Submitter information

## Input (application.client_http)
- Normalized execution results from automated polling mechanisms

## Output (application.dt_api)
- Latest device readings and statuses to update Digital Twin properties
- Gateway Digital Replica (DR) state configuration updates

## Output (services.database_service)
- Historical records batch for devices
- `gateway_status_event` tracking success/failure statuses (source: operator or telemetry)

---
# ==services.database_service==
## Input (services.data_ingestion)
- Full records batch for device histories
- Gateway status events annotated with activity state and operation outcome

---
# <mark style='background-color:lightgreen'>TELEGRAM UI</mark>
# ==telegram_bot.webhook_routes==
## Input (Telegram)
- Webhook updates containing user messages/commands

## Input (services.analytics / services.data_ingestion)
- Notification payloads (POST requests to `/notify` with alert fields)

## Output (telegram_bot.handlers)
- Asynchronously routes processed Telegram updates and formats messages for dispatch

---

# ==telegram_bot.handlers==
## Input (telegram_bot.webhook_routes)
- Routed Telegram Update objects and alert payloads for dispatch

## Output (Telegram)
- Text replies and notifications sent to the configured Telegram chat

---
# <mark style='background-color:lightgreen'>VIRTUALIZATION LAYER</mark>
# ==virtualization.digital_replica.dr_factory==
## Input (services.data_ingestion)
- Telemetry data for creating gateway and sensor Digital Replicas

## Input (application.operator_api)
- API constraints for DR management endpoints

## Output (services.database_service)
- Validated Digital Replica documents ready for persistence

## Output (application.dt_api / digital_twin.dt_factory)
- Validated Digital Replicas for assembling Digital Twins

---
# ==virtualization.digital_replica.history_factory==
## Input (services.data_ingestion)
- Edge responses and telemetry data to create history/event records

## Input (application.operator_api)
- Operator-issued commands to create history records

## Output (services.database_service)
- Validated append-only history event records for MongoDB insertion

---

# ==virtualization.digital_replica.dr_schema_registry==
## Input (Configuration)
- YAML Digital Replica schema template files

## Output (services.database_service)
- MongoDB `$jsonSchema` validation documents for collections

## Output (digital_twin.dt_factory)
- Schemas to validate Digital Replica references

---

# ==virtualization.digital_replica.history_schema_registry==
## Input (Configuration)
- YAML history schema template files

## Output (services.database_service)
- MongoDB `$jsonSchema` validation documents for history collections

---

# ==virtualization.digital_replica.schema_registry==
## Input (virtualization.digital_replica.dr_schema_registry / history_schema_registry)
- Schemas compiled by the underlying specialized schema registries

## Output (application bootstrap / app.py)
- A backwards-compatible unified module exposing both `DRSchemaRegistry` and `HistorySchemaRegistry`
- Used across the flask application to bind schema validation dynamically

---

# ==virtualization.test_virtualization==
## Input (virtualization.digital_replica.*)
- Classes from `dr_factory`, `history_factory`, `dr_schema_registry`, and `history_schema_registry`
- Mock dictionaries with test profiles, data states, and metadata

## Output (Testing Environment)
- Verified module behaviors
- Assertions ensuring instances correctly merge with YAML templates and retain expected keys like generated timestamps (`last_update`) and identifiers (`_id`)