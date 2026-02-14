import asyncio
from flask import Blueprint, jsonify, request
from telegram import Update
from config.config import Config

webhook = Blueprint("webhook", __name__)
application = None
allowed_keys = {"text", "time_stamp", "temperature", "wind", "air_quality"}
cfg = Config()
GROUP_CHAT_ID = cfg.TELEGRAM_CHAT_ID

def init_routes(app, telegram_application=None):
    """
    Register the webhook blueprint with the Flask app and set the global application reference for the webhook routes.
    This allows the webhook routes to access the Telegram application instance and its event loop for processing updates and sending messages.
    """
    app.register_blueprint(webhook)
    global application
    application = telegram_application

@webhook.route("/telegram", methods=["POST"])
def telegram_webhook():
    """Webhook endpoint for receiving updates from Telegram"""
    if request.method == "POST":
        update = Update.de_json(request.get_json(), application.bot)
        loop = application.bot_data["loop"]
        fut = asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
        fut.result()  # wait for processing to finish, but doesn't block the event loop

    return "OK"

@webhook.route("/")
def index():
    """Root endpoint to check if the bot is active"""
    return "Bot is up and running!"

@webhook.route("/notify", methods=["POST"])
def notify():
    if not cfg.TELEGRAM_CHAT_ID:
        return jsonify({"ok": False, "error": "TELEGRAM_CHAT_ID not configured"}), 500
    
    global application
    if not application:
        return jsonify({"ok": False, "error": "application not initialized"}), 500

    payload = request.get_json(silent=True) or {}

    # Check if all keys in payload are in allowed_keys
    invalid_keys = set(payload.keys()) - allowed_keys
    if invalid_keys:
        return jsonify({"ok": False, "error": f"invalid keys: {invalid_keys}"}), 400

    text = payload.get("text")
    time_stamp = payload.get("time_stamp")
    temperature = payload.get("temperature")
    wind = payload.get("wind")
    air_quality = payload.get("air_quality")

    if not text or not time_stamp or not temperature or not wind or not air_quality:
        return jsonify({"ok": False, "error": "missing required fields"}), 400
    
    txt = f"{text}\n\nTime: {time_stamp}\nTemperature: {temperature}°C\nWind: {wind} km/h\nAir Quality: {air_quality}"
    loop = application.bot_data["loop"]

    # Push to Telegram via the background event loop (thread-safe)
    fut = asyncio.run_coroutine_threadsafe(
        application.bot.send_message(chat_id=GROUP_CHAT_ID, text=txt),
        loop
    )
    fut.result()  # raises if Telegram fails (useful for debugging)

    return jsonify({"ok": True})