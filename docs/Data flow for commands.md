## send_command_to_devices()
Send a command to multiple edge devices (to the gateway it can reach the field devices)
### input:
- **command**: the command you want to execute
- **devices**: `dict{ gateway_id : list [sensor/actuators]}` connected to the gateway

1. Process the input to get 3 lists
	1. gateway_ids
	2. field_devices
	3. base_urls
2. Begin the requests to the single gateway (loop)
	1. calls `_send_http_command()` for each triplets `base_url, command, field_device`
	   It returns a dictionary equal to the one I got from `_pool_gateway()`
		``` python
		result = {
			"status": "success",
			"code": either response or custom error code,
			"req_timestamp": datetime.now(timezone.utc).isoformat()
			body: 
			[
				{
					"time_stamp": "2026-05-05T14:30:00.000Z",
					"record": {
						"id": "mpu6050_01",
						"type": "accelerometer",
						"status": "ERROR",
						"severity": "critical",
						"value": null,
						"message": "MPU-6050 connection lost",
						"timestamp": "2026-02-16T15:40:12Z"
					}
				},
				{ 
					"time_stamp": "2026-05-05T16:44:00.123Z", <-- IDENTICO 
					"record":{ 
						"id": "sensore_2", 
						"type": "sensor"
						"status": "OK"
						"severity": "info"
						"value": 55.0 
						"message": "read successful"
						"timestamp": "2026-02-16T15:40:12Z"
					} 
				}
			],
		}
		```
3. This result is passed to `_normalize_result(result)` and aggregated in `send_command_to_sensors()` to get the final result
	``` python
	results = {
		"gateway_01": # gateway ID
		{
			"gateway_info": {
				"status": "success",
				"code": 200, # either response code or custom error code,
				"error": None,
				"req_timestamp": result.get("req_timestamp"),
			}	
			"records": 
			{
				"mpu6050_01": # field device ID 
				{
					"type": "accelerometer",
					"status": "ERROR",
					"severity": "critical",
					"value": null,
					"message": "MPU-6050 connection lost",
					"timestamp": "2026-02-16T15:40:12Z"
				}
				"sensore_2": # field device ID
				{
					"type": "sensor"
						"status": "OK"
						"severity": "info"
						"value": 55.0 
						"message": "read successful"
						"timestamp": "2026-02-16T15:40:12Z"
				}
			},
		}
		
		"gateway_02": # gateway ID
		{
			gateway_info: {
				"status": "error",
				"code": 404,
				"error": "(e.g. error 404, resource not found)"
				"req_timestamp": result.get("req_timestamp"),
			}
			records:
			{}
		}
	}
	```

In `ingest_edge_results()` I have a lot of for loops.
The goals are, for each gateway_id:
1. read `records` and:
	1. retrieve the list of sensors id read (unique entries), this will be used to update the list of sensors in the gateway DR
	2. add the information about all received devices in records to the history collection
	3. for each unique sensor id, I need to know the last reading (based on timestamp) so that I can update the corresponding DR with the last reading only
2. read the `gateway_info` and add the information to the history collection
3. read the `gateway_info` and update the gateway DR

I wonder if there's a way to perform this logic without using a for loop for each task.