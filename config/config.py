import os
from dotenv import load_dotenv


class Config:
    load_dotenv()  # Load environment variables from .env file if it exists
    # Flask
    FLASK_HOST = os.getenv("FLASK_HOST")
    FLASK_PORT = int(os.getenv("FLASK_PORT"))
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"

    # Telegram Bot (optional, for notifications)
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")
    WEBHOOK_PATH = "/telegram"
    
    # MongoDB
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "etna_iot")

    # MQTT Broker (NOTE: this is the broker, not your python service)
    MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
    MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
    MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
    MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
    MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "cloud_platform")

    # MQTT Topics
    TOPIC_TELEMETRY_BATCH = os.getenv("TOPIC_TELEMETRY_BATCH", "telemetry/batch")
    TOPIC_TELEMETRY_ONDEMAND = os.getenv("TOPIC_TELEMETRY_ONDEMAND", "telemetry/ondemand")
    TOPIC_HEALTH_EVENT = os.getenv("TOPIC_HEALTH_EVENT", "health/event")
    TOPIC_COMMANDS_DOWNLINK = os.getenv("TOPIC_COMMANDS_DOWNLINK", "commands/downlink")

    # Twin identity
    DEFAULT_TWIN_ID = os.getenv("DEFAULT_TWIN_ID", "etna_01")

    # Directories
    TEMPLATES_DIR = os.getenv("TEMPLATES_DIR", "templates")
    STATIC_DIR = os.getenv("STATIC_DIR", "static")
