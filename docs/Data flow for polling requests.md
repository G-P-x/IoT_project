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
				"type": "sensor", 
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
				"type": "sensor" 
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
				"type": "sensor" 
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
				"type": "sensor" 
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
				"type": "sensor" 
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
				"type": "sensor" 
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

Now ***`_normalized_result(result)`*** takes the result and it returns a new dictionary composed as follow:
``` python
{
	gateway_info: {
		"status": "success",
		"code": %% either response or custom error code %%,
		"error": None,
		"req_timestamp": result.get("req_timestamp"),
	},
	records: # single gateway's readings
	{
		device_id (e.g. "AABBCCDD-s1"): 
		{
			"type": "sensor",
			"status": "ERROR",
			"severity": "critical",
			"value": null,
			"message": "MPU-6050 connection lost",
			"timestamp": "2026-02-16T15:40:12Z"
			"threshold": 21.0,
		}
		"AABBCCDD-t1":
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

Next...
