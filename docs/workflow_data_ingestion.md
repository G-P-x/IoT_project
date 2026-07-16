# Data Flow Architecture: Polling & Command Ingestion

This document details the complete end-to-end information flow for the two primary operations in the Cloud Platform: **Polling Gateways (Telemetry)** and **Sending Commands (Control)**. 

Both operations rely on edge gateway communication, but they conceptually merge into a single unified data ingestion pipeline to update the **Digital Replicas (DR)** and the **History Collection**.

---

## 1. High-Level Flow Diagram
```mermaid
flowchart TD  
%% Application Entry Point
	subgraph "Application Entry Point"  
		App{{app.py}}  
		Server([Flask])
		Poll[GatewayPoller]
		API{{OperatorAPI}}
		Service[services.py]
		Consumer[IngestionWorker]
		QIngest[(IngestionQueue)]
		
		
		App -->|Run| Server 
		Server --> |Operator HTTP requests| API
		Server --> |INIT| QIngest
		App -.-> |Starts poller| Poll --> |PUT| QIngest
		App -.-> |Starts consumer| Consumer
		App -.-> |Start services| Service
		QIngest --> |GET| Consumer
		
		
	end 

%% OPERATOR_API MODULE
	subgraph "operator_api.py"
		CMD_SEND[CommandDispatcher]
		SensSend[[send_command]]
		S[[POST /command/send]]
		cmdHTTP[[_send_command_to_*]]
		
		API --> S --> CMD_SEND --> SensSend --> cmdHTTP --> S --> |PUT| QIngest
	end
	
%% CLIENT_HTTP MODULE
	subgraph "client_http.py (Edge Communication)"  
		HTTP_GET[[poll_gateway]]  
		HTTP_POST[[send_command_to*]]
		N[[normalize_result]]
		  
		Poll --> |loop| HTTP_GET  
		cmdHTTP --> HTTP_POST  
		HTTP_GET --> N --> HTTP_GET --> |Returns standardized dict| Poll 
		HTTP_POST --> N --> HTTP_POST -->|Returns standardized dict| cmdHTTP
	end    

%% DATA INGESTION MODULE
	subgraph "data_ingestion.py (Data Processing)"
		Ingest[[ingest_edge_results]]
		AnDetector[[anomaly_detector]]
		Split{Process Gateway & Records}
		History[[save_history_event]]
		DR[[update_dr / add_dr]]
		DTS[[add_sensor_replicas]]
	 
		Consumer ==> Ingest
		Ingest ==> AnDetector   
		AnDetector ==>|set the alert_level field| Split  
		Split ==>|1 - Event Sourcing| History  
		Split ==>|2 - DR Sync| DR
		Split ==>|3 - DT Sync| DTS
		
		
		
	end  
	  
	subgraph "database_service.py (Storage)"  
		History ==> MongoDB_Hist[(History Collection)]  
		DR ==> MongoDB_DR[(Device Collection)]  
		DTS==>MongoDB_DT[(DT Collection)]

	end  
	%% --- Legend Section --- 
	subgraph Legend ["Diagram Legend: Component Shapes"]
		direction LR 
		L_Srv([Stadium Shape]) --> L_Srv_T[Server / Host] 
		L_Mod{{Hexagon}} --> L_Mod_T[Module / Package] 
		L_Cls[Rectangle] --> L_Cls_T[Class / Object] 
		L_Fn[[Double Box]] --> L_Fn_T[Function / Method] 
		
	end
	
%% --- Styling the Legend (Optional) --- 
style Legend fill:#fcfcfc,stroke:#333,stroke-dasharray: 5 5

%% Apply Colors at the very bottom 
	%% green forward
	linkStyle 0,1,8,9,10,11,15,19,2 stroke:#2ecc71,stroke-width:3.5px; 
	%% green backward
	linkStyle 20,21,12,13 stroke:#2ecc71,stroke-width:1.5px; 
	
	%% red forward
	linkStyle 3,14,16 stroke:#e67e22,stroke-width:3.5px;
	%% red backward
	linkStyle 4,17,18 stroke:#e67e22,stroke-width:1.5px;
	
	%% blue
	linkStyle 5,7 stroke:#2222e6,stroke-width:3.5px;
	
	%% fucsia #2222e6
	
```
## 2. Detailed-Level Flow Diagram

