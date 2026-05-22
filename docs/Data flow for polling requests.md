### **poll_gateways()**: 
polls all gateways for new data, it gets a list of jsons with this structure
calls **`_poll_gateway()`** and it gets this from the single gateway:
```
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
]

```
- time_stamp: is the time when the gateway received the last recorded value
- timestamp: is the time at sensor/actuator level

**`_poll_gateway()`**  returns a dictionary like this to the caller ***`poll_gateways()`***:

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

Then, in `poll_gateways()`, we aggregate all these `result` from the gateways to form a dictionary.
It initializes the ***``results = {}``*** and it adds the key `gateway_id: _normalized_result(result)` 

Now ***`_normalized_result(result)`*** takes the result and it creates a new dictionary composed as follow:
```
{
	gateway_info: {
		"status": "success",
		"code": %% either response or custom error code %%,
		"error": None
		"req_timestamp": result.get("req_timestamp"),
	}	
	records: # single gateway's readings
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
```
This dictionary is returned to `poll_gateways` which associates the normalized result with the corresponding gateway id.
The final result of this flow is this:
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
