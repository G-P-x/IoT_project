from flask import Flask
from flask_cors import CORS

from cloud_platform.telegram_bot.handlers.base_handlers import echo_handler, help_handler, start_handler
from config.config import Config
import asyncio
import threading
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from pyngrok import ngrok

from cloud_platform.application.operator_api import register_operator_routes
from cloud_platform.telegram_bot.routes.webhook_routes import init_routes

class TelegramBot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.application = None
        self._initialise_bot_application()
        self._setup_handlers()
        self._setup_ngrok()

    def _create_persistent_event_loop(self):
        loop = asyncio.new_event_loop()
        def _run_loop_forever(loop):
            asyncio.set_event_loop(loop)
            loop.run_forever()
        loop_thread = threading.Thread(target=_run_loop_forever, args=(loop,), daemon=True)
        loop_thread.start()
        return loop
    
    def _initialise_bot_application(self):
        # Create a persistent event loop and run it in a background thread
        loop = self._create_persistent_event_loop()

        # Initialize bot application
        self.application = Application.builder().token(self.cfg.TELEGRAM_BOT_TOKEN).build()
        self.application.bot_data["loop"] = loop  # Store loop reference for webhook routes
    
    def _setup_handlers(self):
        self.application.add_handler(CommandHandler("start", start_handler))
        self.application.add_handler(CommandHandler("help", help_handler))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_handler))
        asyncio.run_coroutine_threadsafe(self.application.initialize(), self.application.bot_data["loop"]).result()
        asyncio.run_coroutine_threadsafe(self.application.start(), self.application.bot_data["loop"]).result()

    def _setup_ngrok(self):
        ngrok.set_auth_token(self.cfg.NGROK_AUTH_TOKEN)
        public_url = ngrok.connect(self.cfg.FLASK_PORT).public_url
        webhook_url = f"{public_url}{self.cfg.WEBHOOK_PATH}"
        print(f"Webhook URL: {webhook_url}")
        asyncio.run_coroutine_threadsafe(self.application.bot.set_webhook(webhook_url), self.application.bot_data["loop"]).result()

class FlaskServer:
    """
    This class encapsulates the Flask app and its setup. 
    It creates:
    - the Flask app and configures it to handle HTTP requests from researchers and operators 
    
    """
    def __init__(self, cfg: Config, telegram_application=None):
        self.cfg = cfg
        self.app = Flask(__name__, template_folder=cfg.TEMPLATES_DIR, static_folder=cfg.STATIC_DIR)
        CORS(self.app)  # Enable CORS for all routes
        self._register_blueprints(telegram_application)

    def _register_blueprints(self, telegram_application=None):
        register_operator_routes(self.app)
        init_routes(self.app, telegram_application)

    def run(self, host: str, port: int, debug: bool, application: Application = None):
        """Start the Flask server."""
        try: 
            print(f"Starting Flask server on {host}:{port} with debug={debug}")
            self.app.run(host=host, port=port, debug=debug, threaded = True)
        except Exception as e:
            print(f"Error starting Flask server: {e}")
        finally:
            if application and "loop" in application.bot_data:
                loop = application.bot_data["loop"]
                loop.call_soon_threadsafe(loop.stop)
                loop_thread = application.bot_data.get("loop_thread")
                if loop_thread:
                    loop_thread.join()

# def create_app() -> Flask:
#     # Expose needed config to Flask
#     app.config.update(
#         DEFAULT_TWIN_ID=cfg.DEFAULT_TWIN_ID,
#         TOPIC_COMMANDS_DOWNLINK=cfg.TOPIC_COMMANDS_DOWNLINK,
#     )

#     # DB + Services
#     mongo = MongoDB(cfg.MONGO_URI, cfg.MONGO_DB_NAME)
#     dt = DTService(
#         twins=mongo.collections.twins,
#         telemetry=mongo.collections.telemetry,
#         health=mongo.collections.health,
#         commands=mongo.collections.commands,
#         anomalies=mongo.collections.anomalies,
#     )

#     # MQTT client (subscriber)
#     mqttc = MQTTClient(cfg, dt)

#     # Attach as Flask extensions so routes can access
#     app.extensions["mongo"] = mongo
#     app.extensions["dt_service"] = dt
#     app.extensions["mqtt_client"] = mqttc

#     # Register routes using Blueprints, this creates modular route groups in separate files
#     app.register_blueprint(bp_public)
#     app.register_blueprint(bp_operator)
#     app.register_blueprint(bp_commands)
#     app.register_blueprint(bp_frontend)

#     # Start MQTT once
#     # IMPORTANT: when Flask debug reloader is on, it runs twice. Avoid double-start.
#     if not cfg.FLASK_DEBUG:
#         mqttc.start()
#     else:
#         # In debug, only start MQTT in the reloader child process
#         # Werkzeug sets WERKZEUG_RUN_MAIN='true' in the child.
#         if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
#             mqttc.start()

#     return app


if __name__ == "__main__":
    cfg = Config()
    telegram_bot = TelegramBot(cfg)
    server = FlaskServer(cfg, telegram_application=telegram_bot.application)
    server.run(host=cfg.FLASK_HOST, port=cfg.FLASK_PORT, debug=cfg.FLASK_DEBUG, application=telegram_bot.application)
