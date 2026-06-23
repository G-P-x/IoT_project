import os
from dotenv import load_dotenv
import json


class Config:
    load_dotenv()

    # Flask
    FLASK_HOST  = os.getenv("FLASK_HOST")
    FLASK_PORT  = int(os.getenv("FLASK_PORT"))
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"

    # Server HTTP for researcher clients
    HTTP_ENDPOINT_HOST = os.getenv("HTTP_ENDPOINT_HOST", "0.0.0.0")
    HTTP_ENDPOINT_PORT = int(os.getenv("HTTP_ENDPOINT_PORT", "5000"))

    # ---------- Edge devices ----------
    # Chiave: MAC address del nodo ESP8266 (corrisponde al nodeID() del firmware).
    # Valore: URL base del gateway — gli endpoint /data e /command vengono
    #         appesi automaticamente da client_http.py tramite POLL_ENDPOINT
    #         e COMMAND_ENDPOINT.
    # Aggiorna l'IP se la rete cambia (DHCP).
    EDGE_DEVICES = {
        "A4CF12F5A331": "http://10.98.201.225:8080",
    }

    POLL_ENDPOINT    = os.getenv("POLL_ENDPOINT",    "/data")
    COMMAND_ENDPOINT = os.getenv("COMMAND_ENDPOINT", "/command")

    # HTTP Polling interval (ms)
    POLLING_INTERVAL_MS = int(os.getenv("POLLING_INTERVAL_MS", "5000"))

    # ---------- Telegram Bot ----------
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
    NGROK_AUTH_TOKEN   = os.getenv("NGROK_AUTH_TOKEN", "")
    WEBHOOK_PATH       = "/telegram"

    # ---------- MongoDB ----------
    MONGO_URI     = os.getenv("MONGO_URI",     "mongodb://localhost:27017")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "etna_iot")

    # Twin identity
    DEFAULT_TWIN_ID = os.getenv("DEFAULT_TWIN_ID", "etna_01")

    # Directories
    TEMPLATES_DIR = os.getenv("TEMPLATES_DIR", "templates")
    STATIC_DIR    = os.getenv("STATIC_DIR",    "static")

    # Commands
    COMMANDS = {
        "cmd_01": "sensor_reading_event",
        "cmd_02": "display_message",
    }