```mermaid  
flowchart TD  
%% Application Entry Point
	subgraph "Application Entry Point"  
		App{{app.py}}  
		Server([Flask])
		Poll[GatewayPoller]
		API{{OperatorAPI}}
		Services{{services.py}}
		Consumer[IngestionWorker]
		
		App -->|Run| Server 
		Server --> |Listen for HTTP requests| API
		App -.-> |Starts poller| Poll  
		App -.-> |Starts consumer| Consumer
		Poll -->|Loop every *n* seconds| Poll
		
		Poll --> Services
		
	end 
	
%% OPERATOR_API MODULE
	subgraph "operator_api.py"
		CMD_SEND[CommandDispatcher]
		SensSend[[send_command]]
		S[[POST /command/send]]
		cmdHTTP[[_send_command_to_*]]
		
		API --> S --> CMD_SEND --> SensSend --> cmdHTTP --> S
	end
	
%% CLIENT_HTTP MODULE
	subgraph "client_http.py (Edge Communication)"  
		HTTP_GET[[poll_gateway]]  
		HTTP_POST[[send_command_to*]]
		N[[normalize_result]]
		  
		Poll --> HTTP_GET  
		cmdHTTP --> HTTP_POST  
		HTTP_GET --> N --> HTTP_GET --> |Returns standardized dict| Poll 
		HTTP_POST --> N --> HTTP_POST -->|Returns standardized dict| cmdHTTP
	end    

%% DATA INGESTION MODULE
	subgraph "data_ingestion.py (Data Processing)"
		Ingest[[ingest_edge_results]]
		AnDetector[[anomaly_detector]]
		Split{Process Gateway & Records}
		History[[save_history_event]]
		DR[[update_dr / add_dr]]
		DTS[[add_sensor_replicas]]
		
		Poll -->|Calls after receiving result| Ingest  
		S-->Ingest
		Ingest ==> AnDetector   
		AnDetector ==>|set the alert_level field| Split  
		Split ==>|1 - Event Sourcing| History  
		Split ==>|2 - DR Sync| DR
		Split ==>|3 - DT Sync| DTS
		
		
		
	end  
	  
	subgraph "database_service.py (Storage)"  
		IngestionDone{Return}
		History ==> MongoDB_Hist[(History Collection)]  
		DR ==> MongoDB_DR[(Device Collection)]  
		DTS==>MongoDB_DT[(DT Collection)]
		MongoDB_Hist ==> IngestionDone
		MongoDB_DR ==> IngestionDone
		MongoDB_DT ==> IngestionDone
		IngestionDone --> Poll
	end  
	%% --- Legend Section --- 
	subgraph Legend ["Diagram Legend: Component Shapes"]
		direction LR 
		L_Srv([Stadium Shape]) --> L_Srv_T[Server / Host] 
		L_Mod{{Hexagon}} --> L_Mod_T[Module / Package] 
		L_Cls[Rectangle] --> L_Cls_T[Class / Object] 
		L_Fn[[Double Box]] --> L_Fn_T[Function / Method] 
	end
	
%% --- Styling the Legend (Optional) --- 
style Legend fill:#fcfcfc,stroke:#333,stroke-dasharray: 5 5

%% Apply Colors at the very bottom 
	%% green forward
	linkStyle 0,1,2,6,7,8,11,15 stroke:#2ecc71,stroke-width:3.5px; 
	%% green backward
	linkStyle 16,17,9,19 stroke:#2ecc71,stroke-width:1.5px; 
	
	%% red forward
	linkStyle 3,14,16 stroke:#e67e22,stroke-width:3.5px;
	%% red backward
	linkStyle 17,18 stroke:#e67e22,stroke-width:1.5px;
	
	%% blue
	linkStyle 5 stroke:#2222e6,stroke-width:3.5px;
```

---

## 2. Phase 1: Edge Communication & Convergence (`client_http.py`)

The workflow begins in the HTTP Client module, which handles parallel HTTP requests to the edge gateways.

### Flow A: Passive Polling
- **Function:** `poll_gateways()`
- **Trigger:** A background loop (e.g., `while True` timer).
- **Action:** Uses a `ThreadPoolExecutor` to execute `_poll_gateway()` for all configured `EDGE_DEVICES`. It sends a standard `GET /data` request.
- **Goal:** Periodically harvest all accumulated telemetry data from the gateways.

### Flow B: Active Commands
- **Function:** `send_command_to_sensors(command, target)`
- **Trigger:** An explicit action from an operator (`operator_api.py`) or a rule engine.
- **Action:** Uses a `ThreadPoolExecutor` to execute `_send_http_command()` to specific gateways. It sends a `POST /command` request with a JSON payload.
- **Goal:** Actively force edge devices to perform an action and immediately return the result.

### The Convergence Point: `_normalize_result()`
Regardless of whether the data was passively polled or actively requested, the raw HTTP response is passed to `_normalize_result()`. This function acts as an adapter, transforming varying edge schemas into one **Unified Data Dictionary**.

**The Unified Dictionary Structure:**
```json
{
    "gateway_alpha": {
        "gateway_info": {
            "status": "success",
            "code": 200,
            "error": null,
            "req_timestamp": "2026-06-04T10:00:00Z"
        },
        "records": {
            "84F3EB12A0BC-t1": {
                "type": "sensor",
                "status": "OK",
                "value": 24.8,
                "timestamp": "2026-06-04T09:59:58Z"
            }
        }
    }
}
```

---

## 3. Phase 2: Data Ingestion (`data_ingestion.py`)

The unified dictionary is passed directly into `ingest_edge_results(db_service, results, ...)`. This module is completely agnostic to *how* the data was collected. It now works with two views of the same gateway response:

- `raw_records`: the full list of readings received from the gateway.
- `records`: the deduplicated map keyed by device id, used for the latest state of each device.

