#17_07_2026
"""
GatewayCode.py — Gateway IoT per il monitoraggio vulcanico
===========================================================
Ponte tra il nodo IoT (NodeMCU ESP8266) e il server cloud.
Opera su due canali paralleli in thread separati:

  1. Client MQTT (thread daemon): riceve i dati dell'ESP su iot/sensors,
     li archivia in una sliding window e analizza le anomalie critiche.
     NOTA: l'attivazione automatica del LED e' disabilitata (commentata).
     Il LED risponde solo ai comandi espliciti via POST /command.

  2. Server HTTP Flask (thread principale): espone 4 endpoint REST per
     interrogare i dati o inviare comandi all'ESP.

Topic MQTT:
  iot/sensors       <- ESP pubblica dati periodici (ogni 5s)
  iot/sensors/cmd   <- ESP risponde a cmd_01 on-demand
  iot/cmd           -> Gateway pubblica comandi verso ESP

Config esterna: config.json (nessun valore hardcoded in questo file).
"""

import json         # Serializzazione/deserializzazione JSON
import threading    # Mutex (Lock) per accesso thread-safe alle variabili condivise
import time         # sleep() per attendere che MQTT si connetta prima di Flask
import os           # os.path per costruire il percorso assoluto di config.json
from datetime import datetime, timezone  # Generazione timestamp UTC ISO-8601
from collections import deque            # deque con maxlen per la sliding window
from threading import Thread, Event      # Thread per MQTT, Event per sincronizzazione cmd_01

import paho.mqtt.client as mqtt   # Client MQTT per Python
from flask import Flask, request, jsonify  # Framework HTTP REST

# =============================================================
# CARICAMENTO CONFIGURAZIONE ESTERNA
# =============================================================
# Tutti i parametri sono in config.json: nessun valore hardcoded qui.
# Modifica config.json per cambiare IP, porte o dimensione sliding window.

# Costruisce il percorso assoluto di config.json nella stessa cartella di questo file
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

with open(_CONFIG_PATH, "r") as f:  # Apre il file di configurazione
    _cfg = json.load(f)             # Carica il JSON come dizionario Python

GATEWAY_IP  = _cfg["gateway_ip"]   # IP del PC gateway (usato solo nei log di avvio)
MQTT_HOST   = _cfg["mqtt_host"]    # IP del broker Mosquitto
MQTT_PORT   = _cfg["mqtt_port"]    # Porta MQTT (default: 1883)
HTTP_PORT   = _cfg["http_port"]    # Porta del server Flask (es. 8080)
WINDOW_SIZE = _cfg["window_size"]  # Numero massimo di record nella sliding window
CMD_TIMEOUT = _cfg["cmd_timeout"]  # Secondi di attesa per la risposta a cmd_01
TOPIC_AUTO  = _cfg["topic_auto"]   # Topic dati periodici: "iot/sensors"
TOPIC_CMD   = _cfg["topic_cmd"]    # Topic risposte on-demand: "iot/sensors/cmd"
TOPIC_PUB   = _cfg["topic_pub"]    # Topic comandi verso ESP: "iot/cmd"

# =============================================================
# STATO CONDIVISO TRA THREAD
# =============================================================
# Queste variabili sono accedute da entrambi i thread (MQTT e Flask).
# Ogni accesso in scrittura e' protetto da _lock per evitare race condition.

data_window    = deque(maxlen=WINDOW_SIZE)  # Sliding window: conserva gli ultimi N record
_lock          = threading.Lock()           # Mutex per accesso thread-safe
_last_esp_data = []                         # Cache: ultimo batch ricevuto dall'ESP (4 record)
_mqtt_client   = None                       # Riferimento al client MQTT (usato da Flask per publish)
_alarm_active  = False                      # True = allarme attualmente attivo (evita log ripetuti)

