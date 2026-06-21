import json
import threading
import time
from datetime import datetime, timezone
from collections import deque
from threading import Thread, Event

import paho.mqtt.client as mqtt
from flask import Flask, request, jsonify

# ================= CONFIG =================
GATEWAY_IP      = "10.162.53.225"
MQTT_HOST       = "localhost"
MQTT_PORT       = 1883

# Topic separati:
# TOPIC_AUTO → dati periodici automatici dell'ESP (ogni 5s)
# TOPIC_CMD  → risposta a cmd_01 on-demand
# TOPIC_PUB  → comandi verso ESP
TOPIC_AUTO      = "iot/sensors"
TOPIC_CMD       = "iot/sensors/cmd"
TOPIC_PUB       = "iot/cmd"

HTTP_PORT       = 8080
WINDOW_SIZE     = 200
CMD_TIMEOUT     = 10.0

data_window    = deque(maxlen=WINDOW_SIZE)
_lock          = threading.Lock()
_last_esp_data = []
_mqtt_client   = None
_alarm_active  = False

# Sincronizzazione cmd_01
_cmd_event    = Event()
_cmd_response = []

IGNORED_ERRORS = [
    "MPU-6050 not available",
    "Sensor warming up",
]

# ================= MQTT CLIENT =================

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[MQTT] Connesso a Mosquitto ({MQTT_HOST}:{MQTT_PORT})")
        # Iscritto a entrambi i topic
        client.subscribe(TOPIC_AUTO)
        client.subscribe(TOPIC_CMD)
        print(f"[MQTT] Iscritto a {TOPIC_AUTO}")
        print(f"[MQTT] Iscritto a {TOPIC_CMD}")
    else:
        print(f"[MQTT] Connessione fallita rc={rc}")


def on_message(client, userdata, msg):
    global _last_esp_data, _alarm_active, _cmd_response
    try:
        raw = msg.payload.decode()
        print(f"\n[MQTT IN] topic={msg.topic}  {len(raw)} byte")
        decoded = json.loads(raw)
        print(json.dumps(decoded, indent=2))

        now = _now()
        records = []
        if "responses" in decoded:
            for r in decoded["responses"]:
                records.append({"time_stamp": now, "record": r})

        if msg.topic == TOPIC_CMD:
            # Risposta a cmd_01: sblocca il thread HTTP in attesa
            with _lock:
                _cmd_response = records
            _cmd_event.set()
            print(f"[CMD_01] Risposta ricevuta: {len(records)} record(s)")
            return  # non aggiorna cache né anomaly detection

        # Topic periodico: aggiorna cache e anomaly detection
        with _lock:
            _last_esp_data = records
        for r in records:
            data_window.append(r)
        print(f"[MQTT IN] Cache aggiornata: {len(records)} record(s)")

        # Anomaly detection solo sui dati periodici
        anomalies = [
            r for r in records
            if r["record"].get("status") == "ERROR"
            and not any(
                r["record"].get("message", "").startswith(e)
                for e in IGNORED_ERRORS
            )
        ]

        critical = [r for r in anomalies
                    if r["record"].get("severity") == "critical"]
        warnings = [r for r in anomalies
                    if r["record"].get("severity") == "warning"]

        if warnings:
            print(f"[WARNING] {len(warnings)} warning:")
            for w in warnings:
                print(f"  - {w['record']['id']}: {w['record']['message']}")

        if critical and not _alarm_active:
            _alarm_active = True
            print(f"[CRITICAL] {len(critical)} anomalia/e critica/e:")
            for c in critical:
                print(f"  - {c['record']['id']}: {c['record']['message']}")
            client.publish(TOPIC_PUB, json.dumps({"command": "alarm", "buzzer": 1}))
            print(f"[MQTT OUT] Buzzer ON inviato")

        elif not anomalies and _alarm_active:
            _alarm_active = False
            client.publish(TOPIC_PUB, json.dumps({"command": "alarm", "buzzer": 0}))
            print(f"[ANOMALY] Anomalie rientrate, Buzzer OFF inviato")

    except Exception as e:
        print(f"[MQTT IN] Errore: {e}")


def on_disconnect(client, userdata, rc):
    print(f"[MQTT] Disconnesso rc={rc}, riconnessione automatica...")