This split is intentional:

- **History Collection** keeps every raw reading, including repeated readings for the same sensor.
- **Device Collection** and **Digital Twin** keep only the latest reading per device id.

The ingestion flow iterates through the gateway payload and performs two distinct operations for both the Gateways and the individual Sensors/Actuators.

### Operation 1: Event Sourcing (History)
Every incoming payload represents an event in time. The system records an immutable log of what happened.
1. **Gateways:** Calls `_create_gateway_record()` to generate a `gateway_status_event` tracking gateway health and HTTP codes.
2. **Devices:** Iterates over `raw_records` and calls `_create_sensor_record()` (or actuator equivalent) for every raw reading, even if the same sensor appears multiple times.
3. **Storage:** These events are passed to `db_service.save_history_event()` one by one, so History preserves all 200 readings.

### Operation 2: State Synchronization (Digital Replicas)
The Digital Replicas must reflect the *latest known state* of the edge devices.
1. **Lookup:** The system calls `_find_dr(db_service, device_id)` to see if the gateway or sensor already exists in the database.
2. **Deduplication gate:** The code keeps a `processed_devices` set so each device id updates DR/DT only once per polling cycle.
3. **If DR Exists (Update):**
	- Extracts the latest `value` and `timestamp` from `records`.
	- Calls `db_service.update_dr()` to perform a partial update (`$set`) on the DR's `data` section and bump the `metadata.last_update` timestamp.
4. **If DR is Missing (Auto-Creation):**
   - Calls `_create_gateway_dr_entry()` or `_create_sensor_dr_entry()`.
   - These functions build the initial `profile` (inferring types, generating names) and pass it to `DRFactory`.
   - The `DRFactory` validates the data against the YAML templates (`gateway.yaml`, `sensor.yaml`), applies defaults, and returns a sanitized dictionary.
   - Finally, `db_service.add_dr()` is called to insert the brand new DR into MongoDB.

### Procedure Summary
1. `poll_gateways()` or `send_command_to_sensors()` receives the edge response.
2. `_normalize_result()` stores the full response in `raw_records` and the latest per-device view in `records`.
3. `ingest_edge_results()` writes every item in `raw_records` into History.
4. The same function uses `records` to update DRs and the DT only once per device id.
5. If `raw_records` is missing, ingestion falls back to `records.values()` so the pipeline still works with older payloads.

---

## 4. Phase 3: Persistence (`database_service.py`)

The Database Service abstracts MongoDB and utilizes the `SchemaRegistry` to route data.

- **`save_history_event(history_event)`**: Inserts the immutable log entry into the history collection defined by `sensor_history.yaml`.
- **`add_dr(dr_entry)`**: Uses `schema_registry.get_collection_name(dr_type)` to determine the correct MongoDB collection (e.g., `device_collection`). The driver automatically generates the primary `_id` upon `insert_one`.
- **`update_dr(dr_type, dr_id, update_data)`**: Executes a lightweight `updateOne` operation targeting the specific `_id`, applying the nested `$set` payload, and refreshing the metadata timestamps.



```mermaid
flowchart TD
    subgraph Edge Communication
        A((Trigger)) -->|Invokes| B(poll_gateways)
        B -->|HTTP GET| C[Edge Gateways]
        C -->|Returns JSON| D[edge_results Payload]
    end

    subgraph Data Ingestion Service
        D --> E(ingest_edge_results)
        E -->|Validates| F{Pydantic EdgeResults}
        
        F --> G{For each Gateway}
        
        %% Gateway Failure Path
        G -->|Failure / Timeout| H[Save 'inactive' Gateway History]
        H --> I[Update Gateway DR as 'inactive']
        I --> Y
        
        %% Gateway Success Path
        G -->|Success| J[Save 'active' Gateway History]
        J --> K{For each Device}
        
        %% Sensor Path
        K -->|Is Sensor| L[Save Sensor History]
        L --> M{Find Sensor DR}
        M -->|Not Found| N[Auto-Create Sensor DR]
        M -->|Found| O[Update Sensor DR value/status]
        N --> O
        
        %% Actuator Path
        K -->|Is Actuator| P[Save Actuator History]
        P --> Q{Find Actuator DR}
        Q -->|Not Found| R[Auto-Create Actuator DR]
        Q -->|Found| S[Update Actuator DR state/command]
        R --> S
        
        %% Device Loop
        O --> T((Next Device))
        S --> T
        T --> K
        
        %% Gateway DR Linking
        K -->|All Devices Processed| U[Append new sensors/actuators to Gateway DR]
    end

    subgraph DB & Digital Twin Orchestration
        U --> V(dt_factory.add_digital_replicas)
        V --> W[(MongoDB & Active Twin Context)]
        
        %% Gateway Loop
        W --> Y((Next Gateway))
        Y --> G
    end
    
    G -->|All Gateways Processed| Z([End Data Flow])

    %% Styling
    classDef service fill:#f9f,stroke:#333,stroke-width:2px;
    classDef db fill:#bbf,stroke:#333,stroke-width:2px;
    class E,V service;
    class W db;
```
