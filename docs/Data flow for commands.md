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
		```
		result = {
			"status": "success",
			"code": %% either response or custom error code %%,
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
3. This result is passed to `_normalize_result(result)` and aggregated in `send_command_to_devices()` to get the final result
	```
	results = {
		gateway_id (e.g. "gateway_01") : 
		{
			gateway_info: {
				"status": "success",
				"code": %% either response or custom error code %%,
				"error": None
				"req_timestamp": result.get("req_timestamp"),
			}	
			records: 
			{
				device_id (e.g. "mpu6050_01"): 
				{
					"type": "accelerometer",
					"status": "ERROR",
					"severity": "critical",
					"value": null,
					"message": "MPU-6050 connection lost",
					"timestamp": "2026-02-16T15:40:12Z"
				}
				"sensore_2":
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
		
		"gateway_02":
		{
			gateway_info: {
				"status": "error",
				"code": %% either response or custom error code %%,
				"error": "(e.g. error 404, resource not found)"
				"req_timestamp": result.get("req_timestamp"),
			}
			records:
			{}
		}
	}
	```
