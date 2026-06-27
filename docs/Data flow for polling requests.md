## client_http.py
### **poll_gateways()**: 
polls all gateways for new data, for each gateway, it calls **`_poll_gateway()`** and it gets this from the single gateway:
- **time_stamp**: is the time when the gateway received the last recorded value (*same for all acquisition in the record*)
- **timestamp**: is the time at sensor/actuator level

**`_poll_gateway()`**  returns a dictionary like this to the caller ***`poll_gateways()`***:

``` python
# the result I got from the single gateway
result = {
	"status": "success",
	"code": # either response or custom error code
	"req_timestamp": datetime.now(timezone.utc).isoformat()
	body: 
	[
		{
			"time_stamp": "2026-05-05T16:44:00.123Z", <-- IDENTICO
			"record": {
				"id": "AABBCCDD-t2", # t2 for fumarole temperature
				"type": "temperature", 
				"status": "ERROR",
				"severity": "critical",
				"value": null,
				"message": "MPU-6050 connection lost",
				"timestamp": "2026-02-16T15:40:12Z",
				"threshold": 21.0,
			}
		},
		{ 
			"time_stamp": "2026-05-05T16:44:00.123Z", # <-- IDENTICO 
			"record":{ 
				"id": "AABBCCDD-t3", # t3 magmatic chamber
				"type": "temperature" 
				"status": "OK"
				"severity": "info"
				"value": 1000.0 
				"message": "read successful"
				"timestamp": "2026-02-16T15:40:12Z"
				"threshold": 21.0,
			} 
		},
		{ 
			"time_stamp": "2026-05-05T16:44:00.123Z", # <-- IDENTICO 
			"record":{ 
				"id": "AABBCCDD-t1", # t1 ground temperature
				"type": "temperature" 
				"status": "OK"
				"severity": "info"
				"value": 55.0 
				"message": "read successful"
				"timestamp": "2026-02-16T15:40:12Z"
				"threshold": 21.0,
			} 
		},
		{ 
			"time_stamp": "2026-05-05T16:44:00.123Z", # <-- IDENTICO 
			"record":{ 
				"id": "AABBCCDD-aq1", # aq1 CO2 concentration (ppm - parts per million - parti per milione)
				"type": "air_quality" 
				"status": "OK"
				"severity": "info"
				"value": 432 
				"message": "read successful"
				"timestamp": "2026-02-16T15:40:12Z"
				"threshold": 5000.0,  # recommended exposure limit
			} 
		},
		{ 
			"time_stamp": "2026-05-05T16:44:00.123Z", # <-- IDENTICO 
			"record":{ 
				"id": "AABBCCDD-aq2", # aq2 SO2 concentration (ppb - parts per billion - parti per miliardo)
				"type": "temperature" 
				"status": "OK"
				"severity": "info"
				"value": 2.5 
				"message": "read successful"
				"timestamp": "2026-02-16T15:40:12Z"
				"threshold": 35.0, # recommended exposure limit according to the World Health Organization
			} 
		}
		{ 
			"time_stamp": "2026-05-05T16:44:00.123Z", # <-- IDENTICO 
			"record":{ 
				"id": "AABBCCDD-s1", # s1 sisesmic waves
				"type": "siesmic_wave" 
				"status": "OK"
				"severity": "info"
				"value": 0.5 # m/s^2 
				"message": "read successful"
				"timestamp": "2026-02-16T15:40:12Z"
				"threshold": 1 # m/s^2 google says that 1 m/s^2 feels like the vibration of a truck passing nearby. 
			} 
		},
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
			"threshold": 21.0,
		}
		"sensore_2":
		{
			"type": "sensor"
			"status": "OK"
			"severity": "info"
			"value": 55.0 
			"message": "read successful"
			"timestamp": "2026-02-16T15:40:12Z"
			"threshold": 21.0,
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
				"threshold": 21.0,
			}
			"sensore_2":
			{
				"type": "sensor",
				"status": "OK",
				"severity": "info",
				"value": 55.0,
				"message": "read successful",
				"timestamp": "2026-02-16T15:40:12Z",
				"threshold": 21.0,
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