# Sincronizzazione per cmd_01 tra thread MQTT e thread Flask
_cmd_event    = Event()  # Event: set() da on_message(), wait() da receive_command()
_cmd_response = []       # Buffer: contiene la risposta ESP a cmd_01

# Errori hardware noti: condizioni transitorie normali del nodo.
# Non generano attivazione LED, ma vengono comunque archiviati nella sliding window.
IGNORED_ERRORS = [
    "MPU-6050 not available",  # Chip non trovato al boot (graceful degradation)
    "Sensor warming up",       # MQ-135 in fase di preriscaldamento (30s post-boot)
    "MPU-6050 restarting",    # Chip in reinizializzazione (freeze I2C rilevato)
]

# =============================================================
# FUNZIONI DI UTILITA'
# =============================================================

def _now() -> str:
    """Restituisce il timestamp UTC corrente in formato ISO-8601 con millisecondi.
    Esempio output: '2026-07-10T14:30:00.000Z'
    Usato per il campo time_stamp di ogni record (timestamp del gateway)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    # datetime.now(timezone.utc): ora corrente in UTC
    # .isoformat(timespec="milliseconds"): formato "2026-07-10T14:30:00.000+00:00"
    # .replace("+00:00", "Z"): sostituisce l'offset UTC con "Z" (notazione standard)


# =============================================================
# CLIENT MQTT — Callback e avvio
# =============================================================

def on_connect(client, userdata, flags, rc):
    """Callback invocata dal thread MQTT alla connessione al broker.
    rc=0 indica connessione riuscita; altri valori indicano errori."""
    if rc == 0:  # rc (return code) = 0 significa connessione riuscita
        print(f"[MQTT] Connesso a Mosquitto ({MQTT_HOST}:{MQTT_PORT})")
        client.subscribe(TOPIC_AUTO)  # Iscrive a iot/sensors (dati periodici ESP)
        client.subscribe(TOPIC_CMD)   # Iscrive a iot/sensors/cmd (risposte cmd_01)
        print(f"[MQTT] Iscritto a {TOPIC_AUTO}")
        print(f"[MQTT] Iscritto a {TOPIC_CMD}")
    else:
        print(f"[MQTT] Connessione fallita rc={rc}")  # Log del codice di errore


def on_message(client, userdata, msg):
    """Callback invocata dal thread MQTT ad ogni messaggio in arrivo.
    Gestisce due topic:
      - TOPIC_AUTO: dati periodici ESP -> aggiorna cache e sliding window
      - TOPIC_CMD:  risposta ESP a cmd_01 -> sblocca il thread Flask in attesa
    """
    global _last_esp_data, _alarm_active, _cmd_response  # Accede alle variabili globali condivise
    try:
        raw = msg.payload.decode()              # Decodifica i byte del payload MQTT in stringa UTF-8
        print(f"\n[MQTT IN] topic={msg.topic}  {len(raw)} byte")  # Log: topic e dimensione
        decoded = json.loads(raw)               # Deserializza la stringa JSON in dizionario Python
        print(json.dumps(decoded, indent=2))    # Stampa il JSON formattato (indentato di 2 spazi)

        # Trasforma ogni response dell'ESP in un record {time_stamp, record}.
        # time_stamp = timestamp del gateway (momento di ricezione del messaggio MQTT).
        # record["timestamp"] = timestamp del sensore sull'ESP (generato da getTimestamp()).
        now = _now()   # Timestamp del gateway: identico per tutti i record dello stesso batch
        records = []   # Lista che accumulera' i record trasformati
        for r in decoded.get("responses", []):       # Itera sulle responses nel payload ESP
            records.append({"time_stamp": now, "record": r})  # Aggiunge il wrapper {time_stamp, record}

        # Risposta a cmd_01: segnala al thread Flask in attesa tramite Event
        if msg.topic == TOPIC_CMD:           # E' una risposta on-demand (non dati periodici)?
            with _lock:                      # Acquisisce il mutex per accesso thread-safe
                _cmd_response = records      # Salva la risposta nel buffer condiviso
            _cmd_event.set()                 # Sblocca il thread Flask che sta aspettando in wait()
            print(f"[CMD_01] Risposta ricevuta: {len(records)} record(s)")
            return                           # Esce: le risposte cmd_01 non vanno nella sliding window

        # Dati periodici: aggiorna cache (ultimo batch) e sliding window (storico)
        with _lock:                          # Acquisisce il mutex per accesso thread-safe
            _last_esp_data = records         # Sovrascrive la cache con il batch piu' recente
        for r in records:                    # Itera su ogni record del batch
            data_window.append(r)            # Aggiunge alla sliding window (maxlen gestisce l'overflow)
        print(f"[MQTT IN] Cache aggiornata: {len(records)} record(s)")

        # Filtra le anomalie reali escludendo gli errori hardware transitori
        anomalies = [
            r for r in records               # Itera su tutti i record del batch
            if r["record"].get("status") == "ERROR"  # Considera solo gli errori
            and not any(                     # Escludi se il messaggio inizia con un errore noto
                r["record"].get("message", "").startswith(e)
                for e in IGNORED_ERRORS      # Lista degli errori hardware da ignorare
            )
        ]

        critical = [r for r in anomalies if r["record"].get("severity") == "critical"]
        # Filtra ulteriormente: solo i record con severity "critical" (non "error")

        if critical:
            # Level-triggered: riinvia alarm ON ad ogni batch finche'
            # l'anomalia persiste, compensando l'auto-spegnimento del buzzer (3s).
            if not _alarm_active:            # Prima volta che rileva il CRITICAL in questo episodio?
                _alarm_active = True         # Imposta il flag per evitare log ripetuti
                print(f"[CRITICAL] {len(critical)} anomalia/e critica/e:")
                for c in critical:           # Stampa ogni anomalia critica
                    print(f"  - {c['record']['id']}: {c['record']['message']}")
#            client.publish(TOPIC_PUB, json.dumps({"command": "alarm", "buzzer": 1}))
#            print("[MQTT OUT] Buzzer ON inviato")
            # NOTA: le righe sopra sono commentate per disattivare l'allarme automatico.
            # Il LED si attiva solo via POST /command esplicito dal server cloud.

        elif _alarm_active:                  # L'anomalia e' rientrata e il flag era attivo?
            _alarm_active = False            # Resetta il flag allarme
#            client.publish(TOPIC_PUB, json.dumps({"command": "alarm", "buzzer": 0}))
#            print("[ANOMALY] Anomalie critiche rientrate, Buzzer OFF inviato")
            # NOTA: commentato per la stessa ragione sopra (solo controllo remoto)

    except Exception as e:
        print(f"[MQTT IN] Errore: {e}")  # Cattura qualsiasi eccezione per evitare crash del thread


def on_disconnect(client, userdata, rc):
    """Callback invocata alla disconnessione dal broker.
    loop_forever() gestisce automaticamente la riconnessione."""
    print(f"[MQTT] Disconnesso rc={rc}, riconnessione automatica...")


def start_mqtt():
    """Avvia il client MQTT in un thread daemon.
    loop_forever() blocca il thread e gestisce riconnessione e heartbeat."""
    global _mqtt_client                              # Accede alla variabile globale
    _mqtt_client = mqtt.Client(client_id="gateway") # Crea client con ID fisso "gateway"
    _mqtt_client.on_connect    = on_connect          # Registra callback connessione
    _mqtt_client.on_message    = on_message          # Registra callback messaggi
    _mqtt_client.on_disconnect = on_disconnect       # Registra callback disconnessione
    _mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)  # Connette al broker (keepalive 60s)
    _mqtt_client.loop_forever()  # Loop infinito: gestisce I/O MQTT e riconnessione automatica


# =============================================================
# SERVER HTTP FLASK — Endpoint REST
# =============================================================
# Gira nel thread principale; il client MQTT gira in un thread daemon.
# E' il punto di accesso per il server cloud e gli operatori.

app = Flask(__name__)  # Crea l'applicazione Flask

@app.route("/", methods=["GET"])
def pian():
    return jsonify("Ciao")
@app.route("/command", methods=["POST"])
def receive_command():
    """
    POST /command — Invia un comando all'ESP tramite MQTT.

    Corpo JSON:
      {"command": "cmd_01", "sensors": ["MAC-t1"]}  -> lettura on-demand
      {"command": "alarm",  "buzzer": 1}             -> accende LED
      {"command": "alarm",  "buzzer": 0}             -> spegne LED

    Per cmd_01: usa Event/threading per attendere la risposta ESP (max CMD_TIMEOUT s).
    Per alarm:  inoltra su MQTT e restituisce la cache corrente.
    """
    global _cmd_event, _cmd_response               # Accede alle variabili di sincronizzazione
    cmd = request.json                             # Legge il corpo JSON della richiesta HTTP
    print(f"\n[HTTP IN] POST /command  {cmd}")     # Log della richiesta ricevuta
    if not cmd:                                    # Se il body e' vuoto o non e' JSON valido:
        return jsonify({"error": "Invalid JSON"}), 400  # Risponde con errore 400 Bad Request

    command = cmd.get("command", "")              # Estrae il campo "command" dal JSON

    if command in ["cmd_01", "mqtt_publication_interval"]:  # Attendi risposta per questi comandi                        # Comando di lettura on-demand?
        with _lock:                                         # Acquisisce il mutex per thread-safety
            _cmd_response = []                              # Svuota il buffer della risposta precedente
        _cmd_event.clear()                                  # Resetta l'Event (non segnalato)

        _mqtt_client.publish(TOPIC_PUB, json.dumps(cmd))  # Pubblica il comando su iot/cmd
        print(f"[MQTT OUT] {TOPIC_PUB} -> {cmd}")
        print(f"[CMD_01] Attendo risposta su {TOPIC_CMD} (max {CMD_TIMEOUT}s)...")

        # Blocca questo thread Flask fino a che on_message() non chiama _cmd_event.set()
        # oppure fino allo scadere del timeout CMD_TIMEOUT secondi
        got = _cmd_event.wait(timeout=CMD_TIMEOUT)  # True se segnalato, False se timeout

        if not got or not _cmd_response:           # Timeout o risposta vuota?
            now = _now()                           # Timestamp del momento del timeout
            print("[CMD_01] Timeout")
            return jsonify([{"time_stamp": now, "record": {
                "status": "ERROR", "severity": "error",  # Errore di timeout
                "type": "gateway", "id": "gateway",      # Sorgente: il gateway (non l'ESP)
                "value": None,                            # Nessun valore disponibile
                "message": f"Timeout {CMD_TIMEOUT}s: ESP non risponde",  # Messaggio descrittivo
                "timestamp": now,                         # Timestamp del timeout
                "threshold": None                         # Nessuna soglia per errori gateway
            }}]), 504  # 504 Gateway Timeout

        print(f"[CMD_01] {len(_cmd_response)} record(s) restituiti")
        return jsonify(_cmd_response)  # Restituisce la risposta ricevuta dall'ESP

    # Tutti gli altri comandi (alarm, ecc.) vengono inoltrati direttamente su MQTT
    _mqtt_client.publish(TOPIC_PUB, json.dumps(cmd))  # Pubblica il comando su iot/cmd
    print(f"[MQTT OUT] {TOPIC_PUB} -> {cmd}")

    with _lock:                                    # Acquisisce il mutex per thread-safety
        cached = list(_last_esp_data)             # Copia la cache (ultimo batch ESP)

    if not cached:                                 # Cache vuota (ESP non ha ancora pubblicato)?
        now = _now()
        return jsonify([{"time_stamp": now, "record": {
            "status": "ERROR", "severity": "error",
            "type": "gateway", "id": "gateway",
            "value": None,
            "message": "Cache vuota: attendere il primo publish dell'ESP (max 5s)",
            "timestamp": now,
            "threshold": None
        }}]), 503  # 503 Service Unavailable

    return jsonify(cached)  # Restituisce l'ultimo batch ricevuto dall'ESP


@app.route("/data", methods=["GET"])
def get_data():
    """GET /data — Restituisce la sliding window e la svuota immediatamente dopo."""
    with _lock:  # Acquisisci il mutex per evitare conflitti con il thread MQTT
        # 1. Copia i dati correnti in una lista locale
        data_to_return = list(data_window)

        # 2. Svuota la deque originale
        data_window.clear()

    # 3. Restituisci i dati che hai salvato prima di svuotare
    return jsonify(data_to_return)

@app.route("/anomalies", methods=["GET"])
def get_anomalies():
    """GET /anomalies — Restituisce i record con status=ERROR, escludendo
    gli errori hardware noti (freeze I2C, warmup). Utile per il log anomalie reali."""
    return jsonify([
        r for r in data_window                          # Itera su tutta la sliding window
        if r["record"].get("status") == "ERROR"         # Considera solo i record in errore
        and not any(                                    # Escludi se il messaggio e' un errore noto
            r["record"].get("message", "").startswith(e)
            for e in IGNORED_ERRORS                     # Lista degli errori hardware da ignorare
        )
    ])


@app.route("/critical", methods=["GET"])
def get_critical():
    """GET /critical — Restituisce solo i record con severity=critical.
    Sottoinsieme di /anomalies: esclude anche gli errori non critici (severity=error)."""
    return jsonify([
        r for r in data_window                          # Itera su tutta la sliding window
        if r["record"].get("severity") == "critical"   # Solo severity critical
    ])


def start_http():
    """Avvia il server Flask nel thread principale (bloccante)."""
    print(f"[HTTP] Server su http://{GATEWAY_IP}:{HTTP_PORT}")
    app.run(host="0.0.0.0",     # Ascolta su tutte le interfacce di rete (non solo localhost)
            port=HTTP_PORT,     # Porta configurata in config.json
            debug=False,        # Debug disabilitato in produzione
            use_reloader=False) # Disabilita il reloader automatico (incompatibile con threading)


# =============================================================
# MAIN — Avvio del gateway
# =============================================================
if __name__ == "__main__":  # Esegue solo se lo script e' avviato direttamente (non importato)
    print("\n========== GATEWAY BOOT ==========")
    print(f"  Config: {_CONFIG_PATH}")  # Mostra il percorso del file di configurazione
    print()
    print("  Topic MQTT:")
    print(f"  {TOPIC_AUTO}     <- dati periodici ESP (ogni 5s)")   # iot/sensors
    print(f"  {TOPIC_CMD} <- risposta cmd_01 on-demand")           # iot/sensors/cmd
    print(f"  {TOPIC_PUB}          -> comandi verso ESP")          # iot/cmd
    print()
    print("  Endpoints HTTP:")
    print(f"  POST /command   -> invia comando all'ESP")
    print(f"  GET  /data      -> sliding window completa (max {WINDOW_SIZE})")
    print(f"  GET  /anomalies -> tutte le anomalie reali")
    print(f"  GET  /critical  -> solo critical")
    print()

    # Avvia il client MQTT in un thread daemon (termina con il processo principale)
    Thread(target=start_mqtt, daemon=True).start()
    time.sleep(2)  # Attendi 2s: lascia che MQTT si connetta prima di avviare Flask
#
    print(f"[GATEWAY] HTTP -> http://{GATEWAY_IP}:{HTTP_PORT}")
    print(f"[GATEWAY] MQTT -> {MQTT_HOST}:{MQTT_PORT}")
    print("===================================\n")

    start_http()  # Avvia Flask nel thread principale (bloccante: non ritorna mai)