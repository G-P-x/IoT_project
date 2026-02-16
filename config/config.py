import os
from dotenv import load_dotenv


class Config:
    load_dotenv()  # Load environment variables from .env file if it exists
    # Flask
    FLASK_HOST = os.getenv("FLASK_HOST")
    FLASK_PORT = int(os.getenv("FLASK_PORT"))
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"

    # Clinet HTTP Endpoint
    HTTP_ENDPOINT_HOST = os.getenv("HTTP_ENDPOINT_HOST", "0.0.0.0")
    HTTP_ENDPOINT_PORT = int(os.getenv("HTTP_ENDPOINT_PORT", "5000"))

    # Edge devices: comma-separated list of "device_id@host:port"
    # e.g. "device_01@http://192.168.1.10:5000,device_02@http://192.168.1.11:5000"
    EDGE_DEVICES_RAW = os.getenv(
        "EDGE_DEVICES",
        "device_01@http://192.168.1.10:5000,"
        "device_02@http://192.168.1.11:5001,"
        "device_03@http://192.168.1.12:5002,"
        "device_04@http://192.168.1.13:5003"
    )
    EDGE_DEVICES = {
        entry.split("@")[0]: entry.split("@")[1]
        for entry in EDGE_DEVICES_RAW.split(",") if "@" in entry
    }

    # Telegram Bot (optional, for notifications)
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")
    WEBHOOK_PATH = "/telegram"
    
    # MongoDB
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "etna_iot")

    # MQTT Broker (NOTE: this is the broker, not your python service)
    MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
    MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

    # MQTT Topics
    TOPIC_TELEMETRY = os.getenv("TOPIC_TELEMETRY","")
    TOPIC_HEALTH = os.getenv("TOPIC_HEALTH","")
    TOPIC_PUB = os.getenv("TOPIC_PUB","")

    # Twin identity
    DEFAULT_TWIN_ID = os.getenv("DEFAULT_TWIN_ID", "etna_01")

    # Directories
    TEMPLATES_DIR = os.getenv("TEMPLATES_DIR", "templates")
    STATIC_DIR = os.getenv("STATIC_DIR", "static")
