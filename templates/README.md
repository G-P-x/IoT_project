# IoT Platform UI Templates

This folder contains HTML templates for the IoT platform's user interface, designed for researchers and operators to interact with the digital twin system.

## Structure

```
Templates/
├── home.html           # Dashboard and main entry point
├── history.html         # Historical data viewer
├── commands.html        # Command dispatcher
├── style.css           # Stylesheet (moved to /static)
└── README.md           # This file
```

## Pages Overview

### 1. Dashboard (`home.html`)
The main landing page that provides:
- Navigation to all other pages
- Configuration panel for setting the default Twin ID (deprecated, will be removed)
- Overview cards linking to other features
- API documentation reference (to be done eventually)

**Routes:**
- `GET /operator/home` - Dashboard

### 2. History (`history.html`)
Displays historical parameter data with statistics and chart;
All selections are performed via dropdown menu 
- Query parameters
- Select All sensor or a specific one
- Specify Twin ID (optional, uses saved default if not provided)
- Specify the records' time interval
- Automatic statistics calculation (count, average, min, max)
- View data progression in a chart.

**API Endpoint Used:**
- `GET /operator/history/<parameter>?twin_id=...&limit=...`

**Response Format:**
```json

[
  {
    "ts": "2024-02-10T12:00:00",
    "value": 23.5,
    "unit": "°C",
    "sensor_id": "temp_02"
  },
  ...
]
```

### 3. Commands (`commands.html`)
Interface for issuing commands to sensors:
- Enter command details (twin ID, operator ID, sensor ID, command ID)
- Submit commands via form
- View success/error responses
- Display command ID and status

**API Endpoint Used:**
- `POST operator/commands/send` // should be changed, I should not use a verb

**Request Body Format:**
```json
{
  target: {
    "twin_id": "etna_01",
    "sensor_id": "temp_01"   # optional, if command is for a specific sensor
  },
  command_id: "cmd_01",
  issued_by: "operator_01"   
}
```

**Response Format:**
For now just testing is done

## Features

### Data Visualization
- Historical data displayed in a chart
- Real-time statistics calculation
- Responsive design for mobile and desktop