from flask import Flask
from flask_cors import CORS
from config.config import Config
import asyncio
import logging
import threading
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from pyngrok import ngrok

from cloud_platform.application.operator_api import register_operator_routes
from cloud_platform.application import client_http
from cloud_platform.telegram_bot.routes.webhook_routes import init_routes

from cloud_platform.virtualization.digital_replica.schema_registry import SchemaRegistry
from cloud_platform.services.database_service import DatabaseService
from cloud_platform.services.notification_service import NotificationService
from cloud_platform.digital_twin.dt_factory import DTFactory
from cloud_platform.application.dt_api import register_dt_api_blueprints
from config.config_loader import ConfigLoader
from cloud_platform.services.data_ingestion import ingest_edge_results

logger = logging.getLogger(__name__)


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
        return loop, loop_thread

    def _initialise_bot_application(self):
        loop, loop_thread = self._create_persistent_event_loop()
        self.application = Application.builder().token(self.cfg.TELEGRAM_BOT_TOKEN).build()
        self.application.bot_data["loop"]        = loop
        self.application.bot_data["loop_thread"] = loop_thread

    def _setup_handlers(self):
        from cloud_platform.telegram_bot.handlers.bot_handlers import (
            start_handler,
            help_handler,
            status_handler,
            chatid_handler,
            register_handler,       # nuovo handler /register
            unknown_text_handler,
        )
        self.application.add_handler(CommandHandler("start",    start_handler))
        self.application.add_handler(CommandHandler("help",     help_handler))
        self.application.add_handler(CommandHandler("status",   status_handler))
        self.application.add_handler(CommandHandler("chatid",   chatid_handler))
        self.application.add_handler(CommandHandler("register", register_handler))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text_handler))

        asyncio.run_coroutine_threadsafe(self.application.initialize(), self.application.bot_data["loop"]).result()
        asyncio.run_coroutine_threadsafe(self.application.start(),      self.application.bot_data["loop"]).result()

    def _setup_ngrok(self):
        ngrok.set_auth_token(self.cfg.NGROK_AUTH_TOKEN)
        public_url  = ngrok.connect(self.cfg.FLASK_PORT).public_url
        webhook_url = f"{public_url}{self.cfg.WEBHOOK_PATH}"
        print(f"Webhook URL: {webhook_url}")
        asyncio.run_coroutine_threadsafe(
            self.application.bot.set_webhook(webhook_url),
            self.application.bot_data["loop"],
        ).result()


class FlaskServer:
    def __init__(self, cfg: Config, telegram_application=None):
        self.cfg = cfg
        self.app = Flask(__name__, template_folder=cfg.TEMPLATES_DIR, static_folder=cfg.STATIC_DIR)
        CORS(self.app)
        self._init_dt_components()
        self._init_notification_service(telegram_application)
        self._register_blueprints(telegram_application)

    def _init_dt_components(self):
        schema_registry = SchemaRegistry()
        schema_registry.load_schema("gateway",  "cloud_platform/virtualization/templates/gateway.yaml")
        schema_registry.load_schema("sensor",   "cloud_platform/virtualization/templates/sensor.yaml")
        schema_registry.load_schema("actuator", "cloud_platform/virtualization/templates/actuator.yaml")

        db_config         = ConfigLoader.load_database_config()
        connection_string = ConfigLoader.build_connection_string(db_config)

        db_service = DatabaseService(
            connection_string=connection_string,
            db_name=db_config["settings"]["name"],
            schema_registry=schema_registry,
        )
        db_service.connect()

        dt_factory = DTFactory(db_service, schema_registry)

        self.app.config["SCHEMA_REGISTRY"] = schema_registry
        self.app.config["DB_SERVICE"]      = db_service
        self.app.config["DT_FACTORY"]      = dt_factory

    def _init_notification_service(self, telegram_application=None):
        """
        Inizializza il NotificationService e lo inietta sia in app.config
        che in bot_data (per i command handler del bot).
        """
        db_service = self.app.config.get("DB_SERVICE")
        notification_service = NotificationService(
            db_service=db_service,
            telegram_app=telegram_application,
        )
        self.app.config["NOTIFICATION_SERVICE"] = notification_service

        # Inietta in bot_data così /register può accederlo senza importare current_app
        if telegram_application:
            telegram_application.bot_data["notification_service"] = notification_service

    def _register_blueprints(self, telegram_application=None):
        register_operator_routes(self.app)
        if telegram_application is not None:
            init_routes(self.app, telegram_application)
        else:
            logger.warning("Telegram bot not initialized; webhook routes not registered.")
        register_dt_api_blueprints(self.app)

    def run(self, host: str, port: int, debug: bool, application: Application = None):
        try:
            print(f"Starting Flask server on {host}:{port} with debug={debug}")
            self.app.run(host=host, port=port, debug=debug, threaded=True)
        except Exception as e:
            print(f"Error starting Flask server: {e}")
        finally:
            if "DB_SERVICE" in self.app.config:
                self.app.config["DB_SERVICE"].disconnect()
            if application and "loop" in application.bot_data:
                loop = application.bot_data["loop"]
                try:
                    asyncio.run_coroutine_threadsafe(application.stop(),     loop).result(timeout=10)
                    asyncio.run_coroutine_threadsafe(application.shutdown(), loop).result(timeout=10)
                except Exception as e:
                    print(f"Error shutting down Telegram bot: {e}")
                finally:
                    loop.call_soon_threadsafe(loop.stop)
                    loop_thread = application.bot_data.get("loop_thread")
                    if loop_thread:
                        loop_thread.join()


class GatewayPoller:
    def __init__(self, db_service: DatabaseService, poll_interval_ms: int, notification_service=None):
        self.db_service           = db_service
        self.notification_service = notification_service
        self.poll_interval_s      = 5
        self._stop_event          = threading.Event()
        self._thread              = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        logger.info("Gateway poller started (interval=%.2fs)", self.poll_interval_s)
        while not self._stop_event.is_set():
            try:
                results = client_http.poll_gateways()
                ingest_edge_results(
                    self.db_service,
                    results,
                    submitter=None,
                    command=None,
                    notification_service=self.notification_service,
                )
            except Exception as exc:
                logger.exception("Gateway polling failed: %s", exc)
            self._stop_event.wait(self.poll_interval_s)


def _get_db_service(server: FlaskServer) -> DatabaseService:
    db_service = server.app.config.get("DB_SERVICE")
    if not db_service:
        raise RuntimeError("DB_SERVICE not initialized on Flask app")
    return db_service


def _get_notification_service(server: FlaskServer):
    return server.app.config.get("NOTIFICATION_SERVICE")


if __name__ == "__main__":
    cfg          = Config()
    telegram_bot = None

    if cfg.TELEGRAM_BOT_TOKEN:
        telegram_bot = TelegramBot(cfg)
    else:
        logger.warning("TELEGRAM_BOT_TOKEN missing; skipping Telegram bot startup.")

    server = FlaskServer(
        cfg,
        telegram_application=telegram_bot.application if telegram_bot else None,
    )

    poller = GatewayPoller(
        _get_db_service(server),
        cfg.POLLING_INTERVAL_MS,
        notification_service=_get_notification_service(server),
    )
    poller.start()

    try:
        server.run(
            host=cfg.FLASK_HOST,
            port=cfg.FLASK_PORT,
            debug=cfg.FLASK_DEBUG,
            application=telegram_bot.application if telegram_bot else None,
        )
    finally:
        poller.stop()