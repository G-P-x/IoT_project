import os
from dotenv import load_dotenv
import json
from dataclasses import dataclass


class Config:
    load_dotenv()  # Load environment variables from .env file if it exists
    # Flask
    FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1")
    FLASK_PORT = int(os.getenv("FLASK_PORT", 5000))
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"

    # Server HTTP  for researcher clients
    HTTP_ENDPOINT_HOST = os.getenv("HTTP_ENDPOINT_HOST", "0.0.0.0")
    HTTP_ENDPOINT_PORT = int(os.getenv("HTTP_ENDPOINT_PORT", "5000"))

    ### ---------- Edge devices ----------
    # EDGE_DEVICE = {
    #     "gateway_main": os.getenv("GATEWAY_MAIN", "http://127.0.0.1:5050"),
    # }
    if os.getenv("GATEWAY_MAIN"):
        EDGE_DEVICES = {
            "gateway_main":os.getenv("GATEWAY_MAIN", "http://127.0.0.1:5050"),
        }
    else:
        EDGE_DEVICES = {
            "gateway_main" : "http://127.0.0.1:5050",
            "gateway_02": "http://127.0.0.1:5050/gtw_02",        
        }


    POLL_ENDPOINT = os.getenv("POLL_ENDPOINT", "/data")
    # HTTP Polling interval (seconds)
    POLLING_INTERVAL_S = int(5)  # Default to 5 seconds

    COMMAND_ENDPOINT = os.getenv("COMMAND_ENDPOINT", "/command")

    ON_FIELD_ALARMS : list = [f"{gateway}{os.getenv("COMMAND_ENDPOINT", "/command")}" for gateway in EDGE_DEVICES.values()]

    ### ---------- Operator Server ----------
    OPERATOR_PORT = int(os.getenv("OPERATOR_PORT", 4500))
    OPERATOR_IP = os.getenv("OPERATOR_IP_PORT", "127.0.0.1:4500")

    WEBHOOK_OPERATOR = "http://127.0.0.1:4500/webhook/OPERATOR"
    WEBHOOK_ALERT = "http://127.0.0.1:4500/webhook/ALERT"       

    ### ---------- Telegram Bot ----------

    # Telegram Bot (optional, for notifications)
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")
    WEBHOOK_PATH = "/telegram"
    
    ### ---------- MongoDB ----------
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "etna_iot")

    # Twin identity
    DEFAULT_TWIN_ID = os.getenv("DEFAULT_TWIN_ID", "etna_01")

    # Directories
    TEMPLATES_DIR = os.getenv("TEMPLATES_DIR", "templates")
    STATIC_DIR = os.getenv("STATIC_DIR", "static")

    # commands
    COMMANDS = {
        "cmd_01": "sensor_reading_event",
        "cmd_02": "display_message",
    }

if __name__ == "__main__":
    cfg = Config()
    print(cfg.EDGE_DEVICES)
    print()
    print(cfg.ON_FIELD_ALARMS)