def start_mqtt():
    global _mqtt_client
    _mqtt_client = mqtt.Client(client_id="gateway")
    _mqtt_client.on_connect    = on_connect
    _mqtt_client.on_message    = on_message
    _mqtt_client.on_disconnect = on_disconnect
    _mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    _mqtt_client.loop_forever()


# ================= HTTP SERVER =================

app = Flask(__name__)


@app.route("/command", methods=["POST"])
def receive_command():
    global _cmd_event, _cmd_response
    cmd = request.json
    print(f"\n[HTTP IN] POST /command  {cmd}")
    if not cmd:
        return jsonify({"error": "Invalid JSON"}), 400

    command = cmd.get("command", "")

    # cmd_01: aspetta risposta real-time su iot/sensors/cmd
    if command == "cmd_01":
        with _lock:
            _cmd_response = []
        _cmd_event.clear()

        _mqtt_client.publish(TOPIC_PUB, json.dumps(cmd))
        print(f"[MQTT OUT] {TOPIC_PUB} -> {cmd}")
        print(f"[CMD_01] Attendo risposta su {TOPIC_CMD} (max {CMD_TIMEOUT}s)...")

        got = _cmd_event.wait(timeout=CMD_TIMEOUT)

        if not got or not _cmd_response:
            now = _now()
            print("[CMD_01] Timeout")
            return jsonify([{"time_stamp": now, "record": {
                "status": "ERROR", "severity": "error",
                "type": "gateway", "id": "gateway",
                "value": None,
                "message": f"Timeout {CMD_TIMEOUT}s: ESP non risponde",
                "timestamp": now
            }}]), 504

        print(f"[CMD_01] {len(_cmd_response)} record(s) restituiti")
        return jsonify(_cmd_response)

    # Altri comandi (alarm): pubblica e restituisce cache
    _mqtt_client.publish(TOPIC_PUB, json.dumps(cmd))
    print(f"[MQTT OUT] {TOPIC_PUB} -> {cmd}")

    with _lock:
        cached = list(_last_esp_data)

    if not cached:
        now = _now()
        return jsonify([{"time_stamp": now, "record": {
            "status": "ERROR", "severity": "error",
            "type": "gateway", "id": "gateway",
            "value": None,
            "message": "Cache vuota: attendere il primo publish dell'ESP (max 5s)",
            "timestamp": now
        }}]), 503

    return jsonify(cached)


@app.route("/data", methods=["GET"])
def get_data():
    return jsonify(list(data_window))


@app.route("/anomalies", methods=["GET"])
def get_anomalies():
    return jsonify([
        r for r in data_window
        if r["record"].get("status") == "ERROR"
        and not any(
            r["record"].get("message", "").startswith(e)
            for e in IGNORED_ERRORS
        )
    ])


@app.route("/warnings", methods=["GET"])
def get_warnings():
    return jsonify([
        r for r in data_window
        if r["record"].get("severity") == "warning"
    ])


@app.route("/critical", methods=["GET"])
def get_critical():
    return jsonify([
        r for r in data_window
        if r["record"].get("severity") == "critical"
    ])


def start_http():
    print(f"[HTTP] Server su http://{GATEWAY_IP}:{HTTP_PORT}")
    app.run(host="0.0.0.0", port=HTTP_PORT, debug=False, use_reloader=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ================= MAIN =================
if __name__ == "__main__":
    print("\n========== GATEWAY BOOT ==========")
    print()
    print("  Topic MQTT:")
    print(f"  {TOPIC_AUTO}     <- dati periodici ESP (ogni 5s)")
    print(f"  {TOPIC_CMD} <- risposta cmd_01 on-demand")
    print(f"  {TOPIC_PUB}          -> comandi verso ESP")
    print()
    print("  Endpoints HTTP:")
    print(f"  POST /command   -> invia comando all'ESP")
    print(f"  GET  /data      -> sliding window completa")
    print(f"  GET  /anomalies -> tutte le anomalie reali")
    print(f"  GET  /warnings  -> solo warning")
    print(f"  GET  /critical  -> solo critical")
    print()

    Thread(target=start_mqtt, daemon=True).start()
    time.sleep(2)

    print(f"[GATEWAY] HTTP -> http://{GATEWAY_IP}:{HTTP_PORT}")
    print(f"[GATEWAY] MQTT -> {MQTT_HOST}:{MQTT_PORT}")
    print("===================================\n")

    start_http()
