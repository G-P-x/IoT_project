# IoT Project - Hiker Safety Monitoring System

A comprehensive IoT solution for real-time monitoring of hikers using sensor networks, edge computing with Arduino, and a cloud-based Digital Twin architecture.

## Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [System Components](#system-components)
- [Key Features](#key-features)
- [Communication Protocols](#communication-protocols)
- [Getting Started](#getting-started)
- [Project Structure](#project-structure)

---

## Overview

This IoT project implements a distributed monitoring system that combines edge computing (Arduino) with cloud-based analytics (Flask + MongoDB) to provide real-time health monitoring for hikers. The system uses a **Digital Twin** approach where the cloud maintains the authoritative state of the entire system.

### Key Design Principles
- **Single Source of Truth**: Cloud-based Digital Twin holds authoritative state
- **Smart Edge Computing**: Arduino handles local liveness detection and command execution
- **Dual Acquisition Modes**: Baseline monitoring + on-demand real-time acquisition
- **Event-Driven**: Status changes trigger notifications, not continuous streaming

---

## Architecture

```
Sensors → Arduino (Sink + Gateway + Monitor) → Cloud (Flask + Digital Twin + MongoDB) → Users
```

### Architecture Flow
1. **Sensors** measure parameters and send periodic telemetry or event-driven data
2. **Arduino** acts as sink, gateway, and local health monitor
3. **Cloud** stores authoritative state, runs analytics, and exposes APIs
4. **Users** (Hikers, Researchers, Operators) access data through the cloud interface

---

## System Components

### 1. Sensors
- Measure environmental and health parameters (temperature, seismic activity, air quality)
- Send periodic or event-driven telemetry
- Send heartbeats (low-rate, periodic)
- No direct cloud or user access
- No strict synchronization required

### 2. Arduino (Sink + Gateway + Local Health Monitor)
- **Collects** data from all connected sensors
- **Performs** local liveness detection (heartbeat timeout, sanity checks)
- **Packages** and forwards data to cloud
- **Handles** real-time command execution
- **Monitors** health status and sends health events on state changes
- Does NOT perform long-term storage or historical analysis

### 3. Cloud Backend (Flask + Digital Twin + MongoDB)
- **Stores** authoritative state (current values, timestamps, health status)
- **Maintains** history (telemetry, anomalies, commands)
- **Runs** anomaly detection and notification systems
- **Exposes** APIs and user interfaces
- **Manages** command lifecycle (requested → completed/failed)

### 4. Database (MongoDB)
- Persistent state storage
- Telemetry history
- Anomaly records
- Command logs
- Health event records

### 5. Users
- **Hikers**: Read-only access to safety information
- **Researchers/Operators**: Read detailed data, request on-demand acquisitions, receive alarms

---

## Key Features

### Dual Acquisition Policy

#### A. Baseline Monitoring (Default)
- Covers all sensors
- Periodic or event-driven
- Arduino may batch data
- Cloud ingestion not time-critical

#### B. On-Demand Real-Time Acquisition (FR7)
- Selected sensor(s) only
- Triggered by user command
- Immediate acquisition and upstream delivery
- Tagged with request metadata

### Liveness & Fault Detection
- Uses explicit heartbeats (not inferred from missing telemetry)
- Arduino tracks: `SILENT → SUSPECTED → OFFLINE → RECOVERED`
- Cloud stores health state and history
- Status changes trigger notifications

### Real-Time Alarms
- Latency target: ≤ 5 seconds
- Handled at edge (Arduino) and cloud
- Push notifications to users

### Digital Twin Model
Composed of:
- **In-memory models** (Python classes)
- **Persistent state** (MongoDB)
- **Business logic** (Flask services)

MongoDB stores state, not behavior.

---

## Communication Protocols

### Sensors ↔ Arduino
- **Networked/Constrained**: CoAP over UDP
- **Physically Attached**: I2C / SPI / UART

### Arduino ↔ Cloud
**MQTT over TCP + TLS**
  - `telemetry/batch` - Periodic sensor data
  - `telemetry/ondemand` - Requested real-time data
  - `health/event` - Status changes

### Cloud ↔ Arduino (Commands)
- **Method**: MQTT downlink (push-based, no polling)

### Cloud ↔ Users
- **Queries/Commands**: HTTPS
- **Real-time Updates**: Optional WebSocket/SSE

---

### Prerequisites
- Python 3.8+
- Flask
- MongoDB
- MQTT Broker (Mosquitto or similar)
- Arduino with network connectivity
   
---

## Design Decisions Explained

### Why Digital Twin in Cloud?
- Single authoritative source of truth
- Enables offline resilience (Arduino continues operating)
- Centralized anomaly detection and analytics

### Why Arduino Gateway?
- Local fault detection reduces cloud load
- Real-time command execution without network latency
- Graceful degradation if cloud connection fails

### Why Not Everything Real-Time?
- Baseline monitoring reduces bandwidth and power consumption
- On-demand mode provides real-time when needed
- Event-driven approach is more efficient than continuous streaming

---

## Getting Started

### Clone GitHub repository
1. **Clone the repository**
```bash
git clone <repository-url>
cd IoT_project

```
2. **Install Python dependencies**
```bash
pip install -r requirements.txt
```

## Project Structure

## License
See [LICENSE](LICENSE) for details.